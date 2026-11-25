"""준파일럿: 신호 상태 추정 (당근파일럿 방식 참고).

주행 모델에는 신호등 색을 알려 주는 출력이 따로 없다. 대신 모델이 '앞차가 없는데 앞에서 멈추려는' 계획을 세우면
정지 신호(빨간불·정지선)로 보고, 그렇게 멈춰 있다가 모델이 다시 출발 계획을 세우면 출발 신호(초록불)로 본다.
실제 신호등 색을 읽는 것이 아니라서 틀릴 수 있다 (화면·음성 안내용, 차량 제어에는 쓰지 않음).
"""
import numpy as np

NONE, RED, GREEN = 0, 1, 2
STOP_SPEED = 0.3          # m/s, 모델 계획 속도가 이보다 낮아지는 지점을 정지 지점으로 봄
STOP_MAX_DIST = 80.0      # m, 이보다 먼 정지 계획은 무시
LEAD_MARGIN = 15.0        # m, 정지 지점 근처에 앞차가 있으면 앞차 때문에 서는 것
RED_HOLD = 0.6            # 초, 이만큼 이어져야 정지 신호로 봄
GREEN_HOLD = 0.5
GREEN_SHOW = 6.0          # 초, 출발 신호 표시 시간
MOVING = 2.0              # m/s
RELEASE_SPEED = 4.0       # m/s, 이보다 빨리 달리면 신호 대기 끝
MIN_STOP_DIST = 5.0       # m
LEAD_HOLD = 1.5           # 초
STANDSTILL = 0.5          # m/s


def planned_stop(vx, px) -> float | None:
  vx, px = np.asarray(vx, dtype=float), np.asarray(px, dtype=float)
  if len(vx) == 0 or len(vx) != len(px):
    return None
  stopped = np.flatnonzero(vx < STOP_SPEED)
  if not stopped.size:
    return None
  i = stopped[0]
  return 0.0 if i == 0 else float(np.interp(STOP_SPEED, vx[[i, i - 1]], px[[i, i - 1]]))


T_IDXS = np.array([10.0 * (i / 32) ** 2 for i in range(33)])  # 모델 계획 시각(초)
GO_T, GO_SPEED = 2.0, 1.0  # 2초 뒤 계획 속도가 1m/s를 넘으면 출발 계획


def go_plan(vx) -> bool:
  vx = np.asarray(vx, dtype=float)
  if len(vx) != len(T_IDXS):
    return False
  return float(np.interp(GO_T, T_IDXS, vx)) > GO_SPEED


class TrafficLight:
  """상태: NONE / RED(앞차 없이 멈추려 하거나 그렇게 멈춰 기다리는 중) / GREEN(기다리다 출발 계획이 나옴, 잠깐 표시)."""

  def __init__(self):
    self.state = NONE
    self.stop_t: float | None = None   # 달리면서 앞차 없는 정지 계획이 시작된 시각
    self.go_t: float | None = None
    self.lead_seen_t = -1e9            # 가까운 앞차를 마지막으로 본 시각 (앞차 인식이 깜빡여서 잠깐 유지)
    self.waiting = False               # 정지 신호로 멈춰 기다리는 중
    self.green_until = 0.0

  def update(self, now: float, v_ego: float, model_vx, model_px, lead_present: bool, lead_d: float) -> int:
    """매 주기 호출. 지금 상태(NONE/RED/GREEN)를 돌려준다."""
    stop_d = planned_stop(model_vx, model_px)
    if lead_present and lead_d < max(stop_d if stop_d is not None else 0.0, 0.0) + LEAD_MARGIN:
      self.lead_seen_t = now
    lead_near = now - self.lead_seen_t < LEAD_HOLD

    # 1) 달리는 중: 앞차 없이 앞에서 멈추려는 계획이 이어지면 정지 신호
    approaching = (v_ego > MOVING and stop_d is not None and MIN_STOP_DIST <= stop_d < STOP_MAX_DIST and not lead_near)
    if approaching:
      self.stop_t = self.stop_t if self.stop_t is not None else now
      if now - self.stop_t >= RED_HOLD:
        self.waiting = True
    else:
      self.stop_t = None

    if self.waiting:
      # 앞차가 끼어들어 그 뒤에 서는 것이면 신호 대기가 아님. 다시 달리기 시작해도 끝
      released = v_ego > RELEASE_SPEED and not approaching  # 정지 계획 없이 다시 달림
      if (lead_near and v_ego < MOVING and now - self.lead_seen_t < 0.1 and not approaching) or released:
        self.waiting = False
        self.go_t = None
      elif v_ego < STANDSTILL and go_plan(model_vx) and not lead_near:
        # 2) 멈춰 기다리다 출발 계획이 이어지면 출발 신호
        self.go_t = self.go_t if self.go_t is not None else now
        if now - self.go_t >= GREEN_HOLD:
          self.waiting = False
          self.go_t = None
          self.green_until = now + GREEN_SHOW
      else:
        self.go_t = None

    if self.waiting:
      self.state = RED
    elif now < self.green_until:
      self.state = GREEN
    else:
      self.state = NONE
    return self.state
