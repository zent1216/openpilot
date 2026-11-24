import json
import threading
import time
from dataclasses import replace

import pytest
import requests

from openpilot.junpilot import store, tracker as tr
from openpilot.junpilot.tracker import DriveTracker, Snapshot

K = 1 / 3.6


def drive(tk, snaps):
  evs = []
  for s in snaps:
    evs += tk.update(s)
  return evs


def base(t, **kw):
  args = {"t": t, "onroad": True, "v": 25.0, "engaged": True, "cruise_on": True, "set_speed": 100 * K, "driver_set": 100 * K}
  args.update(kw)
  return Snapshot(**args)


def test_events_and_saved_summary(tmp_path):
  tk = DriveTracker(save_dir=str(tmp_path), wall_clock=lambda: 1_700_000_000)
  snaps = [base(i * 0.1, engaged=False) for i in range(5)]
  snaps += [base(0.5 + i * 0.1) for i in range(100)]                                   # 켜짐
  snaps += [base(10.5 + i * 0.1, navi_kind=2, navi_limit=80 * K) for i in range(50)]   # 구간단속
  snaps += [base(15.5 + i * 0.1) for i in range(10)]                                    # 구간 끝
  snaps += [base(16.5 + i * 0.1, curve_limit=70 * K, brake=(i == 3)) for i in range(30)]  # 커브 감속 중 브레이크
  snaps += [base(19.5, lead=True, lead_d=30, lead_a=-4.5)]                              # 앞차 급감속
  snaps += [base(19.6, bsm_r=True, blinker_r=True)]                                     # 측후방
  snaps += [base(19.7 + i * 0.1, target=80 * K) for i in range(100)]                    # 버튼 반영 안 됨
  snaps += [base(29.7, engaged=False), Snapshot(t=29.8, onroad=False)]
  evs = drive(tk, snaps)
  types = [e["type"] for e in evs]
  for t in ("engage", "navi_enter", "navi_exit", "curve_slow", "lead_brake", "bsm_warn", "button_stuck", "disengage"):
    assert t in types, t
  assert next(e for e in evs if e["type"] == "navi_enter")["limit"] == 80
  files = list(tmp_path.glob("*.json"))
  assert len(files) == 1
  d = json.loads(files[0].read_text())
  assert d["intervention"]["curve_brake"] == 1 and d["distance_km"] > 0.5 and d["counts"]["lead_brake"] == 1


def test_short_drive_not_saved(tmp_path):
  tk = DriveTracker(save_dir=str(tmp_path))
  drive(tk, [base(0), base(1), Snapshot(t=2, onroad=False)])
  assert not list(tmp_path.glob("*.json"))


def test_lead_brake_cooldown():
  tk = DriveTracker()
  evs = drive(tk, [base(i * 0.1, lead=True, lead_d=30, lead_a=-4) for i in range(50)])
  assert sum(e["type"] == "lead_brake" for e in evs) == 1


def d(**iv):
  return {"intervention": {"curve_brake": 0, "curve_gas": 0, "navi_brake": 0, "navi_gas": 0, **iv}, "curve_slow_sec": 60}


def test_tuning_suggestions():
  s = {"curve_slowdown": 2, "cruise_style": 1, "navi_margin": 0}
  assert tr.tuning_suggestions([d()], s)[0]["key"] is None  # 기록 부족
  out = tr.tuning_suggestions([d(curve_brake=2), d(curve_brake=2)], s)
  assert {"key": "curve_slowdown", "value": 3}.items() <= out[0].items()
  out = tr.tuning_suggestions([d(curve_gas=2), d(curve_gas=2)], s)
  assert out[0]["key"] == "curve_slowdown" and out[0]["value"] == 1
  out = tr.tuning_suggestions([d(navi_brake=2), d(navi_brake=2)], s)
  assert any(x["key"] == "navi_margin" and x["value"] == -5 for x in out)
  # 단속 구간 가속이 많아도 여유(과속)를 올리라고 추천하지 않음
  out = tr.tuning_suggestions([d(navi_gas=5), d(navi_gas=5)], s)
  assert not any(x["key"] == "navi_margin" for x in out)


# ---- 서버 API ----
@pytest.fixture
def srv(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path / "jp"))
  from http.server import ThreadingHTTPServer
  from openpilot.junpilot.tests.test_server import FakeDevice
  from openpilot.junpilot.web import server
  app = server.App(FakeDevice(str(tmp_path / "logs")))
  ThreadingHTTPServer.daemon_threads = True
  httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
  threading.Thread(target=httpd.serve_forever, daemon=True).start()
  base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
  token = requests.post(base_url + "/api/pair", json={"code": app.code, "client": "app"}).json()["token"]
  yield app, base_url, {"Authorization": f"Bearer {token}"}
  httpd.shutdown()


def test_bearer_auth_and_drives(srv, tmp_path):
  app, url, h = srv
  assert requests.get(url + "/api/drives").status_code == 401
  ddir = tmp_path / "jp" / "drives"
  ddir.mkdir(parents=True)
  for name in ("20261124-080000", "20261124-180000"):
    (ddir / f"{name}.json").write_text(json.dumps({**d(curve_brake=2), "distance_km": 12.3, "events": [{"type": "engage"}]}))
  lst = requests.get(url + "/api/drives", headers=h).json()["drives"]
  assert [x["id"] for x in lst] == ["20261124-180000", "20261124-080000"] and "events" not in lst[0]
  one = requests.get(url + "/api/drives/20261124-080000", headers=h).json()
  assert one["events"][0]["type"] == "engage"
  assert requests.get(url + "/api/drives/..%2fx", headers=h).status_code in (400, 404)
  sug = requests.get(url + "/api/tuning", headers=h).json()["suggestions"]
  assert sug[0]["key"] == "curve_slowdown"
  # 추천과 다른 값은 거부, 추천값은 적용
  assert requests.post(url + "/api/tuning/apply", headers=h, json={"key": "curve_slowdown", "value": 1}).status_code == 400
  assert requests.post(url + "/api/tuning/apply", headers=h, json={"key": "curve_slowdown", "value": 3}).status_code == 200
  assert store.get_settings()["curve_slowdown"] == 3


def test_event_stream(srv):
  app, url, h = srv
  got = []

  def listen():
    with requests.get(url + "/api/events", headers=h, stream=True, timeout=5) as r:
      for line in r.iter_lines(chunk_size=1, decode_unicode=True):
        if line.startswith("data:"):
          got.append(json.loads(line[5:]))
          return
  th = threading.Thread(target=listen, daemon=True)
  th.start()
  for _ in range(50):
    if app.broadcaster.clients:
      break
    time.sleep(0.05)
  app.broadcaster.publish("event", {"type": "lead_brake", "dist": 30})
  th.join(3)
  assert got == [{"type": "lead_brake", "dist": 30}]


def test_snapshot_replace_unused():
  assert replace(base(0), v=1.0).v == 1.0
