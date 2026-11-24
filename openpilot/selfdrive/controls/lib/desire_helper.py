from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.
LANE_CHANGE_START_TIME = 0.5
AUTO_LANE_CHANGE_SPEED_MIN = 40 * CV.KPH_TO_MS  # 준파일럿 자동 차선 변경 최저 속도

class DesireHelper:
  def __init__(self, enable_bsm: bool = False):
    # 준파일럿: 자동 차선 변경 (깜빡이 후 설정 시간 지나면 핸들을 밀지 않아도 변경)
    # 측후방 감지(BSM)가 있는 차에서만 동작하고, 깜빡이 한 번에 한 번만 바꾼다
    self.enable_bsm = enable_bsm
    self.auto_delay = 0.0
    self.lane_change_enabled = True
    self.auto_settings_t = 0.0
    self.pre_timer = 0.0
    self.auto_used = False
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.prev_one_blinker = False
    self.desire = log.Desire.none

  @staticmethod
  def get_lane_change_direction(CS):
    return LaneChangeDirection.left if CS.leftBlinker else LaneChangeDirection.right

  def _refresh_auto_settings(self):
    self.auto_settings_t -= DT_MDL
    if self.auto_settings_t > 0:
      return
    self.auto_settings_t = 1.0  # 1초마다 설정 다시 읽기
    try:
      from openpilot.junpilot.store import get_settings
      mode = int(get_settings().get("lane_change_mode", 1))
    except Exception:
      mode = 1
    self.lane_change_enabled = mode != 0
    self.auto_delay = float(max(mode - 1, 0))

  def update(self, carstate, lateral_active, lane_change_prob):
    self._refresh_auto_settings()
    v_ego = carstate.vEgo
    one_blinker = carstate.leftBlinker != carstate.rightBlinker
    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX:
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.lane_change_timer = 0.0
    else:
      if (self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker and not below_lane_change_speed
          and self.lane_change_enabled):
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_timer = 0.0
        self.pre_timer = 0.0
        # Initialize lane change direction to prevent UI alert flicker
        self.lane_change_direction = self.get_lane_change_direction(carstate)

      elif self.lane_change_state == LaneChangeState.preLaneChange:
        # Update lane change direction
        self.lane_change_direction = self.get_lane_change_direction(carstate)

        torque_applied = carstate.steeringPressed and \
                         ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

        blindspot_detected = ((carstate.leftBlindspot and self.lane_change_direction == LaneChangeDirection.left) or
                              (carstate.rightBlindspot and self.lane_change_direction == LaneChangeDirection.right))

        # 옆 차선에 차가 있으면 지나간 뒤부터 다시 기다림
        self.pre_timer = 0.0 if blindspot_detected else self.pre_timer + DT_MDL
        auto_ok = (self.auto_delay > 0 and self.enable_bsm and not self.auto_used and
                   self.pre_timer >= self.auto_delay and v_ego >= AUTO_LANE_CHANGE_SPEED_MIN and not carstate.steeringPressed)

        if not one_blinker or below_lane_change_speed:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          self.lane_change_timer = 0.0
        elif (torque_applied or auto_ok) and not blindspot_detected:
          self.auto_used = self.auto_used or (auto_ok and not torque_applied)
          self.lane_change_state = LaneChangeState.laneChangeStarting
          self.lane_change_timer = 0.0

      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        self.lane_change_timer += DT_MDL

        if lane_change_prob < 0.02 and self.lane_change_timer >= LANE_CHANGE_START_TIME:
          self.lane_change_timer = 0.0
          if one_blinker:
            self.lane_change_state = LaneChangeState.preLaneChange
            self.lane_change_direction = self.get_lane_change_direction(carstate)
          else:
            self.lane_change_state = LaneChangeState.off
            self.lane_change_direction = LaneChangeDirection.none

    self.prev_one_blinker = one_blinker and lateral_active
    if not one_blinker:
      self.auto_used = False  # 깜빡이를 끄면 다음 자동 변경 허용

    self.desire = log.Desire.none
    if self.lane_change_state == LaneChangeState.laneChangeStarting:
      if self.lane_change_direction == LaneChangeDirection.left:
        self.desire = log.Desire.laneChangeLeft
      elif self.lane_change_direction == LaneChangeDirection.right:
        self.desire = log.Desire.laneChangeRight
