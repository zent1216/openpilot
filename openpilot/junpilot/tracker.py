"""준파일럿 주행 기록기: 실시간 이벤트를 만들고, 주행이 끝나면 요약을 저장한다.

순수 로직만 담는다 (cereal 의존 없음). 관리 페이지 서버가 10Hz로 Snapshot을 넣어 준다.
이벤트 종류
  engage / disengage        오픈파일럿 켜짐/꺼짐
  navi_enter / navi_exit    단속카메라(kind=1)·구간단속(kind=2) 감속 시작/끝
  curve_slow                커브 때문에 설정속도를 낮춤
  lead_brake                앞차 급감속
  bsm_warn                  측후방 차량이 있는 쪽으로 깜빡이
  button_stuck              자동 조절 버튼이 반영되지 않는 것으로 보임
"""
import json
import os
import time
from dataclasses import dataclass, field

MS_TO_KPH = 3.6

LEAD_BRAKE_ACCEL = -3.0     # m/s^2 이보다 세게 감속하면 급감속
LEAD_BRAKE_DIST = 80.0
LEAD_BRAKE_COOLDOWN = 8.0
CURVE_SLOW_MARGIN = 5 / MS_TO_KPH
BUTTON_STUCK_TIME = 8.0
MIN_DRIVE_DIST = 300.0      # 이보다 짧은 주행은 저장하지 않음
CURVE_LAT_ACC = 1.5         # 커브로 볼 횡가속도


@dataclass
class Snapshot:
  t: float
  onroad: bool = False
  v: float = 0.0
  engaged: bool = False
  cruise_on: bool = False
  set_speed: float = 0.0
  target: float = 0.0
  driver_set: float = 0.0
  curve_limit: float = 0.0     # 0 = 제한 없음
  navi_kind: int = 0
  navi_limit: float = 0.0
  lead: bool = False
  lead_d: float = 0.0
  lead_v: float = 0.0
  lead_a: float = 0.0
  blinker_l: bool = False
  blinker_r: bool = False
  bsm_l: bool = False
  bsm_r: bool = False
  gas: bool = False
  brake: bool = False
  driver_button: bool = False
  gap: int = 0
  lat_acc: float = 0.0


@dataclass
class DriveStats:
  start: float = 0.0
  end: float = 0.0
  distance: float = 0.0
  engaged_distance: float = 0.0
  max_speed: float = 0.0
  counts: dict = field(default_factory=dict)
  # 개인 맞춤 튜닝용: 자동 감속 중 운전자 개입
  curve_brake: int = 0         # 커브 감속 중 브레이크
  curve_gas: int = 0           # 커브 감속 중 가속 페달/버튼
  navi_brake: int = 0
  navi_gas: int = 0
  curve_slow_time: float = 0.0
  driver_curve_lat: list = field(default_factory=list)  # 자동 조절 없이 운전자가 낸 커브 횡가속도 표본
  events: list = field(default_factory=list)

  def to_json(self) -> dict:
    dur = max(self.end - self.start, 1e-3)
    return {
      "start": self.start, "end": self.end, "duration_min": round(dur / 60, 1),
      "distance_km": round(self.distance / 1000, 2),
      "engaged_pct": round(100 * self.engaged_distance / max(self.distance, 1e-3), 1),
      "avg_kph": round(self.distance / dur * MS_TO_KPH, 1), "max_kph": round(self.max_speed * MS_TO_KPH, 1),
      "counts": self.counts,
      "intervention": {"curve_brake": self.curve_brake, "curve_gas": self.curve_gas,
                       "navi_brake": self.navi_brake, "navi_gas": self.navi_gas},
      "curve_slow_sec": round(self.curve_slow_time, 1),
      "driver_curve_lat_p90": round(_p90(self.driver_curve_lat), 2) if self.driver_curve_lat else None,
      "events": self.events[-300:],
    }


def _p90(xs: list) -> float:
  s = sorted(xs)
  return s[min(len(s) - 1, int(0.9 * len(s)))]


