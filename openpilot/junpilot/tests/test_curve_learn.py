from openpilot.junpilot import curve_learn as cl


def _drive(lr, t, secs, v, model, actual, pressed, blinker=False):
  out = None
  for _ in range(int(secs / 0.01)):
    k = lr.update(t, v, model, actual, True, pressed, blinker)
    out = out or k
    t += 0.01
  return t, out


def test_learns_less_steer_after_corrections(tmp_path):
  lr = cl.CurveLearner(str(tmp_path / "l.json"))
  t = 0.0
  assert lr.scale(0.01, 10) == 1.0
  for _ in range(cl.FULL_COUNT * 3):  # 왼쪽 급한 커브에서 매번 10% 덜 꺾도록 고쳐 줌
    t, key = _drive(lr, t, 1.0, 10, 0.01, 0.009, True)
    t, _ = _drive(lr, t, 0.5, 10, 0.01, 0.01, False)
  s = lr.scale(0.01, 10)
  assert 0.88 < s < 0.95
  assert lr.scale(-0.01, 10) == 1.0          # 반대 방향 커브는 따로
  assert lr.scale(0.01, 20) == 1.0           # 다른 속도대(50km/h 이상)도 따로
  lr.save()
  assert abs(cl.CurveLearner(lr.path).scale(0.01, 10) - s) < 1e-9  # 저장됨


def test_ignores_short_taps_lane_changes_and_straights(tmp_path):
  lr = cl.CurveLearner(str(tmp_path / "l.json"))
  t, _ = _drive(lr, 0.0, 0.2, 15, 0.01, 0.005, True)       # 잠깐 툭
  t, _ = _drive(lr, t, 0.5, 15, 0.01, 0.01, False)
  t, _ = _drive(lr, t, 1.0, 15, 0.01, 0.005, True, True)   # 깜빡이 (차선 변경)
  t, _ = _drive(lr, t, 0.5, 15, 0.01, 0.01, False)
  t, _ = _drive(lr, t, 1.0, 15, 0.0005, 0.0002, True)      # 직선
  t, _ = _drive(lr, t, 0.5, 15, 0.01, 0.01, False)
  assert lr.bins == {}


def test_scale_is_bounded(tmp_path):
  lr = cl.CurveLearner(str(tmp_path / "l.json"))
  t = 0.0
  for _ in range(30):
    t, _ = _drive(lr, t, 1.0, 15, 0.01, 0.001, True)   # 말도 안 되게 덜 꺾음
    t, _ = _drive(lr, t, 0.5, 15, 0.01, 0.01, False)
  assert lr.scale(0.01, 15) == cl.SCALE_CLIP[0]
  assert cl.describe(lr.bins)[0]["percent"] == 85
