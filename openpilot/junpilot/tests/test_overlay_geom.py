import os

import numpy as np

os.environ.setdefault("RAYLIB_BACKEND", "headless")
from openpilot.junpilot.ui.mici_overlay import target_lane_corners, project

XS = np.linspace(0, 100, 33)


def line(y):
  return np.column_stack((XS, np.full_like(XS, y), np.zeros_like(XS))).astype(np.float32)


LINES = [line(-5.4), line(-1.8), line(1.8), line(5.4)]
PATH = line(0.0)


def test_left_and_right_lane_sides():
  probs = np.array([0.9, 0.9, 0.9, 0.9])
  left = target_lane_corners(LINES, probs, PATH, True, 1.2)
  right = target_lane_corners(LINES, probs, PATH, False, 1.2)
  assert left[:, 1].max() <= -1.8 + 1e-6 and left[:, 1].min() >= -5.4 - 1e-6  # 모델 좌표 y: 왼쪽이 음수
  assert right[:, 1].min() >= 1.8 - 1e-6 and right[:, 1].max() <= 5.4 + 1e-6
  assert left[:, 0].min() >= 4.0 and left[:, 0].max() <= 60.0


def test_missing_outer_line_uses_default_width():
  probs = np.array([0.0, 0.9, 0.9, 0.0])
  left = target_lane_corners(LINES, probs, PATH, True, 1.2)
  assert np.isclose(left[:, 1].min(), -1.8 - 3.6)


def test_no_lane_when_inner_line_unknown():
  probs = np.array([0.9, 0.1, 0.9, 0.9])
  assert target_lane_corners(LINES, probs, PATH, True, 1.2) is None


def test_project_rejects_points_behind_camera():
  T = np.array([[268, 300, 0], [105, 0, 300], [1, 0, 0]], dtype=np.float32)
  assert project(T, np.array([[-1.0, 0.0, 1.0]], dtype=np.float32)) is None
  p = project(T, np.array([[10.0, 0.0, 1.2]], dtype=np.float32))
  assert np.allclose(p[0], [268, 105 + 300 * 1.2 / 10])
