import json
import os
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer

import pytest
import requests

from openpilot.junpilot import recovery


@pytest.fixture
def env(tmp_path, monkeypatch):
  op = tmp_path / "openpilot"
  op.mkdir()
  g = lambda *a: subprocess.run(["git", "-C", str(op), *a], check=True, capture_output=True)  # noqa: E731
  g("init", "-q", "-b", "junpilot")
  g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "첫 버전")
  data, params = tmp_path / "jp", tmp_path / "params"
  data.mkdir(); params.mkdir()
  monkeypatch.setattr(recovery, "OP_DIR", str(op))
  monkeypatch.setattr(recovery, "DATA_DIR", str(data))
  monkeypatch.setattr(recovery, "PARAMS_DIR", str(params))
  monkeypatch.setattr(recovery, "REBOOT", "echo reboot")
  recovery._job.update(name="", state="", log="")
  httpd = ThreadingHTTPServer(("127.0.0.1", 0), recovery.Handler)
  threading.Thread(target=httpd.serve_forever, daemon=True).start()
  yield op, data, params, f"http://127.0.0.1:{httpd.server_address[1]}", g
  httpd.shutdown()


def wait_job():
  for _ in range(100):
    if recovery._job["state"] != "진행 중":
      return recovery._job
    time.sleep(0.05)
  return recovery._job


def test_page_and_status_without_pairing(env):
  op, data, params, base, g = env
  assert "준파일럿 복구" in requests.get(base + "/").text
  s = requests.get(base + "/api/status").json()
  assert s["branch"] == "junpilot" and s["subject"] == "첫 버전" and s["good"] == []


def test_requires_token_once_paired(env):
  op, data, params, base, g = env
  (data / "tokens.json").write_text(json.dumps({"abc": {}}))
  assert requests.get(base + "/api/status").status_code == 401
  assert requests.get(base + "/api/status", cookies={"junpilot_token": "abc"}).status_code == 200


def test_record_and_reset_to_good_commit(env):
  op, data, params, base, g = env
  recovery.record_good_commit(str(op), str(data))
  good = json.loads((data / "good_commits.json").read_text())
  assert len(good) == 1
  g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "망가진 버전")
  assert requests.post(base + "/api/reset_good", json={"commit": "deadbeef"}).status_code == 400
  r = requests.post(base + "/api/reset_good", json={"commit": good[0]["commit"]})
  assert r.status_code == 200, r.text
  job = wait_job()
  assert job["state"] == "완료" and "reboot" in job["log"]
  assert requests.get(base + "/api/status").json()["subject"] == "첫 버전"


def test_blocked_while_onroad(env):
  op, data, params, base, g = env
  (params / "IsOnroad").write_text("1")
  assert requests.post(base + "/api/update_latest", json={}).status_code == 403
  assert requests.post(base + "/api/nope", json={}).status_code in (403, 404)


def test_restore_backup_requires_backup(env):
  op, data, params, base, g = env
  assert requests.post(base + "/api/restore_backup", json={}).status_code == 400


def test_recovery_has_no_openpilot_imports():
  src = open(recovery.__file__).read()
  assert "from openpilot" not in src.replace("from openpilot.junpilot.recovery", "") and "import openpilot" not in src
