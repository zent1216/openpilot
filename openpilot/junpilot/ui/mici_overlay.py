"""준파일럿: 콤마4(mici) 주행 화면 추가 표시.

- 깜빡이 방향 예상 차선 (파란색)
- 측후방 차량 접근 경고 (화면 가장자리 빨간 막대, 그쪽 깜빡이를 켜면 깜빡임)
  경고음은 공식 '차선 변경 차단(laneChangeBlocked)' 알림이 담당
- 순정 크루즈 차간거리 단계 (왼쪽 아래 막대 4개)
앞차 추적 표시는 mici/onroad/model_renderer.py 의 리드 막대를 순정 크루즈 차량에서도 켜서 보여준다.
장치 글꼴에 한글이 없을 수 있어 화면에는 숫자·도형만 그린다.
"""
import math

import numpy as np
import raylib_nb as rl

from openpilot.system.ui.lib.polygon import draw_polygon

LANE_COLOR = (55, 138, 221)
BSM_COLOR = (226, 75, 74)
DEFAULT_LANE_WIDTH = 3.6
LANE_LINE_PROB = 0.3
TARGET_LANE_DIST = (4.0, 60.0)
BSM_WIDTH = 16


def target_lane_corners(lines: list[np.ndarray], probs: np.ndarray, path: np.ndarray, left: bool, z_off: float) -> np.ndarray | None:
  """옆 차선 영역을 차량 좌표(x 앞, y 왼쪽+, z)의 다각형 꼭짓점으로 반환.

  lines: 모델 차선 4개 [먼 왼쪽, 왼쪽, 오른쪽, 먼 오른쪽], 각 (N,3)
  내 차선 쪽 선은 보이면 그 선, 바깥 선이 안 보이면 차선 폭 3.6m 가정.
  모델 좌표의 y는 오른쪽이 +이므로 그대로 쓴다 (draw는 변환 행렬이 처리).
  """
  inner_i, outer_i = (1, 0) if left else (2, 3)
  inner, outer = lines[inner_i], lines[outer_i]
  if len(path) < 2 or len(inner) < 2 or probs[inner_i] < LANE_LINE_PROB:
    return None
  xs = np.linspace(*TARGET_LANE_DIST, 12)
  xs = xs[xs <= inner[-1, 0]]
  if len(xs) < 2:
    return None
  y_in = np.interp(xs, inner[:, 0], inner[:, 1])
  sign = -1.0 if left else 1.0
  if len(outer) >= 2 and probs[outer_i] >= LANE_LINE_PROB:
    y_out = np.interp(xs, outer[:, 0], outer[:, 1])
  else:
    y_out = y_in + sign * DEFAULT_LANE_WIDTH
  z = np.interp(xs, path[:, 0], path[:, 2]) + z_off
  near_side = np.column_stack((xs, y_in, z))
  far_side = np.column_stack((xs, y_out, z))[::-1]
  return np.vstack((near_side, far_side)).astype(np.float32)


def project(transform: np.ndarray, corners: np.ndarray) -> np.ndarray | None:
  pts = transform @ corners.T
  if np.any(pts[2] <= 1e-3):
    return None
  return (pts[:2] / pts[2]).T.astype(np.float32)


class JunpilotOverlay:
  def __init__(self):
    self.lane_alpha = 0.0
    self.bsm_alpha = [0.0, 0.0]

  @staticmethod
  def _ease(cur: float, target: float, rate: float = 0.25) -> float:
    return cur + (target - cur) * rate

  def render(self, rect: rl.Rectangle, model_renderer, sm, engaged: bool):
    cs = sm['carState']
    self._draw_target_lane(rect, model_renderer, cs)
    self._draw_bsm(rect, cs)
    if cs.cruiseState.enabled and cs.junpilotCruiseGap > 0:
      self._draw_gap(rect, cs.junpilotCruiseGap)

  def _draw_target_lane(self, rect, mr, cs):
    left = cs.leftBlinker and not cs.rightBlinker
    right = cs.rightBlinker and not cs.leftBlinker
    self.lane_alpha = self._ease(self.lane_alpha, 0.35 if (left or right) else 0.0)
    if self.lane_alpha < 0.02 or not (left or right):
      return
    lines = [ll.raw_points for ll in mr._lane_lines]
    corners = target_lane_corners(lines, mr._lane_line_probs, mr._path.raw_points, left, mr._path_offset_z)
    if corners is None:
      return
    pts = project(mr._car_space_transform, corners)
    if pts is None:
      return
    pts = pts + np.array([mr._rect.x, mr._rect.y], dtype=np.float32)
    blocked = cs.leftBlindspot if left else cs.rightBlindspot
    color = BSM_COLOR if blocked else LANE_COLOR
    draw_polygon(rect, pts, rl.Color(*color, int(255 * self.lane_alpha)))

  def _draw_bsm(self, rect, cs):
    t = rl.get_time()
    for i, (spot, blinker) in enumerate(((cs.leftBlindspot, cs.leftBlinker), (cs.rightBlindspot, cs.rightBlinker))):
      target = 0.0
      if spot:
        # 그쪽 깜빡이를 켜면 빠르게 깜빡여 강하게 경고
        target = (0.95 if math.sin(t * 2 * math.pi * 4) > 0 else 0.25) if blinker else 0.6
      self.bsm_alpha[i] = self._ease(self.bsm_alpha[i], target, 0.5)
      if self.bsm_alpha[i] < 0.02:
        continue
      x = rect.x if i == 0 else rect.x + rect.width - BSM_WIDTH
      top = rect.y + rect.height * 0.25
      rl.draw_rectangle_rounded(rl.Rectangle(x, top, BSM_WIDTH, rect.height * 0.75), 0.4, 6,
                                rl.Color(*BSM_COLOR, int(255 * self.bsm_alpha[i])))

  @staticmethod
  def _draw_gap(rect, gap: int):
    w, gapx, base_y = 12, 5, rect.y + rect.height - 14
    x0 = rect.x + 18
    rl.draw_rectangle_rounded(rl.Rectangle(x0 - 8, base_y - 30, 4 * w + 3 * gapx + 16, 38), 0.35, 6, rl.Color(0, 0, 0, 140))
    for i in range(4):
      h = 8 + 5 * i
      a = 230 if i < gap else 60
      rl.draw_rectangle_rounded(rl.Rectangle(x0 + i * (w + gapx), base_y - h, w, h), 0.3, 4, rl.Color(255, 255, 255, a))
