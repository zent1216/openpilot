from openpilot.junpilot import cruise_learn as cl
from openpilot.junpilot.gap import AutoGap


def _u(lr, t, **kw):
  base = {"cruise": True, "v_ego": 15.0, "k_max": 0.0, "curve_limited": False, "camera_active": False, "accel_pressed": False,
          "decel_pressed": False, "gas_pressed": False, "gap_pressed": False, "cur_gap": 3, "has_lead": True}
  base.update(kw)
  return lr.update(t, **base)


def test_curve_learning_from_buttons_and_gas(tmp_path):
  lr = cl.CruiseLearner(str(tmp_path / "c.json"))
  assert _u(lr, 0.0, k_max=0.01, curve_limited=True, accel_pressed=True) == "curve1"
  assert lr.curve_lat_adj(0.01) == cl.CURVE_STEP
  assert _u(lr, 1.0, k_max=0.01, curve_limited=True, accel_pressed=True) is None  # 연달아 배우지 않음
  t = 10.0
  for _ in range(150):  # 커브 감속 중 가속 페달 1.5초
    _u(lr, t, k_max=0.01, curve_limited=True, gas_pressed=True)
    t += 0.01
  assert abs(lr.curve_lat_adj(0.01) - 2 * cl.CURVE_STEP) < 1e-9
  assert _u(lr, 20.0, k_max=0.004, decel_pressed=True) == "curve0"
  assert lr.curve_lat_adj(0.004) == -cl.CURVE_STEP
  assert lr.curve_lat_adj(0.001) == 0.0  # 직선은 상관없음


def test_margin_and_gap(tmp_path):
  lr = cl.CruiseLearner(str(tmp_path / "c.json"))
  for i in range(8):
    _u(lr, i * 4.0, camera_active=True, accel_pressed=True)
  assert lr.margin_adj() == cl.MARGIN_CLIP[1]
  assert lr.gap_for(10, True) is None
  _u(lr, 100.0, v_ego=10, gap_pressed=True, cur_gap=4)
  _u(lr, 101.0, v_ego=10, cur_gap=1)
  _u(lr, 101.6, v_ego=10, cur_gap=1)  # 1.5초 뒤 계기판 단계를 배움
  assert lr.gap_for(10, True) == 1 and lr.gap_for(10, False) is None
  lr.save()
  lr2 = cl.CruiseLearner(lr.path)
  assert lr2.gap_for(10, True) == 1 and lr2.margin_adj() == cl.MARGIN_CLIP[1]
  d = cl.describe(lr.path)
  assert not d["empty"] and d["gap"][0]["gap"] == 1
  lr2.reset()
  assert cl.describe(lr.path)["empty"]


def test_autogap_uses_learned_gap():
  g = AutoGap()
  t = 0.0
  for _ in range(100):
    out = g.update(t, 25.0, True, 3, True, learned=1)
    t += 0.05
  assert out == 1
