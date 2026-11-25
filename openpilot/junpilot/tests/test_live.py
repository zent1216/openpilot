import struct

import numpy as np

from openpilot.cereal import log
from openpilot.junpilot import live, traffic


class SM(dict):
  def __init__(self, msgs):
    super().__init__(msgs)
    self.seen = dict.fromkeys(msgs, True)


def _sm(lead_d=None, stop_at=None):
  msgs = {}
  for w in ('modelV2', 'carState', 'selfdriveState', 'radarState', 'extrinsicsCalibration', 'deviceState', 'narrowRoadCameraState'):
    ev = log.Event.new_message()
    ev.init(w)
    msgs[w] = getattr(ev, w)
  # 직진 도로: 경로와 차선
  xs = np.linspace(0, 100, 33).tolist()
  md = log.Event.new_message().init('modelV2')
  md.position.x, md.position.y, md.position.z = xs, [0.0] * 33, [0.0] * 33
  v = [10.0] * 33 if stop_at is None else [max(0.0, 10.0 * (1 - x / stop_at)) for x in xs]
  md.velocity.x = v
  lls = md.init('laneLines', 4)
  for i, y in enumerate((-5.4, -1.8, 1.8, 5.4)):
    lls[i].x, lls[i].y, lls[i].z = xs, [y] * 33, [0.0] * 33
  md.laneLineProbs = [0.9, 0.9, 0.9, 0.9]
  msgs['modelV2'] = md
  cal = log.Event.new_message().init('extrinsicsCalibration')
  cal.rpyCalib = [0.0, 0.0, 0.0]
  cal.height = [1.22]
  msgs['extrinsicsCalibration'] = cal
  cs = log.Event.new_message().init('carState')
  cs.vEgo = 10.0
  msgs['carState'] = cs
  if lead_d is not None:
    rs = log.Event.new_message().init('radarState')
    rs.leadOne.present = True
    rs.leadOne.dRel = lead_d
    msgs['radarState'] = rs
  return SM(msgs)


def test_overlay_projects_path_and_lanes_on_screen():
  ob = live.OverlayBuilder()
  out = ob.build(_sm(lead_d=30.0))
  assert len(out["lanes"]) == 4 and out["path"] and out["lead"]["d"] == 30.0
  pts = np.array(out["path"])
  assert np.all((pts[:, 0] > 0) & (pts[:, 0] < 1))
  assert np.median(pts[:, 1]) < 1.0 and pts[:, 1].min() > 0.3  # 길은 화면 아래쪽 (가까운 끝은 화면 밖)
  left, right = np.array(out["lanes"][1]["poly"]), np.array(out["lanes"][2]["poly"])
  assert left[:, 0].mean() < 0.5 < right[:, 0].mean()  # 왼쪽 차선은 왼쪽에
  assert out["hud"]["kph"] == 36


def test_pack_frame():
  b = live.pack_frame(b"\x00\x00\x00\x01\x67abc", True, 123)
  n, key, ts = struct.unpack(">IBQ", b[:13])
  assert (n, key, ts) == (8, 1, 123) and b[13:] == b"\x00\x00\x00\x01\x67abc"


def test_flag(tmp_path):
  f = str(tmp_path / "live")
  assert not live.flag_active(f)
  live.touch_flag(f)
  assert live.flag_active(f)


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
