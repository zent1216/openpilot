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
  store.set_settings({"cruise_auto": True, "cruise_style": 1, "curve_slowdown": 2, "nmirror": True})
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
  # 커브가 끝나면 잠시 뒤 '지금 속도+10'까지만 올리고, 차가 빨라지면 따라서 100까지 복귀 (버튼 한꺼번에 안 누름)
  vals = [step(p, clk, cs(70), model(70 * KPH)) for _ in range(40)]
  assert vals[0] < 100 * KPH and vals[-1] == pytest.approx(80 * KPH)
  for v in (80, 90, 100):
    for _ in range(30):
      t = step(p, clk, cs(70, v_kph=v), model(v * KPH))
  assert t == pytest.approx(100 * KPH)


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


def test_navi_limit(planner):
  p, clk = planner
  c = cs(100)
  step(p, clk, c, model(100 * KPH))
  c.junpilotNaviLimit = 80 * KPH
  assert step(p, clk, c, model(100 * KPH)) == pytest.approx(80 * KPH)
  store.set_settings({"navi_margin": 5})
  clk.t += 2
  # 여유를 올리면 올릴 때는 1초 유지 후 반영
  for _ in range(30):
    t = step(p, clk, c, model(100 * KPH))
  assert t == pytest.approx(85 * KPH)
  store.set_settings({"navi_slowdown": False})
  clk.t += 2
  for _ in range(30):
    t = step(p, clk, c, model(100 * KPH))
  assert t == pytest.approx(100 * KPH)


def test_nmirror_fallback(planner, tmp_path, monkeypatch):
  import json
  import time
  from openpilot.junpilot import nmirror
  path = tmp_path / "nm.json"
  monkeypatch.setattr(nmirror, "STATE_PATH", str(path))
  path.write_text(json.dumps({"mono": time.monotonic(), "road_limit": {"cam_limit_speed": 60, "cam_limit_speed_left_dist": 200}}))
  nmirror._cache["t"] = -1e9
  p, clk = planner
  c = cs(100)
  assert step(p, clk, c, model(100 * KPH)) == pytest.approx(60 * KPH)
  assert p.debug["navi_kind"] == 1
  store.set_settings({"nmirror": False})
  clk.t += 2
  nmirror._cache["t"] = -1e9
  for _ in range(30):
    t = step(p, clk, c, model(100 * KPH))
  assert t == pytest.approx(100 * KPH)


