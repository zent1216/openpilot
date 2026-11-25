import base64
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer

import pytest
import requests

from openpilot.junpilot import drive, store
from openpilot.junpilot.web import server


class FakeDevice:
  def __init__(self, log_root):
    self.params = {"IsLdwEnabled": False, "IsMetric": True, "LanguageSetting": "en", "OpenpilotEnabledToggle": True,
                   "DisengageOnAccelerator": False, "AlwaysOnDM": False, "RecordFront": False, "RecordAudio": False}
    self.onroad = False
    self.root = log_root
    self.alert = None
    self.rebooted = False

  def get_param(self, k): return self.params.get(k)
  def put_param(self, k, v): self.params[k] = v
  def is_onroad(self): return self.onroad
  def info(self): return {"Version": "0.11", "GitBranch": "junpilot", "GitCommit": "abc", "car": None}
  def log_root(self): return self.root
  def ip_addresses(self): return ["192.168.43.1"]
  def set_pairing_alert(self, show, text=""): self.alert = text if show else None
  def check_update(self): return True
  def reboot(self): self.rebooted = True


@pytest.fixture
def env(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path / "jp"))
  logs = tmp_path / "realdata"
  for seg in range(2):
    d = logs / f"0000001c--4e7a1b2c3d--{seg}"
    d.mkdir(parents=True)
    (d / "qlog.zst").write_bytes(os.urandom(1000 + seg))
    (d / "rlog.zst").write_bytes(os.urandom(20_000))
  dev = FakeDevice(str(logs))
  app = server.App(dev)
  httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
  threading.Thread(target=httpd.serve_forever, daemon=True).start()
  base = f"http://127.0.0.1:{httpd.server_address[1]}"
  yield app, dev, base
  httpd.shutdown()


def paired(app, base):
  s = requests.Session()
  r = s.post(base + "/api/pair", json={"code": app.code, "name": "폰"})
  assert r.status_code == 200, r.text
  return s


def test_index_and_ping(env):
  app, dev, base = env
  assert "준파일럿" in requests.get(base + "/").text
  assert requests.get(base + "/api/ping").json() == {"paired": False, "pairing": True}


def test_requires_pairing(env):
  app, dev, base = env
  assert requests.get(base + "/api/status").status_code == 401
  assert requests.post(base + "/api/settings", json={}).status_code == 401


def test_pairing_flow_and_lockout(env):
  app, dev, base = env
  app.update_alert()
  assert app.code in dev.alert and dev.alert.isascii()
  wrong = "000000" if app.code != "000000" else "111111"
  for _ in range(server.MAX_FAILS):
    assert requests.post(base + "/api/pair", json={"code": wrong}).status_code == 403
  # 잠금 중에는 맞는 코드도 거부
  assert requests.post(base + "/api/pair", json={"code": app.code}).status_code == 403
  app.locked_until = 0
  s = paired(app, base)
  assert s.get(base + "/api/ping").json()["paired"] is True
  assert s.get(base + "/api/status").status_code == 200
  # 코드는 한 번 쓰면 닫힘
  assert requests.post(base + "/api/pair", json={"code": app.code}).status_code == 403
  app.update_alert()
  assert dev.alert is None


def test_no_pairing_while_onroad(env):
  app, dev, base = env
  dev.onroad = True
  assert requests.post(base + "/api/pair", json={"code": app.code}).status_code == 403


def test_settings(env):
  app, dev, base = env
  s = paired(app, base)
  st = s.get(base + "/api/settings").json()
  assert "IsLdwEnabled" in st["official"] and "cruise_style" in st["junpilot"]
  r = s.post(base + "/api/settings", json={"official": {"IsLdwEnabled": True, "LanguageSetting": "ko"}, "junpilot": {"follow_gap": 2}})
  assert r.status_code == 200, r.text
  assert dev.params["IsLdwEnabled"] is True and dev.params["LanguageSetting"] == "ko"
  assert store.get_settings()["follow_gap"] == 2
  # 잘못된 값, 목록 밖 항목은 거부하고 아무것도 바꾸지 않음
  assert s.post(base + "/api/settings", json={"official": {"IsMetric": False}, "junpilot": {"follow_gap": 9}}).status_code == 400
  assert dev.params["IsMetric"] is True
  assert s.post(base + "/api/settings", json={"official": {"DongleId": "x"}}).status_code == 400
  # 주행 중 변경 금지
  dev.onroad = True
  assert s.post(base + "/api/settings", json={"official": {"IsLdwEnabled": False}}).status_code == 403
  assert dev.params["IsLdwEnabled"] is True
  assert s.get(base + "/api/settings").json()["onroad"] is True
  # 시동은 켜져 있어도 P·N단에 멈춰 있으면 변경 가능

  class Parked:
    def is_parked(self):
      return True
  app.collector = Parked()
  assert s.get(base + "/api/settings").json()["onroad"] is False
  assert s.post(base + "/api/settings", json={"official": {"IsLdwEnabled": False}}).status_code == 200
  assert dev.params["IsLdwEnabled"] is False
  app.collector = None