class DriveTracker:
  def __init__(self, save_dir: str | None = None, wall_clock=time.time):  # noqa: TID251  저장 파일 이름용 벽시계
    self.save_dir = save_dir
    self.wall = wall_clock
    self.prev: Snapshot | None = None
    self.stats: DriveStats | None = None
    self.navi_active = 0
    self.curve_active = False
    self.lead_brake_t = -1e9
    self.bsm_prev = (False, False)
    self.stuck_since: float | None = None
    self.stuck_reported = False
    self.last_saved: dict | None = None

  def _emit(self, s: Snapshot, etype: str, **data) -> dict:
    ev = {"type": etype, "t": round(s.t, 2), "wall": int(self.wall()), "kph": round(s.v * MS_TO_KPH), **data}
    if self.stats is not None:
      self.stats.counts[etype] = self.stats.counts.get(etype, 0) + 1
      self.stats.events.append(ev)
    return ev

  def update(self, s: Snapshot) -> list[dict]:
    out: list[dict] = []
    p = self.prev or Snapshot(t=s.t)
    dt = max(0.0, min(s.t - p.t, 1.0)) if self.prev else 0.0

    # 주행 시작/끝
    if s.onroad and self.stats is None:
      self.stats = DriveStats(start=self.wall())
    if not s.onroad and self.stats is not None:
      self._finish()
      self.prev = s
      return out
    st = self.stats
    if st is not None:
      st.distance += s.v * dt
      if s.engaged:
        st.engaged_distance += s.v * dt
      st.max_speed = max(st.max_speed, s.v)

    if s.engaged and not p.engaged:
      out.append(self._emit(s, "engage"))
    if p.engaged and not s.engaged and s.v > 5:
      out.append(self._emit(s, "disengage"))

    # 단속 감속
    kind = s.navi_kind if s.navi_limit > 0 else 0
    if kind and kind != self.navi_active:
      out.append(self._emit(s, "navi_enter", kind=kind, limit=round(s.navi_limit * MS_TO_KPH)))
    elif not kind and self.navi_active:
      out.append(self._emit(s, "navi_exit", kind=self.navi_active))
    self.navi_active = kind

    # 커브 감속: 커브 제한이 운전자 속도보다 충분히 낮을 때
    curve = bool(s.cruise_on and s.curve_limit > 0 and s.driver_set > 0 and s.curve_limit < s.driver_set - CURVE_SLOW_MARGIN)
    if curve and not self.curve_active:
      out.append(self._emit(s, "curve_slow", limit=round(s.curve_limit * MS_TO_KPH)))
    self.curve_active = curve

    # 자동 감속 중 운전자 개입 (튜닝 추천 재료)
    if st is not None:
      gas_now = (s.gas and not p.gas) or (s.driver_button and not p.driver_button and s.set_speed > p.set_speed)
      brake_now = s.brake and not p.brake
      if curve:
        st.curve_slow_time += dt
        st.curve_brake += int(brake_now)
        st.curve_gas += int(gas_now)
      if kind:
        st.navi_brake += int(brake_now)
        st.navi_gas += int(gas_now)
      if not s.engaged and abs(s.lat_acc) > CURVE_LAT_ACC and s.v > 10:
        if len(st.driver_curve_lat) < 5000:
          st.driver_curve_lat.append(abs(s.lat_acc))

    # 앞차 급감속
    if s.lead and s.lead_d < LEAD_BRAKE_DIST and s.lead_a < LEAD_BRAKE_ACCEL and s.t - self.lead_brake_t > LEAD_BRAKE_COOLDOWN:
      self.lead_brake_t = s.t
      out.append(self._emit(s, "lead_brake", dist=round(s.lead_d), accel=round(s.lead_a, 1)))

    # 측후방 차량 쪽으로 깜빡이
    bsm = (s.bsm_l and s.blinker_l, s.bsm_r and s.blinker_r)
    for side, (now, before) in zip(("left", "right"), zip(bsm, self.bsm_prev, strict=True), strict=True):
      if now and not before:
        out.append(self._emit(s, "bsm_warn", side=side))
    self.bsm_prev = bsm

    # 버튼 반영 안 됨: 목표와 설정속도가 오래 다름
    mismatch = s.engaged and s.cruise_on and s.target > 0 and abs(s.target - s.set_speed) * MS_TO_KPH >= 2 \
      and not s.gas and not s.brake and not s.driver_button
    if mismatch:
      self.stuck_since = self.stuck_since if self.stuck_since is not None else s.t
      if s.t - self.stuck_since > BUTTON_STUCK_TIME and not self.stuck_reported:
        self.stuck_reported = True
        out.append(self._emit(s, "button_stuck", target=round(s.target * MS_TO_KPH), set=round(s.set_speed * MS_TO_KPH)))
    else:
      self.stuck_since = None
      self.stuck_reported = False

    self.prev = s
    return out

  def _write(self, st: DriveStats, in_progress: bool) -> dict | None:
    if st.distance < MIN_DRIVE_DIST:
      return None
    data = st.to_json()
    if in_progress:
      data["in_progress"] = True
    if self.save_dir:
      os.makedirs(self.save_dir, exist_ok=True)
      name = time.strftime("%Y%m%d-%H%M%S", time.localtime(st.start)) + ".json"
      tmp = os.path.join(self.save_dir, name + ".tmp")
      with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
      os.replace(tmp, os.path.join(self.save_dir, name))
      # 최근 100개만 보관
      files = sorted(x for x in os.listdir(self.save_dir) if x.endswith(".json"))
      for old in files[:-100]:
        os.remove(os.path.join(self.save_dir, old))
    return data

  def checkpoint(self):
    """주행 중간 저장. 시동을 끄기 전에 전원이 꺼지거나 업데이트로 재부팅돼도 기록이 남게 한다."""
    if self.stats is not None:
      self.stats.end = self.wall()
      self._write(self.stats, in_progress=True)

  def _finish(self):
    st, self.stats = self.stats, None
    self.navi_active, self.curve_active = 0, False
    st.end = self.wall()
    data = self._write(st, in_progress=False)
    if data is not None:
      self.last_saved = data


