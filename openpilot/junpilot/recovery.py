#!/usr/bin/env python3
# ruff: noqa: E501, ISC002
"""준파일럿 복구 서버 (포트 8083).

오픈파일럿이 켜지지 않거나 업데이트 후 망가져도 휴대폰으로 되살릴 수 있게 한다.
- 표준 라이브러리만 사용하고 openpilot 코드를 import 하지 않는다 (본체가 망가져도 동작)
- launch_chffrplus.sh 에서 빌드/매니저보다 먼저 별도 프로세스로 실행
- 같은 와이파이/핫스팟(사설망)에서만 접속, 관리 페이지에서 연결한 기기만 사용 가능
  (아직 연결한 기기가 하나도 없으면 사설망 접속만으로 허용)
기능: 상태/로그 보기, 정상 동작했던 버전으로 되돌리기, 최신 버전 다시 받기, 업데이트 직전 버전 복원, 재부팅
"""
import hmac
import ipaddress
import json
import os
import shlex
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = int(os.getenv("JUNPILOT_RECOVERY_PORT", "8083"))
OP_DIR = os.getenv("JUNPILOT_OP_DIR", "/data/openpilot")
DATA_DIR = os.getenv("JUNPILOT_DIR", "/data/junpilot")
BACKUP_DIR = "/data/safe_staging/old_openpilot"
PARAMS_DIR = "/data/params/d"
COOKIE = "junpilot_token"  # 관리 페이지(8082)와 같은 쿠키 (쿠키는 포트를 구분하지 않음)

_job = {"name": "", "state": "", "log": "", "started": 0.0}
_job_lock = threading.Lock()


def _read(path: str, default: str = "") -> str:
  try:
    with open(path, errors="replace") as f:
      return f.read()
  except OSError:
    return default


def _load_json(name: str, default):
  try:
    return json.loads(_read(os.path.join(DATA_DIR, name), "")) or default
  except ValueError:
    return default


def is_onroad() -> bool:
  return _read(os.path.join(PARAMS_DIR, "IsOnroad")).strip() in ("1", "\x01")


