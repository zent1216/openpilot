import json
import time

from openpilot.junpilot import gdrive, store


class R:
  def __init__(self, code, d):
    self.status_code, self._d, self.text = code, d, json.dumps(d)

  def json(self):
    return self._d


def test_device_login_flow(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  cf = tmp_path / "client.json"
  cf.write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}))
  monkeypatch.setattr(gdrive, "CLIENT_FILE", str(cf))
  calls = []

  def post(url, data=None, timeout=None):
    calls.append((url, data))
    if url == gdrive.DEVICE_URL:
      assert data["scope"] == gdrive.SCOPE
      return R(200, {"device_code": "dc", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device",
                     "expires_in": 60, "interval": 0})
    n = sum(1 for u, _ in calls if u == gdrive.TOKEN_URL)
    if n < 3:
      return R(428, {"error": "authorization_pending"})
    return R(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

  assert not gdrive.connected()
  lg = gdrive.Login()
  lg.start(post=post)
  assert lg.status()["user_code"] == "ABCD-EFGH" and lg.status()["state"] == "waiting"
  for _ in range(100):
    if lg.state != "waiting":
      break
    time.sleep(0.02)
  assert lg.state == "ok" and gdrive.connected()
  assert store.load(gdrive.TOKEN_FILE, {})["refresh_token"] == "rt"


def test_denied(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  cf = tmp_path / "client.json"
  cf.write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}))
  monkeypatch.setattr(gdrive, "CLIENT_FILE", str(cf))

  def post(url, data=None, timeout=None):
    if url == gdrive.DEVICE_URL:
      return R(200, {"device_code": "dc", "user_code": "X", "verification_url": "u", "expires_in": 60, "interval": 0})
    return R(403, {"error": "access_denied"})
  lg = gdrive.Login()
  lg.start(post=post)
  for _ in range(100):
    if lg.state != "waiting":
      break
    time.sleep(0.02)
  assert lg.state == "error" and "허용" in lg.error and not gdrive.connected()


def test_no_client(tmp_path, monkeypatch):
  monkeypatch.setattr(gdrive, "CLIENT_FILE", str(tmp_path / "none.json"))
  assert gdrive.client() is None and not gdrive.connected()


def test_set_client(tmp_path, monkeypatch):
  import pytest
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  monkeypatch.setattr(gdrive, "CLIENT_FILE", str(tmp_path / "none.json"))
  with pytest.raises(ValueError):
    gdrive.set_client("bad", "x")
  gdrive.set_client(" a.apps.googleusercontent.com ", "s")
  assert gdrive.client()["client_id"] == "a.apps.googleusercontent.com"


def test_job_uploads_files_in_parallel(tmp_path, monkeypatch):
  from openpilot.junpilot import drive
  files = []
  for i in range(5):
    p = tmp_path / f"{i}.bin"
    p.write_bytes(b"x" * (1000 + i))
    files.append((f"{i}_rlog.zst", str(p)))
  monkeypatch.setattr(gdrive, "connected", lambda: True)
  monkeypatch.setattr(gdrive, "folder", lambda name, parent=None: {"id": "f", "webViewLink": "L"})
  got = []

  def up(name, parent, size, chunks, on_bytes=lambda n: None):
    data = b"".join(chunks)
    assert len(data) == size
    on_bytes(size)
    got.append(name)
    return {}
  monkeypatch.setattr(gdrive, "upload", up)
  job = drive.UploadJob("b", files, {"route": "r"})
  job.run()
  st = job.status()
  assert st["state"] == "완료" and st["progress"] == 100.0 and sorted(got) == sorted(["meta.json"] + [n for n, _ in files])
