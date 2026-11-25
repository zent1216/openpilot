"""차량 메시지를 읽어 주행 기록기에 넣고, 휴대폰 앱으로 실시간 이벤트를 보낸다 (관리 페이지 서버의 스레드)."""
import json
import os
import queue
import threading
import logging
import time

from openpilot.junpilot import store
from openpilot.junpilot.tracker import DriveTracker, Snapshot

log = logging.getLogger("junpilot")

STATE_INTERVAL = 0.5
DEBUG_PATH = os.getenv("JUNPILOT_SPEED_DEBUG", "/dev/shm/junpilot_speed.json")


CHECKPOINT_INTERVAL = 30.0  # 주행 기록 중간 저장 간격(초)


def drives_dir() -> str:
  return os.path.join(store.data_dir(), "drives")


class Broadcaster:
  """서버 전송 이벤트(SSE) 구독자에게 메시지를 나눠 준다."""
  def __init__(self, maxsize: int = 200):
    self.lock = threading.Lock()
    self.clients: list[queue.Queue] = []
    self.maxsize = maxsize

  def subscribe(self) -> queue.Queue:
    q: queue.Queue = queue.Queue(self.maxsize)
    with self.lock:
      self.clients.append(q)
    return q

  def unsubscribe(self, q: queue.Queue):
    with self.lock:
      if q in self.clients:
        self.clients.remove(q)

  def publish(self, kind: str, data: dict):
    msg = f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with self.lock:
      for q in self.clients:
        try:
          q.put_nowait(msg)
        except queue.Full:
          pass  # 느린 구독자는 건너뜀


def read_speed_debug() -> dict:
  try:
    with open(DEBUG_PATH) as f:
      d = json.load(f)
    if time.monotonic() - d.get("mono", 0) > 2.0:
      return {}
    return d
  except (OSError, ValueError):
    return {}


def snapshot_from(sm, dbg: dict) -> Snapshot:
  cs, ss = sm['carState'], sm['selfdriveState']
  lead = sm['radarState'].leadOne
  v = cs.vEgo
  yaw = sm['modelV2'].orientationRate.z
  return Snapshot(
    t=time.monotonic(), onroad=sm['deviceState'].started, v=v, engaged=ss.enabled,
    cruise_on=cs.cruiseState.enabled, set_speed=cs.cruiseState.speed,
    target=sm['carControl'].cruiseControl.junpilotTargetSpeed,
    driver_set=dbg.get("driver_set", 0.0), curve_limit=dbg.get("curve", 0.0),
    navi_kind=cs.junpilotNaviKind if cs.junpilotNaviLimit > 0 else int(dbg.get("navi_kind", 0)),
    navi_limit=cs.junpilotNaviLimit if cs.junpilotNaviLimit > 0 else float(dbg.get("navi_limit", 0.0)),
    lead=lead.present, lead_d=lead.dRel, lead_v=lead.vLead, lead_a=lead.aLeadK,
    blinker_l=cs.leftBlinker, blinker_r=cs.rightBlinker, bsm_l=cs.leftBlindspot, bsm_r=cs.rightBlindspot,
    gas=cs.gasPressed, brake=cs.brakePressed, driver_button=len(cs.buttonEvents) > 0,
    gap=cs.junpilotCruiseGap, lat_acc=(yaw[0] * v) if len(yaw) else 0.0,
  )


def state_json(s: Snapshot) -> dict:
  k = 3.6
  return {"onroad": s.onroad, "kph": round(s.v * k), "engaged": s.engaged, "cruise": s.cruise_on,
          "set": round(s.set_speed * k), "target": round(s.target * k), "driver_set": round(s.driver_set * k),
          "curve": round(s.curve_limit * k), "navi_kind": s.navi_kind, "navi_limit": round(s.navi_limit * k),
          "lead": s.lead, "lead_d": round(s.lead_d, 1), "lead_kph": round(s.lead_v * k), "gap": s.gap,
          "bsm_l": s.bsm_l, "bsm_r": s.bsm_r, "blinker_l": s.blinker_l, "blinker_r": s.blinker_r}


class Collector:
  def __init__(self, broadcaster: Broadcaster):
    self.bc = broadcaster
    self.tracker = DriveTracker(save_dir=drives_dir())
    self.last_state: dict = {}
    self.parked = False      # P/N단에 멈춰 있음 (설정 변경 허용용)
    self.parked_t = 0.0
    self._last_state_t = 0.0
    self._last_ckpt_t = 0.0
    self.thread: threading.Thread | None = None
    self.last_error = ""  # 관리 화면 진단용

  def run(self):
    import openpilot.cereal.messaging as messaging
    sm = messaging.SubMaster(['carState', 'selfdriveState', 'radarState', 'carControl', 'modelV2', 'deviceState'])
    last_t = 0.0
    while True:
      sm.update(100)
      now = time.monotonic()
      if not sm.seen['deviceState'] or now - last_t < 0.1:  # 10Hz로 처리
        continue
      last_t = now
      # P/N 정차 판단은 다른 처리와 분리 (아래에서 오류가 나도 설정 잠금 판단은 계속 돌아야 함)
      try:
        if sm.seen['carState'] and sm.alive['carState']:
          cs = sm['carState']
          gear = str(cs.gearShifter).split('.')[-1].lower()
          self.parked = gear in ("park", "neutral") and cs.vEgo < 0.3
          self.parked_t = now
      except Exception:
        log.exception("준파일럿: 기어 상태 읽기 실패")
      try:
        self._process(sm)
      except Exception as e:
        log.exception("준파일럿: 수집 처리 실패")
        self.last_error = f"{type(e).__name__}: {e}"
        time.sleep(0.5)

  def _process(self, sm):
    snap = snapshot_from(sm, read_speed_debug())
    for ev in self.tracker.update(snap):
      self.bc.publish("event", ev)
    if self.tracker.last_saved is not None:
      self.bc.publish("drive_saved", {k: v for k, v in self.tracker.last_saved.items() if k != "events"})
      self.tracker.last_saved = None
    if snap.t - self._last_ckpt_t >= CHECKPOINT_INTERVAL:
      self._last_ckpt_t = snap.t
      self.tracker.checkpoint()
    if snap.t - self._last_state_t >= STATE_INTERVAL:
      self._last_state_t = snap.t
      self.last_state = state_json(snap)
      self.bc.publish("state", self.last_state)

  def is_parked(self) -> bool:
    return self.parked and time.monotonic() - self.parked_t < 2.0

  def start(self):
    self.thread = threading.Thread(target=self.run, daemon=True, name="junpilot-collector")
    self.thread.start()