def test_steer_tuning_settings(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  assert store.steer_tuning() == (1.0, 0.0)
  store.set_settings({"curve_steer": 92, "steer_timing": 3})
  scale, off = store.steer_tuning()
  assert abs(scale - 0.92) < 1e-9 and off == -0.05
  with pytest.raises(ValueError):
    store.validate_setting("curve_steer", 70)


def lead(d, v_lead_kph, v_ego_kph):
  return NS(present=True, dRel=d, vLead=v_lead_kph * KPH, vRel=(v_lead_kph - v_ego_kph) * KPH)


def test_lead_close_slows_and_releases(planner):
  p, clk = planner
  c = cs(80, v_kph=40)
  c.cruiseState.speed = 80 * KPH
  p.update(cs(80), model(80 * KPH))  # 운전자 설정 80 기억
  # 40km/h에서 앞차 12m(1.08초), 앞차 35km/h로 다가감 → 앞차보다 낮게, 5km/h 단위
  p.lead = lead(12, 35, 40)
  for _ in range(5):
    t = step(p, clk, c, model(40 * KPH))
  assert abs(t * 3.6 - 30) < 0.1  # floor((35-3)/5)*5 = 30
  # 앞차가 조금 빨라져도(36) 바로 올리지 않음 (버튼 덜 누르게)
  p.lead = lead(12.5, 36, 40)
  t = step(p, clk, c, model(40 * KPH))
  assert abs(t * 3.6 - 30) < 0.1
  # 충분히 멀어지면(1.2+0.4초 이상) 풀림: 지금 속도(40)+10까지 먼저
  p.lead = lead(25, 45, 40)
  for _ in range(40):
    t = step(p, clk, c, model(40 * KPH))
  assert abs(t * 3.6 - 50) < 0.1


def test_lead_far_or_not_closing_untouched(planner):
  p, clk = planner
  c = cs(80, v_kph=40)
  p.update(cs(80), model(80 * KPH))
  p.lead = lead(30, 35, 40)  # 2.7초: 멀다
  assert abs(step(p, clk, c, model(40 * KPH)) * 3.6 - 80) < 0.1
  p.lead = lead(12, 41, 40)  # 가깝지만 멀어지는 중
  assert abs(step(p, clk, c, model(40 * KPH)) * 3.6 - 80) < 0.1


def test_cutin_latched(planner):
  p, clk = planner
  c = cs(80, v_kph=60)
  p.update(cs(80), model(80 * KPH))
  c.junpilotCutInSpeed = 50 * KPH
  t = step(p, clk, c, model(60 * KPH))
  assert abs(t * 3.6 - 47) < 0.1  # 끼어드는 차(50)보다 3 낮게
  c.vEgo = 50 * KPH  # 우리가 느려져도 더 내려가지 않음
  assert abs(step(p, clk, c, model(50 * KPH)) * 3.6 - 47) < 0.1
  store.set_settings({"cutin_slowdown": False})
  p.settings_t = -10
  c.junpilotCutInSpeed = 0.0
  for _ in range(40):
    t = step(p, clk, c, model(50 * KPH))
  assert abs(t * 3.6 - 60) < 0.1


def test_driver_raise_pauses_lead_assist(planner):
  p, clk = planner
  c = cs(80, v_kph=40)
  p.update(cs(80), model(80 * KPH))
  p.lead = lead(12, 35, 40)
  assert abs(step(p, clk, c, model(40 * KPH)) * 3.6 - 30) < 0.1
  # 운전자가 RES+로 올림 → 20초 동안 다시 끌어내리지 않음
  c.buttonEvents = [NS(type="accelCruise", pressed=True)]
  step(p, clk, c, model(40 * KPH))
  c.buttonEvents = []
  for _ in range(20):
    t = step(p, clk, c, model(40 * KPH))
  assert t == 0 or t * 3.6 > 35


def test_faster_cutin_ignored(planner):
  p, clk = planner
  c = cs(80, v_kph=70)
  p.update(cs(80), model(80 * KPH))
  c.junpilotCutInSpeed, c.junpilotCutInDist = 90 * KPH, 30.0
  assert abs(step(p, clk, c, model(70 * KPH)) * 3.6 - 80) < 0.1


def test_similar_speed_cutin_ignored(planner):
  p, clk = planner
  c = cs(80, v_kph=70)
  p.update(cs(80), model(80 * KPH))
  c.junpilotCutInSpeed, c.junpilotCutInDist = 67 * KPH, 25.0  # 비슷한 속도로 멀찍이
  assert abs(step(p, clk, c, model(70 * KPH)) * 3.6 - 80) < 0.1
  c.junpilotCutInDist = 8.0  # 바짝 들어오면 감속
  assert step(p, clk, c, model(70 * KPH)) * 3.6 < 70


def test_driver_raise_during_camera_kept(planner):
  p, clk = planner
  c = cs(80, v_kph=75)
  p.update(cs(80), model(80 * KPH))
  c.junpilotNaviLimit, c.junpilotNaviKind = 80 * KPH, 2
  store.set_settings({"navi_margin": -5})
  p.settings_t = -10
  assert abs(step(p, clk, c, model(75 * KPH)) * 3.6 - 75) < 0.1
  # 운전자가 80으로 올림 → 이번 구간단속 동안은 80 유지
  c.buttonEvents = [NS(type="accelCruise", pressed=True)]
  step(p, clk, c, model(75 * KPH))
  c.buttonEvents = []
  c.cruiseState.speed = 80 * KPH
  for _ in range(20):
    t = step(p, clk, c, model(78 * KPH))
  assert abs(t * 3.6 - 80) < 0.1