def test_routes_and_download(env):
  app, dev, base = env
  s = paired(app, base)
  routes = s.get(base + "/api/routes").json()["routes"]
  assert len(routes) == 1 and routes[0]["segments"] == [0, 1] and routes[0]["kinds"] == ["qlog", "rlog"]
  r = s.get(base + "/api/download/0000001c--4e7a1b2c3d/1/qlog")
  assert r.status_code == 200 and len(r.content) == 1001
  r = s.get(base + "/api/download/0000001c--4e7a1b2c3d/0/rlog")
  assert r.status_code == 200 and r.headers["Content-Disposition"].startswith("attachment")
  assert s.get(base + "/api/download/..%2f..%2fetc/0/qlog").status_code in (400, 404)
  # 한 주행 전체를 zip 하나로
  import io
  import zipfile
  r = s.get(base + "/api/download_all/0000001c--4e7a1b2c3d/qlog")
  assert r.status_code == 200 and r.headers["Content-Type"] == "application/zip"
  z = zipfile.ZipFile(io.BytesIO(r.content))
  assert sorted(z.namelist()) == ["000_qlog.zst", "001_qlog.zst"] and len(z.read("001_qlog.zst")) == 1001


def test_send_to_drive(env, monkeypatch):
  app, dev, base = env
  s = paired(app, base)
  received = {}

  def fake_post(url, payload, timeout=120):
    assert payload["secret"] == "s3cret"
    received.setdefault(payload["name"], {})[payload["part"]] = base64.b64decode(payload["data"])

  monkeypatch.setattr(drive, "CHUNK", 7000)
  orig = drive.UploadJob.__init__
  monkeypatch.setattr(drive.UploadJob, "__init__", lambda self, *a, **k: orig(self, *a, post=fake_post))
  # 설정 전에는 실패
  assert s.post(base + "/api/drive", json={"url": "http://evil.com", "secret": "x"}).status_code == 400
  assert s.post(base + "/api/drive", json={"url": "https://script.google.com/macros/s/x/exec", "secret": "s3cret"}).status_code == 200
  r = s.post(base + "/api/send", json={"route": "0000001c--4e7a1b2c3d", "kinds": ["qlog", "rlog"], "note": "커브 흔들림"})
  assert r.status_code == 200, r.text
  for _ in range(50):
    job = s.get(base + "/api/job").json()["job"]
    if job["state"] in ("완료", "실패"):
      break
    time.sleep(0.05)
  assert job["state"] == "완료", job
  assert set(received) == {"meta.json", "000_qlog.zst", "000_rlog.zst", "001_qlog.zst", "001_rlog.zst"}
  rlog = b"".join(received["000_rlog.zst"][i] for i in sorted(received["000_rlog.zst"]))
  assert rlog == open(os.path.join(dev.root, "0000001c--4e7a1b2c3d--0", "rlog.zst"), "rb").read()
  assert len(received["000_rlog.zst"]) == 3  # 20000바이트 / 7000 = 3조각
  meta = json.loads(received["meta.json"][0])
  assert meta["note"] == "커브 흔들림" and meta["device"]["GitBranch"] == "junpilot"


def test_rejects_non_lan_clients():
  assert server._private("192.168.43.20") and server._private("10.0.0.3") and server._private("127.0.0.1")
  assert not server._private("8.8.8.8")
  assert not server._private("100.64.1.1")  # 통신사(LTE) 공유 주소 차단
  assert not server._private("211.234.10.5")


def test_app_download(env, tmp_path, monkeypatch):
  app, dev, base = env
  appdir = tmp_path / "appdir"
  appdir.mkdir()
  monkeypatch.setattr(server, "APP_DIR", str(appdir))
  assert requests.get(base + "/api/app/version").json()["versionCode"] == 0
  assert requests.get(base + "/app/junpilot.apk").status_code == 404
  (appdir / "junpilot.apk").write_bytes(b"PK-apk")
  (appdir / "version.json").write_text('{"versionCode": 3, "versionName": "1.0.3"}')
  assert requests.get(base + "/api/app/version").json()["versionCode"] == 3
  r = requests.get(base + "/app/junpilot.apk")
  assert r.content == b"PK-apk" and r.headers["Content-Type"] == "application/vnd.android.package-archive"


def test_unexpected_error_returns_message(env, monkeypatch):
  app, dev, base = env

  def boom(*a, **k):
    raise TypeError("알림 저장 실패")
  monkeypatch.setattr(dev, "set_pairing_alert", boom)
  app._last_alert = None
  r = requests.post(base + "/api/show_code", json={})
  assert r.status_code == 500 and "TypeError" in r.json()["error"]
  monkeypatch.setattr(dev, "is_onroad", boom)
  r = requests.get(base + "/api/ping")
  assert r.status_code == 500 and "알림 저장 실패" in r.json()["error"]


def test_trusted_code_works_while_onroad(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  from openpilot.junpilot.web.server import App

  class Dev:
    onroad = True
    def is_onroad(self):
      return self.onroad
    def set_pairing_alert(self, *a, **k):
      pass
    def ip_addresses(self):
      return []

  app = App(Dev())
  assert not app.pairing_active()  # 장치 화면 코드는 주행 중 막힘
  code = app.new_trusted_code()
  assert app.pairing_active()
  assert app.pair(code, "폰")
  assert not app.pairing_active()  # 한 번 쓰면 닫힘
