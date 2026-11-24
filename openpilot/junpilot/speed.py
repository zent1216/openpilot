"""준파일럿 속도 계획기: 순정 크루즈 목표 설정속도를 계산한다 (controlsd에서 100Hz 호출).

목표 = min(운전자가 정한 설정속도, 커브 제한, 단속 제한(차량 순정 내비))
- 운전자 설정속도는 따로 기억한다. 자동으로 내린 뒤에도 커브를 지나면 원래 속도로 돌아간다.
- 실제 가감속은 순정 스마트크루즈가 한다. 여기서는 설정속도만 정한다.
"""
import json
import math
import os
import time

import numpy as np

from openpilot.junpilot import store

KPH = 1 / 3.6
MIN_TARGET = 30 * KPH

# 주행 모드(가감속 성향)별 값: 커브 허용 횡가속도 보정, 미리 감속할 때의 감속도
STYLE = {
  0: {"name": "부드럽게", "lat_bias": -0.3, "decel": 0.8},
  1: {"name": "보통", "lat_bias": 0.0, "decel": 1.1},
  2: {"name": "빠르게", "lat_bias": 0.3, "decel": 1.4},
}
# 커브 감속 정도별 허용 횡가속도 (m/s^2). 0은 끔
CURVE_LAT = {0: None, 1: 2.6, 2: 2.2, 3: 1.8}

# 관리 페이지 서버(주행 기록기)가 읽는 계획기 상태. 장치에서만 기록 (PC 테스트에서는 끔)
DEBUG_PATH = os.getenv("JUNPILOT_SPEED_DEBUG", "/dev/shm/junpilot_speed.json" if os.path.isdir("/dev/shm") and os.path.exists("/AGNOS") else "")

RELEASE_MARGIN = 3 * KPH  # 제한이 이만큼 넉넉해져야 속도를 다시 올림
RELEASE_TIME = 1.0


def curve_limit(v_ego: float, velocity: list[float], yaw_rate: list[float], distance: list[float],
                max_lat: float, decel: float) -> float:
  """모델 예측 경로의 곡률로 지금 낼 수 있는 최대 속도를 계산 (m/s, 제한 없으면 inf)."""
  if not velocity or len(velocity) != len(yaw_rate) or len(velocity) != len(distance):
    return math.inf
  v = np.maximum(np.asarray(velocity, dtype=float), 1.0)
  k = np.abs(np.asarray(yaw_rate, dtype=float)) / v  # 곡률 = 요레이트 / 속도
  d = np.maximum(np.asarray(distance, dtype=float), 0.0)
  with np.errstate(divide="ignore"):
    v_turn = np.where(k > 1e-4, np.sqrt(max_lat / np.maximum(k, 1e-9)), math.inf)
  # 커브 지점까지 남은 거리 동안 decel로 줄일 수 있으므로 지금은 그만큼 더 빨라도 됨
  v_now = np.sqrt(np.square(np.minimum(v_turn, 1e3)) + 2 * decel * d)
  lim = float(np.min(v_now))
  return lim if lim < 1e3 else math.inf


class SpeedPlanner:
  def __init__(self, clock=time.monotonic):
    self.clock = clock
    self.settings = store.get_settings()
    self.settings_t = 0.0
    self.driver_set = 0.0
    self.cruise_prev = False
    self.driver_pending_t: float | None = None
    self.target = 0.0
    self.release_t: float | None = None
    self.camera_limit = math.inf
    self.debug: dict = {}
    self.debug_t = 0.0

  def _refresh_settings(self):
    now = self.clock()
    if now - self.settings_t > 1.0:
      self.settings = store.get_settings()
      self.settings_t = now

  def update(self, CS, model) -> float:
    """목표 설정속도(m/s)를 돌려준다. 0이면 자동 조절 안 함."""
    self._refresh_settings()
    now = self.clock()
    s = self.settings
    cruise = CS.cruiseState.enabled
    set_speed = CS.cruiseState.speed

    # 운전자 설정속도 기억
    if cruise and not self.cruise_prev:
      self.driver_set = set_speed
    if not cruise:
      self.driver_set = 0.0
    if any(be.type in ("accelCruise", "decelCruise", "setCruise", "resumeCruise") for be in CS.buttonEvents):
      self.driver_pending_t = now
    if self.driver_pending_t is not None and now - self.driver_pending_t > 0.6:
      self.driver_set = set_speed  # 운전자가 바꾼 값이 반영된 뒤 기억
      self.driver_pending_t = None
    self.cruise_prev = cruise

    if not s["cruise_auto"] or not cruise or self.driver_set <= 0 or self.driver_pending_t is not None:
      self.target = 0.0
      self.debug = {"driver_set": self.driver_set, "curve": 0.0, "camera": 0.0, "target": 0.0}
      self._write_debug(now)
      return 0.0

    style = STYLE.get(s["cruise_style"], STYLE[1])
    lim_curve = math.inf
    max_lat = CURVE_LAT.get(s["curve_slowdown"])
    if max_lat is not None and model is not None:
      lim_curve = curve_limit(CS.vEgo, list(model.velocity.x), list(model.orientationRate.z), list(model.position.x),
                              max_lat + style["lat_bias"], style["decel"])

    # 단속카메라·구간단속: 차량 순정 내비가 알려준 제한속도 (+여유)
    self.camera_limit = math.inf
    navi = getattr(CS, "junpilotNaviLimit", 0.0)
    if s.get("navi_slowdown", True) and navi > 0:
      self.camera_limit = navi + s.get("navi_margin", 0) * KPH

    want = max(min(self.driver_set, lim_curve, self.camera_limit), MIN_TARGET)

    # 내릴 때는 바로, 올릴 때는 여유가 생기고 잠시 유지돼야 올림 (출렁임 방지)
    if self.target <= 0 or want < self.target:
      self.target = want
      self.release_t = None
    elif want > self.target + RELEASE_MARGIN or want >= self.driver_set:
      if self.release_t is None:
        self.release_t = now
      if now - self.release_t >= RELEASE_TIME:
        self.target = want
        self.release_t = None
    else:
      self.release_t = None

    self.debug = {"driver_set": self.driver_set, "curve": lim_curve if math.isfinite(lim_curve) else 0.0,
                  "camera": self.camera_limit if math.isfinite(self.camera_limit) else 0.0, "target": self.target}
    self._write_debug(now)
    return self.target

  def _write_debug(self, now: float):
    if not DEBUG_PATH or now - self.debug_t < 0.5:
      return
    self.debug_t = now
    try:
      tmp = DEBUG_PATH + ".tmp"
      with open(tmp, "w") as f:
        json.dump({**self.debug, "mono": now}, f)
      os.replace(tmp, DEBUG_PATH)
    except OSError:
      pass
