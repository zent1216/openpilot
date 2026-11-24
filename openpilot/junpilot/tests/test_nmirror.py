import json
import socket
import threading
import time

from openpilot.junpilot import nmirror
from openpilot.junpilot.nmirror import KPH, NMirrorServer, limit_from, parse, read_road_limit


def pkt(**rl):
  return json.dumps({"active": 1, "road_limit": rl}).encode()


def test_parse_keeps_only_numbers_and_drops_cmd():
  m = parse(json.dumps({"cmd": "rm -rf /", "road_limit": {"cam_limit_speed": 60, "cam_type": "x", "section_left_dist": float("nan")},
                        "active": 1}).encode())
  assert "cmd" not in m
  assert m["road_limit"] == {"cam_limit_speed": 60.0}
  assert parse(b"not json") is None
  assert parse(b"[1,2]") is None
  assert parse(b"{" + b" " * 20000 + b"}") is None


def test_limit_camera_distance_and_section():
  v = 100 * KPH
  assert limit_from({"cam_limit_speed": 60, "cam_limit_speed_left_dist": 2000}, v) == (0.0, 0)  # 아직 멂
  lim, kind = limit_from({"cam_limit_speed": 60, "cam_limit_speed_left_dist": 300}, v)
  assert kind == 1 and abs(lim - 60 * KPH) < 1e-6
  lim, kind = limit_from({"section_limit_speed": 80, "section_left_dist": 5000}, v)
  assert kind == 2 and abs(lim - 80 * KPH) < 1e-6
  assert limit_from({}, v) == (0.0, 0)


def test_server_accepts_private_only_and_goes_stale():
  t = [100.0]
  srv = NMirrorServer(clock=lambda: t[0])
  assert not srv.handle(pkt(cam_limit_speed=50), "8.8.8.8")
  assert not srv.handle(pkt(cam_limit_speed=50), "100.64.1.2")
  replies = []
  assert srv.handle(json.dumps({"echo": {"a": 1}}).encode(), "192.168.43.20", reply=replies.append)
  assert replies == [b'{"a": 1}']
  assert srv.handle(pkt(cam_limit_speed=50, road_limit_speed=60), "192.168.43.20")
  st = srv.status()
  assert st["connected"] and st["peer"] == "192.168.43.20" and st["road_limit"]["cam_limit_speed"] == 50
  t[0] += 10
  st = srv.status()
  assert not st["connected"] and st["road_limit"] == {}


def test_targets_include_subnet_broadcast_and_peer():
  srv = NMirrorServer(ip_addresses=lambda: ["192.168.43.1"])
  srv.handle(pkt(), "192.168.43.77")
  assert set(srv.targets()) == {"255.255.255.255", "192.168.43.255", "192.168.43.77"}


def test_state_file_roundtrip(tmp_path, monkeypatch):
  path = str(tmp_path / "nm.json")
  monkeypatch.setattr(nmirror, "STATE_PATH", path)
  srv = NMirrorServer()
  srv.handle(pkt(section_limit_speed=80, section_left_dist=1000), "10.0.0.5")
  nmirror._cache["t"] = -1e9
  assert read_road_limit(path)["section_limit_speed"] == 80


def test_udp_end_to_end(monkeypatch):
  monkeypatch.setattr(nmirror, "RECEIVE_PORT", 28431)
  monkeypatch.setattr(nmirror, "BROADCAST_PORT", 28991)
  listen = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  listen.bind(("127.0.0.1", 28991))
  listen.settimeout(3)
  srv = NMirrorServer(ip_addresses=list)
  srv.targets = lambda: ["127.0.0.1"]
  threading.Thread(target=srv.run, daemon=True).start()
  data, _ = listen.recvfrom(100)
  assert data == nmirror.HELLO
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.sendto(pkt(cam_limit_speed=70, cam_limit_speed_left_dist=200), ("127.0.0.1", 28431))
  for _ in range(30):
    if srv.status()["connected"]:
      break
    time.sleep(0.1)
  assert srv.status()["road_limit"]["cam_limit_speed"] == 70
