import numpy as np

from openpilot.junpilot import traffic


def test_traffic_red_then_green():
  tl = traffic.TrafficLight()
  xs = np.linspace(0, 100, 33)
  stop_v = np.maximum(0, 10 * (1 - xs / 40))
  t = 0.0
  for _ in range(20):  # 앞차 없이 40m 앞 정지 계획
    st = tl.update(t, 8.0, stop_v, xs, False, 0.0)
    t += 0.1
  assert st == traffic.RED
  for _ in range(10):  # 정지
    tl.update(t, 0.0, np.zeros(33), xs, False, 0.0)
    t += 0.1
  go = np.full(33, 5.0)
  for _ in range(10):  # 출발 계획
    st = tl.update(t, 0.0, go, xs, False, 0.0)
    t += 0.1
  assert st == traffic.GREEN


def test_traffic_ignores_stop_behind_lead():
  tl = traffic.TrafficLight()
  xs = np.linspace(0, 100, 33)
  stop_v = np.maximum(0, 10 * (1 - xs / 40))
  st = traffic.NONE
  for i in range(20):
    st = tl.update(i * 0.1, 8.0, stop_v, xs, True, 42.0)
  assert st == traffic.NONE