def git(*args: str, timeout: float = 20) -> str:
  try:
    r = subprocess.run(["git", "-C", OP_DIR, *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout or r.stderr).strip()
  except Exception as e:
    return f"(실패: {e})"


def good_commits() -> list[dict]:
  return _load_json("good_commits.json", [])


def status() -> dict:
  return {
    "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
    "commit": git("rev-parse", "--short", "HEAD"),
    "subject": git("log", "-1", "--format=%s"),
    "onroad": is_onroad(),
    "manager": subprocess.run(["pgrep", "-f", "manager.py"], capture_output=True).returncode == 0,
    "backup": os.path.isdir(BACKUP_DIR),
    "good": good_commits(),
    "launch_log": _read("/tmp/launch_log")[-6000:],
    "job": dict(_job),
  }


def _run_job(name: str, cmd: str):
  with _job_lock:
    if _job["state"] == "진행 중":
      raise RuntimeError("이미 진행 중인 작업이 있어요.")
    _job.update(name=name, state="진행 중", log="", started=time.time())  # noqa: TID251  벽시계 시각(표시용)

  def work():
    try:
      p = subprocess.Popen(["bash", "-lc", cmd], cwd=OP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
      for line in p.stdout:
        _job["log"] = (_job["log"] + line)[-20000:]
      ok = p.wait() == 0
      _job["state"] = "완료" if ok else "실패"
    except Exception as e:
      _job["log"] += f"\n{e}"
      _job["state"] = "실패"
  threading.Thread(target=work, daemon=True).start()


REBOOT = "sync; sleep 2; sudo reboot"


def action(name: str, body: dict):
  if name != "reboot" and is_onroad():
    raise PermissionError("주행 중에는 할 수 없어요. 시동을 끈 뒤 다시 시도해 주세요.")
  if name == "reboot":
    _run_job("재부팅", REBOOT)
  elif name == "reset_good":
    commit = str(body.get("commit", ""))
    if commit not in [c["commit"] for c in good_commits()]:
      raise ValueError("목록에 있는 버전만 고를 수 있어요.")
    c = shlex.quote(commit)
    _run_job(f"{commit[:8]} 버전으로 되돌리기",
             f"git reset --hard {c} && git submodule update --init --recursive && rm -f prebuilt && {REBOOT}")
  elif name == "update_latest":
    branch = shlex.quote(git("rev-parse", "--abbrev-ref", "HEAD") or "junpilot")
    _run_job("최신 버전 다시 받기",
             f"git fetch origin {branch} && git reset --hard origin/{branch} && "
             f"git submodule update --init --recursive && rm -f prebuilt && {REBOOT}")
  elif name == "restore_backup":
    if not os.path.isdir(BACKUP_DIR):
      raise ValueError("업데이트 직전 버전이 남아 있지 않아요.")
    _run_job("업데이트 직전 버전 복원",
             f"rm -rf /data/safe_staging/broken_openpilot && mv {OP_DIR} /data/safe_staging/broken_openpilot && "
             f"mv {BACKUP_DIR} {OP_DIR} && {REBOOT}")
  else:
    raise KeyError(name)


def _private(addr: str) -> bool:
  try:
    ip = ipaddress.ip_address(addr)
  except ValueError:
    return False
  return ip.is_private or ip.is_loopback


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>준파일럿 복구</title>
<style>
body{margin:0;background:#0f1115;color:#e8eaee;font:15px/1.5 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0 14px}h1 b{color:#ff8a3d}
.card{background:#181b22;border:1px solid #262a33;border-radius:12px;padding:14px;margin-bottom:12px}
h2{font-size:14px;color:#8b92a0;margin:0 0 8px}.row{display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid #262a33}
.row:first-of-type{border:0}.k{color:#8b92a0}button{width:100%;padding:11px;border:0;border-radius:10px;font-weight:700;font-size:15px;margin-top:8px;background:#262a33;color:#e8eaee}
button.main{background:#ff8a3d;color:#1a1205}pre{white-space:pre-wrap;word-break:break-all;font-size:12px;color:#8b92a0;max-height:260px;overflow:auto;background:#0f1115;padding:8px;border-radius:8px}
.msg{padding:10px;border-radius:8px;margin-bottom:12px;background:#3d1c1c;color:#ffb3b3}.ok{background:#163a2b;color:#9ff0c9}small{color:#8b92a0}
</style></head><body><main><h1><b>준</b>파일럿 복구</h1>
<p><small>오픈파일럿이 켜지지 않거나 이상할 때 쓰는 페이지예요. 작업을 하면 장치가 자동으로 재부팅돼요.</small></p>
<div id="msg"></div>
<div class="card"><h2>현재 상태</h2><div id="st">불러오는 중…</div></div>
<div class="card"><h2>정상 동작했던 버전으로 되돌리기</h2><div id="good"></div></div>
<div class="card"><h2>기타</h2>
<button class="main" onclick="act('update_latest','최신 버전을 다시 받고 재부팅할까요?')">최신 버전 다시 받기</button>
<button id="bk" onclick="act('restore_backup','업데이트 직전 버전으로 되돌리고 재부팅할까요?')">업데이트 직전 버전 복원</button>
<button onclick="act('reboot','재부팅할까요?')">재부팅</button></div>
<div class="card"><h2>작업 기록</h2><pre id="job">없음</pre></div>
<div class="card"><h2>시작 기록 (launch_log)</h2><pre id="log"></pre></div>
</main><script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function row(k,v){return `<div class="row"><span class="k">${k}</span><span>${v}</span></div>`}
async function load(){const r=await fetch('/api/status');const s=await r.json();if(!r.ok){$('#msg').innerHTML=`<div class="msg">${esc(s.error)}</div>`;return}
$('#st').innerHTML=row('브랜치',esc(s.branch))+row('버전',esc(s.commit)+' '+esc(s.subject))+row('오픈파일럿',s.manager?'실행 중':'꺼져 있음')+row('주행',s.onroad?'주행 중':'정차');
$('#good').innerHTML=s.good.length?s.good.map(g=>`<button onclick="act('reset_good','${esc(g.commit).slice(0,8)} 버전으로 되돌리고 재부팅할까요?',{commit:'${esc(g.commit)}'})">${esc(g.commit).slice(0,8)} · ${esc(g.when)}<br><small>${esc(g.subject)}</small></button>`).join(''):'<small>아직 기록된 버전이 없어요. 정상적으로 2분 이상 켜져 있던 버전이 자동으로 기록돼요.</small>';
$('#bk').style.display=s.backup?'':'none';$('#log').textContent=s.launch_log||'없음';
if(s.job&&s.job.name)$('#job').textContent=`[${s.job.state}] ${s.job.name}\\n\\n${s.job.log}`}
async function act(a,q,body={}){if(!confirm(q))return;const r=await fetch('/api/'+a,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();
$('#msg').innerHTML=`<div class="msg ${r.ok?'ok':''}">${esc(r.ok?'작업을 시작했어요. 끝나면 자동으로 재부팅돼요.':j.error)}</div>`;load()}
load();setInterval(load,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
  server_version = "junpilot-recovery"

  def log_message(self, *args):
    pass

  def _send(self, code, obj=None, body=None, ctype="application/json; charset=utf-8"):
    body = body if body is not None else json.dumps(obj, ensure_ascii=False).encode()
    self.send_response(code)
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)

  def _allowed(self) -> bool:
    if not _private(self.client_address[0]):
      self._send(403, {"error": "같은 와이파이나 핫스팟에서만 접속할 수 있어요."})
      return False
    tokens = _load_json("tokens.json", {})
    if not tokens:
      return True
    token = ""
    for part in (self.headers.get("Cookie") or "").split(";"):
      k, _, v = part.strip().partition("=")
      if k == COOKIE:
        token = v
    if any(hmac.compare_digest(token, t) for t in tokens):
      return True
    self._send(401, {"error": "관리 페이지(8082)에서 기기를 먼저 연결해 주세요."})
    return False

  def do_GET(self):
    path = urlparse(self.path).path
    if path == "/":
      if not _private(self.client_address[0]):
        return self._send(403, {"error": "같은 와이파이나 핫스팟에서만 접속할 수 있어요."})
      return self._send(200, body=PAGE.encode(), ctype="text/html; charset=utf-8")
    if not self._allowed():
      return
    if path == "/api/status":
      return self._send(200, status())
    self._send(404, {"error": "없는 주소예요."})

  def do_POST(self):
    if not self._allowed():
      return
    path = urlparse(self.path).path
    try:
      n = int(self.headers.get("Content-Length") or 0)
      body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
      if not path.startswith("/api/"):
        raise KeyError(path)
      action(path[len("/api/"):], body)
      return self._send(200, {"ok": True})
    except PermissionError as e:
      return self._send(403, {"error": str(e)})
    except KeyError:
      return self._send(404, {"error": "없는 주소예요."})
    except (ValueError, RuntimeError) as e:
      return self._send(400, {"error": str(e)})


def record_good_commit(op_dir: str = OP_DIR, data_dir: str = DATA_DIR, keep: int = 10):
  """정상 동작 중인 현재 버전을 기록 (관리 페이지 서버가 2분 이상 살아 있을 때 호출)."""
  r = lambda *a: subprocess.run(["git", "-C", op_dir, *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
  commit = r("rev-parse", "HEAD")
  if not commit:
    return
  path = os.path.join(data_dir, "good_commits.json")
  try:
    items = json.loads(_read(path, "[]"))
  except ValueError:
    items = []
  items = [i for i in items if i.get("commit") != commit]
  items.insert(0, {"commit": commit, "subject": r("log", "-1", "--format=%s"), "when": time.strftime("%Y-%m-%d %H:%M")})
  os.makedirs(data_dir, exist_ok=True)
  tmp = path + ".tmp"
  with open(tmp, "w") as f:
    json.dump(items[:keep], f, ensure_ascii=False, indent=2)
  os.replace(tmp, path)


def main():
  ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
  main()