def list_drives(save_dir: str) -> list[dict]:
  out = []
  if not os.path.isdir(save_dir):
    return out
  for name in sorted((x for x in os.listdir(save_dir) if x.endswith(".json") and x[:1].isdigit()), reverse=True):
    try:
      with open(os.path.join(save_dir, name)) as f:
        d = json.load(f)
    except (OSError, ValueError):
      continue
    d.pop("events", None)
    out.append({"id": name[:-5], **d})
  return out


def load_drive(save_dir: str, drive_id: str) -> dict:
  if not drive_id.replace("-", "").isdigit():
    raise ValueError("잘못된 주행 기록이에요.")
  with open(os.path.join(save_dir, drive_id + ".json")) as f:
    return {"id": drive_id, **json.load(f)}


def tuning_suggestions(drives: list[dict], settings: dict) -> list[dict]:
  """최근 주행의 운전자 개입을 보고 설정 변경을 추천한다 (적용은 사용자가 직접)."""
  recent = drives[:10]
  if len(recent) < 2:
    return [{"key": None, "reason": "주행 기록이 2개 이상 쌓이면 추천해 드릴게요."}]
  tot = {k: sum(d.get("intervention", {}).get(k, 0) for d in recent) for k in ("curve_brake", "curve_gas", "navi_brake", "navi_gas")}
  slow_min = sum(d.get("curve_slow_sec", 0) for d in recent) / 60
  out = []
  cs = settings.get("curve_slowdown", 2)
  if tot["curve_brake"] >= 3 and tot["curve_brake"] > 2 * tot["curve_gas"] and cs < 3:
    out.append({"key": "curve_slowdown", "value": cs + 1,
                "reason": f"커브 감속 중 브레이크를 {tot['curve_brake']}번 밟으셨어요. 커브에서 조금 더 일찍, 더 많이 감속할게요."})
  elif tot["curve_gas"] >= 3 and tot["curve_gas"] > 2 * tot["curve_brake"] and cs > 1:
    out.append({"key": "curve_slowdown", "value": cs - 1,
                "reason": f"커브 감속 중 가속을 {tot['curve_gas']}번 하셨어요. 커브 감속을 조금 줄일게요."})
  style = settings.get("cruise_style", 1)
  if tot["curve_brake"] + tot["navi_brake"] >= 5 and style > 0 and tot["curve_gas"] + tot["navi_gas"] == 0:
    out.append({"key": "cruise_style", "value": style - 1, "reason": "자동 감속 중 브레이크가 잦아요. 주행 모드를 한 단계 부드럽게 바꿔 보세요."})
  margin = settings.get("navi_margin", 0)
  if tot["navi_brake"] >= 3 and margin > -5:
    out.append({"key": "navi_margin", "value": max(-5, margin - 5),
                "reason": f"단속 구간에서 브레이크를 {tot['navi_brake']}번 밟으셨어요. 단속 속도 여유를 낮출게요."})
  if not out:
    out.append({"key": None, "reason": f"최근 {len(recent)}번 주행에서 지금 설정이 잘 맞았어요 (커브 감속 {slow_min:.0f}분)."})
  return out
