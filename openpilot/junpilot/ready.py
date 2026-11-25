"""키온(ACC)과 READY(계기판 READY, 주행 가능)를 구분한다.

콤마4는 하네스 전원 신호만 보고 '시동 켜짐'으로 판단해서, 브레이크 없이 시동 버튼만 눌러도(키온)
주행 모드로 들어간다. 그러면 설정 변경·업데이트를 할 수 없다.

PV5 실차 rlog에서 키온 → READY로 바뀌는 순간 ACCELERATOR(0x35) 3번째 바이트 4번 비트가
0 → 1로 바뀌고 그대로 유지되는 것을 확인했다. 이 비트가 0이면 정차(offroad)로 둔다.

안전장치
- 신호를 2초 넘게 못 받으면 막지 않는다(원래대로 하네스 전원만 보고 판단).
- 이미 주행 모드일 때는 READY가 10초 넘게 꺼져 있어야만 정차로 바꾼다.
- 설정 '계기판 READY일 때만 주행 모드'를 끄면 원래대로 동작한다.
"""
import json
import os
import time

STATE_PATH = os.getenv("JUNPILOT_READY_PATH", "/dev/shm/junpilot_ready.json")
READY_ADDR = 0x35
READY_BYTE, READY_BIT = 3, 4
STALE = 2.0
OFF_HOLD = 10.0
SUPPORTED = ("KIA_PV5",)


def car_supported() -> bool:
  car = os.getenv("FINGERPRINT", "")
  if not car:
    try:
      with open("/data/junpilot_car") as f:
        car = f.read().strip()
    except OSError:
      car = "KIA_PV5"
  return car in SUPPORTED


def ready_from_frame(dat: bytes) -> bool | None:
  if len(dat) <= READY_BYTE:
    return None
  return bool((dat[READY_BYTE] >> READY_BIT) & 1)


def write_state(ready: bool, path: str = STATE_PATH):
  try:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
      json.dump({"mono": time.monotonic(), "ready": ready}, f)
    os.replace(tmp, path)
  except OSError:
    pass


class ReadyGate:
  """hardwared에서 사용: 주행 모드로 들어가도 되는지."""

  def __init__(self, path: str = STATE_PATH, clock=time.monotonic):
    self.path = path
    self.clock = clock
    self.not_ready_since: float | None = None
    self.enabled = True
    self._last_cfg = -1e9

  def _read(self) -> bool | None:
    try:
      with open(self.path) as f:
        d = json.load(f)
    except (OSError, ValueError):
      return None
    if time.monotonic() - d.get("mono", 0) > STALE:
      return None
    return bool(d.get("ready"))

  def _refresh_cfg(self):
    now = self.clock()
    if now - self._last_cfg < 2.0:
      return
    self._last_cfg = now
    try:
      from openpilot.junpilot import store
      self.enabled = bool(store.get_settings().get("ready_only", True))
    except Exception:
      self.enabled = True

  def allow_onroad(self, started: bool, ready: bool | None = None) -> bool:
    self._refresh_cfg()
    if not self.enabled:
      self.not_ready_since = None
      return True
    if ready is None:
      ready = self._read()
    now = self.clock()
    if ready is None or ready:  # 신호 없음 → 막지 않음
      self.not_ready_since = None
      return True
    if self.not_ready_since is None:
      self.not_ready_since = now
    if not started:
      return False
    return now - self.not_ready_since < OFF_HOLD


def run_watcher():
  """junpilotd 스레드: CAN에서 READY 비트를 읽어 파일로 남긴다 (0.5초마다 잠깐만 읽음)."""
  if not car_supported():
    return
  import openpilot.cereal.messaging as messaging
  sock = messaging.sub_sock("can", conflate=True, timeout=50)
  while True:
    found = None
    deadline = time.monotonic() + 0.3
    while found is None and time.monotonic() < deadline:
      dat = sock.receive()
      if dat is None:
        continue
      evt = messaging.log_from_bytes(dat)
      for c in evt.can:
        if c.address == READY_ADDR and c.src == 0:
          found = ready_from_frame(bytes(c.dat))
          break
    if found is not None:
      write_state(found)
    time.sleep(0.5)
