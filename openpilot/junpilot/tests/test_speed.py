import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from openpilot.junpilot import speed, store

KPH = 1 / 3.6
T = np.linspace(0, 10, 33)


class Clock:
  def __init__(self): self.t = 0.0
  def __call__(self): return self.t


def model(v, radius=None, start_m=0.0):
  """일정 속도 v로 달리는 예측 경로. start_m 이후 반지름 radius 커브."""
  vel = [v] * len(T)
  pos = list(v * T)
  yaw = [(v / radius if radius and p >= start_m else 0.0) for p in pos]
  return NS(velocity=NS(x=vel), orientationRate=NS(z=yaw), position=NS(x=pos))


def cs(set_kph, enabled=True, v_kph=None, buttons=()):
  return NS(cruiseState=NS(enabled=enabled, speed=set_kph * KPH), vEgo=(v_kph or set_kph) * KPH,
            buttonEvents=[NS(type=b) for b in buttons])


@pytest.fixture
def planner(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  store.set_settings({"cruise_auto": True, "cruise_style": 1, "curve_slowdown": 2})
  clk = Clock()
  return speed.SpeedPlanner(clock=clk), clk


def step(p, clk, c, m, secs=0.05):
  clk.t += secs
  return p.update(c, m)


def test_off_when_disabled(planner, tmp_path):
  p, clk = planner
  store.set_settings({"cruise_auto": False})
  clk.t += 2
  assert step(p, clk, cs(100), model(100 * KPH)) == 0.0
  assert step(p, clk, cs(100, enabled=False), model(100 * KPH)) == 0.0


def test_straight_road_keeps_driver_speed(planner):
  p, clk = planner
  assert step(p, clk, cs(100), model(100 * KPH)) == pytest.approx(100 * KPH)


def test_curve_slows_then_restores_driver_speed(planner):
  p, clk = planner
  step(p, clk, cs(100), model(100 * KPH))
  # 반지름 150m 커브: 허용 2.2m/s^2 -> 약 18m/s(65km/h)
  t = step(p, clk, cs(100), model(100 * KPH, radius=150))
  assert 55 * KPH < t < 80 * KPH
  # 시스템이 설정속도를 내린 상태(70)에서도 운전자 속도 100은 기억
  for _ in range(10):
    step(p, clk, cs(70), model(70 * KPH, radius=150))
  # 커브가 끝나면 잠시 뒤 100으로 복귀
  vals = [step(p, clk, cs(70), model(70 * KPH)) for _ in range(40)]
  assert vals[0] < 100 * KPH and vals[-1] == pytest.approx(100 * KPH)


def test_far_curve_allows_more_speed_than_near_curve(planner):
  a = speed.curve_limit(25, *[list(x) for x in (model(25, 150, 150).velocity.x, model(25, 150, 150).orientationRate.z,
                                               model(25, 150, 150).position.x)], 2.2, 1.1)
  b = speed.curve_limit(25, *[list(x) for x in (model(25, 150, 0).velocity.x, model(25, 150, 0).orientationRate.z,
                                               model(25, 150, 0).position.x)], 2.2, 1.1)
  assert a > b and b == pytest.approx(math.sqrt(2.2 * 150), rel=0.01)


def test_driver_button_updates_memory(planner):
  p, clk = planner
  step(p, clk, cs(100), model(100 * KPH))
  assert step(p, clk, cs(100, buttons=["decelCruise"]), model(100 * KPH)) == 0.0  # 운전자 조작 중엔 손 뗌
  for _ in range(20):
    step(p, clk, cs(90), model(90 * KPH))
  assert p.driver_set == pytest.approx(90 * KPH)
  assert step(p, clk, cs(90), model(90 * KPH)) == pytest.approx(90 * KPH)


def test_minimum_target(planner):
  p, clk = planner
  step(p, clk, cs(60), model(60 * KPH))
  t = step(p, clk, cs(60), model(60 * KPH, radius=10))
  assert t == pytest.approx(speed.MIN_TARGET)


def test_curve_slowdown_off(planner):
  p, clk = planner
  store.set_settings({"curve_slowdown": 0})
  clk.t += 2
  step(p, clk, cs(100), model(100 * KPH))
  assert step(p, clk, cs(100), model(100 * KPH, radius=150)) == pytest.approx(100 * KPH)


def test_style_changes_curve_speed():
  m = model(25, 150, 0)
  args = (list(m.velocity.x), list(m.orientationRate.z), list(m.position.x))
  soft = speed.curve_limit(25, *args, 2.2 + speed.STYLE[0]["lat_bias"], speed.STYLE[0]["decel"])
  fast = speed.curve_limit(25, *args, 2.2 + speed.STYLE[2]["lat_bias"], speed.STYLE[2]["decel"])
  assert soft < fast
