from openpilot.junpilot.gap import AutoGap, HOLD_TIME


def run(g, t0, secs, kph, lead, base=3):
  t, out = t0, 0
  while t < t0 + secs:
    out = g.update(t, kph / 3.6, lead, base, True)
    t += 0.05
  return t, out


def test_slow_traffic_shortens_gap_after_hold():
  g = AutoGap()
  t, gap = run(g, 0, 2, 100, True)
  assert gap == 3
  t, gap = run(g, t, HOLD_TIME - 0.5, 20, True)
  assert gap == 3  # 아직 유지 시간 전
  t, gap = run(g, t, 1.0, 20, True)
  assert gap == 1
  t, gap = run(g, t, HOLD_TIME + 0.5, 20, False)
  assert gap == 3  # 앞차가 없으면 기본 단계


def test_disabled_returns_base():
  assert AutoGap().update(0, 5, True, 4, False) == 4
  assert AutoGap().update(0, 5, True, 0, False) == 3
