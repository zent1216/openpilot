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
from openpilot.junpilot.cruise_learn import CruiseLearner, max_curvature
from openpilot.junpilot.nmirror import limit_from, read_road_limit

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

LEAD_THW = {1: 1.0, 2: 1.2, 3: 1.5}  # 앞차 근접 감속 기준 (초)
LEAD_CLOSING = 0.3                   # m/s, 이보다 빨리 가까워질 때만
LEAD_BELOW = 3 * KPH                 # 앞차 속도보다 이만큼 낮게
CUTIN_BELOW = 5 * KPH                # 끼어들기: 우리·끼어드는 차 중 느린 쪽보다 이만큼 낮게
LEAD_OPENING = 0.5                   # m/s, 이보다 빨리 멀어지면 '벌어짐'
LEAD_RELEASE_THW = 0.4               # 기준보다 이만큼 멀어지면 풀기
LEAD_RELEASE_TIME = 2.0              # 벌어짐이 이만큼 이어지면 풀기
LEAD_STEP = 5 * KPH                  # 설정속도는 이 단위로만 내림 (버튼 덜 누르게)
ASSIST_MIN_SPEED = 20 * KPH          # 이보다 느리면 순정이 알아서 함 (설정속도 최저 30km/h)

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
    self.has_lead = False  # controlsd가 넣어 줌 (차간거리 학습용)
    self.lead = None       # controlsd가 넣어 줌: radarState.leadOne
    self.lead_lim = math.inf
    self.cut_lim = math.inf
    self.lead_open_t: float | None = None
    self.learner: CruiseLearner | None = None
    self.learned = ""

  def _refresh_settings(self):
    now = self.clock()
    if now - self.settings_t > 1.0:
      self.settings = store.get_settings()
      self.settings_t = now
      # 스마트크루즈 자가 학습 (설정에서 끄면 쉼)
      if self.settings.get("cruise_learn", True):
        if self.learner is None:
          self.learner = CruiseLearner()
        if os.path.exists(self.learner.path + ".reset"):  # 관리 화면에서 초기화 요청
          os.remove(self.learner.path + ".reset")
          self.learner.reset()
      else:
        self.learner = None

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
    pressed = {str(be.type).split(".")[-1] for be in CS.buttonEvents if getattr(be, "pressed", True)}
    if any(be.type in ("accelCruise", "decelCruise", "setCruise", "resumeCruise") for be in CS.buttonEvents):
      self.driver_pending_t = now
    if self.driver_pending_t is not None and now - self.driver_pending_t > 0.6:
      self.driver_set = set_speed  # 운전자가 바꾼 값이 반영된 뒤 기억
      self.driver_pending_t = None
    self.cruise_prev = cruise

    k_max = max_curvature(list(model.velocity.x), list(model.orientationRate.z)) if model is not None else 0.0
    if self.learner is not None:
      lim_prev = self.debug.get("curve", 0.0) or math.inf
      cam_prev = self.debug.get("camera", 0.0) or math.inf
      got = self.learner.update(now, cruise=cruise, v_ego=CS.vEgo, k_max=k_max,
                                curve_limited=bool(self.target > 0 and lim_prev < self.driver_set - 1 * KPH),
                                camera_active=bool(self.target > 0 and cam_prev < self.driver_set - 1 * KPH),
                                accel_pressed="accelCruise" in pressed or "resumeCruise" in pressed,
                                decel_pressed="decelCruise" in pressed or "setCruise" in pressed,
                                gas_pressed=bool(getattr(CS, "gasPressed", False)), gap_pressed="gapAdjustCruise" in pressed,
                                cur_gap=int(getattr(CS, "junpilotCruiseGap", 0) or 0), has_lead=self.has_lead)
      if got:
        self.learned = got

    if not s["cruise_auto"] or not cruise or self.driver_set <= 0 or self.driver_pending_t is not None:
      self.target = 0.0
      self.debug = {"driver_set": self.driver_set, "curve": 0.0, "camera": 0.0, "target": 0.0}
      self._write_debug(now)
      return 0.0

    style = STYLE.get(s["cruise_style"], STYLE[1])
    lim_curve = math.inf
    max_lat = CURVE_LAT.get(s["curve_slowdown"])
    if max_lat is not None and model is not None:
      adj = self.learner.curve_lat_adj(k_max) if self.learner is not None else 0.0
      lim_curve = curve_limit(CS.vEgo, list(model.velocity.x), list(model.orientationRate.z), list(model.position.x),
                              max(max_lat + style["lat_bias"] + adj, 1.0), style["decel"])

    # 단속카메라·구간단속: 차량 순정 내비가 알려준 제한속도 (+여유)
    # 차량 순정 내비가 없으면 엔미러(휴대폰 TMAP)가 보낸 정보를 쓴다
    self.camera_limit = math.inf
    navi = getattr(CS, "junpilotNaviLimit", 0.0)
    navi_kind = int(getattr(CS, "junpilotNaviKind", 0)) if navi > 0 else 0
    if navi <= 0 and s.get("nmirror", True):
      navi, navi_kind = limit_from(read_road_limit(), CS.vEgo, style["decel"])
    if s.get("navi_slowdown", True) and navi > 0:
      learned_margin = self.learner.margin_adj() if self.learner is not None else 0.0
      self.camera_limit = navi + (s.get("navi_margin", 0) + learned_margin) * KPH

    lim_lead = self._lead_limit(CS, s)
    lim_cutin = self._cutin_limit(CS, s)

    want = max(min(self.driver_set, lim_curve, self.camera_limit, lim_lead, lim_cutin), MIN_TARGET)

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
                  "camera": self.camera_limit if math.isfinite(self.camera_limit) else 0.0, "target": self.target,
                  "navi_kind": navi_kind, "navi_limit": navi,
                  "lead": lim_lead if math.isfinite(lim_lead) else 0.0, "cutin": lim_cutin if math.isfinite(lim_cutin) else 0.0}
    self._write_debug(now)
    return self.target

  def _lead_limit(self, CS, s) -> float:
    """앞차에 시간 간격 기준보다 가깝고 계속 다가가면: 앞차 속도보다 조금 낮게.

    버튼을 자주 누르지 않게(크루즈 먹통 방지) 5km/h 단위로 내리고,
    한 번 켜지면 충분히 멀어지거나(기준+0.4초) 2초 넘게 벌어질 때까지 유지한다.
    """
    thw = LEAD_THW.get(int(s.get("lead_slowdown", 2)))
    l = self.lead
    now = self.clock()
    if thw is None or l is None or not l.present or CS.vEgo < ASSIST_MIN_SPEED or not CS.cruiseState.enabled:
      self.lead_lim, self.lead_open_t = math.inf, None
      return math.inf
    gap_t = l.dRel / max(CS.vEgo, 0.1)
    if not math.isfinite(self.lead_lim):
      if gap_t >= thw or l.vRel > -LEAD_CLOSING:
        return math.inf
    else:
      opening = l.vRel > LEAD_OPENING
      self.lead_open_t = (self.lead_open_t or now) if opening else None
      if gap_t >= thw + LEAD_RELEASE_THW or (self.lead_open_t is not None and now - self.lead_open_t >= LEAD_RELEASE_TIME):
        self.lead_lim, self.lead_open_t = math.inf, None
        return math.inf
    step = LEAD_STEP
    want = max(math.floor((l.vLead - LEAD_BELOW) / step) * step, MIN_TARGET)
    self.lead_lim = min(self.lead_lim, want)
    return self.lead_lim

  def _cutin_limit(self, CS, s) -> float:
    """끼어들기 감지 순간의 값으로 고정 (계속 다시 계산하면 우리 속도 따라 끝없이 내려감)."""
    v_cut = float(getattr(CS, "junpilotCutInSpeed", 0.0) or 0.0)
    if not s.get("cutin_slowdown", True) or v_cut <= 0 or CS.vEgo < ASSIST_MIN_SPEED or not CS.cruiseState.enabled:
      self.cut_lim = math.inf
      return math.inf
    if not math.isfinite(self.cut_lim):
      self.cut_lim = max(math.floor((min(CS.vEgo, v_cut) - CUTIN_BELOW) / LEAD_STEP) * LEAD_STEP, MIN_TARGET)
    return self.cut_lim

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
