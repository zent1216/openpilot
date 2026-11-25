#!/usr/bin/env python3
"""준파일럿 관리 페이지 서버.

- 같은 와이파이/핫스팟의 휴대폰·노트북에서 http://<장치 IP>:8082 로 접속
- 장치 화면에 뜬 6자리 페어링 코드로 한 번 연결하면 이후 자동 접속
- 사설망(192.168.x, 10.x, 172.16~31.x) 주소에서 온 요청만 받는다
"""
import hmac
import ipaddress
import json
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from openpilot.junpilot import store, drive, tracker
from openpilot.junpilot.collector import Broadcaster, drives_dir
from openpilot.junpilot.device import OFFICIAL_SETTINGS

PORT = int(os.getenv("JUNPILOT_PORT", "8082"))
PAIR_WINDOW = 10 * 60  # 페어링 코드 표시 시간(초)
MAX_FAILS = 5
LOCK_TIME = 60
COOKIE = "junpilot_token"
INDEX_HTML = os.path.join(os.path.dirname(__file__), "index.html")
APP_DIR = os.path.join(os.path.dirname(__file__), "app")  # 휴대폰 앱 APK (junpilot-app 빌드 결과를 함께 배포)
ROUTE_FILES = {"qlog": ("qlog.zst", "qlog"), "rlog": ("rlog.zst", "rlog"), "qcamera": ("qcamera.ts",)}


class App:
  def __init__(self, device, clock=time.monotonic):
    self.dev = device
    self.clock = clock
    self.lock = threading.Lock()
    self.code = ""
    self.code_until = 0.0
    self.code_trusted = False  # 이미 연결된 기기가 만든 코드면 주행 중에도 연결 가능
    self.fails = 0
    self.locked_until = 0.0
    self.job: drive.UploadJob | None = None
    self._last_alert: str | None = None
    self.broadcaster = Broadcaster()
    self.collector = None  # 장치에서 main()이 설정
    self.nmirror = None  # 장치에서 main()이 설정 (엔미러 연동)
    self.new_code()

  # ---- 페어링 ----
  def tokens(self) -> dict:
    return store.load("tokens.json", {})

  def new_code(self):
    with self.lock:
      self.code = f"{secrets.randbelow(1_000_000):06d}"
      self.code_until = self.clock() + PAIR_WINDOW
      self.code_trusted = False
      self.fails = 0

  def new_trusted_code(self) -> str:
    """이미 연결된 기기(휴대폰 크롬·노트북)에서 새 기기용 코드를 만든다. 장치 화면이 필요 없어 주행 중에도 된다."""
    with self.lock:
      self.code = f"{secrets.randbelow(1_000_000):06d}"
      self.code_until = self.clock() + PAIR_WINDOW
      self.code_trusted = True
      self.fails = 0
      return self.code

  def pairing_active(self) -> bool:
    return self.clock() < self.code_until and (self.code_trusted or not self.dev.is_onroad())

  def pair(self, code: str, name: str) -> str:
    with self.lock:
      now = self.clock()
      if now < self.locked_until:
        raise PermissionError(f"시도가 너무 많아요. {int(self.locked_until - now)}초 뒤에 다시 시도해 주세요.")
      if not self.pairing_active():
        raise PermissionError("지금은 연결할 수 없어요. '코드 다시 표시'를 누르고 장치 화면을 확인해 주세요.")
      if not hmac.compare_digest(code.strip(), self.code):
        self.fails += 1
        if self.fails >= MAX_FAILS:
          self.locked_until = now + LOCK_TIME
          self.fails = 0
        raise PermissionError("코드가 맞지 않아요.")
      token = secrets.token_hex(32)
      tokens = self.tokens()
      tokens[token] = {"name": (name or "기기")[:40], "paired": time.time()}  # noqa: TID251  벽시계 시각(표시용)
      store.save("tokens.json", tokens)
      self.code_until = 0.0  # 한 번 쓰면 바로 닫음
      return token

  def authed(self, token: str | None) -> bool:
    return bool(token) and any(hmac.compare_digest(token, t) for t in self.tokens())

  def update_alert(self):
    text = ""
    if self.pairing_active():
      addrs = ", ".join(f"{ip}:{PORT}" for ip in self.dev.ip_addresses()) or f"192.168.43.1:{PORT}"
      text = f"http://{addrs}  code {self.code}"  # 장치 글꼴에 한글이 없을 수 있어 영문만
    if text != self._last_alert:
      self.dev.set_pairing_alert(bool(text), text)
      self._last_alert = text

  # ---- 설정 ----
  def get_settings(self) -> dict:
    official = {}
    for k, spec in OFFICIAL_SETTINGS.items():
      official[k] = dict(spec, value=self.dev.get_param(k))
    jun = store.get_settings()
    return {"onroad": self.dev.is_onroad(), "official": official,
            "junpilot": {k: dict(spec, value=jun[k]) for k, spec in store.JUNPILOT_SETTINGS.items()}}

  def set_settings(self, body: dict):
    if self.dev.is_onroad():
      raise PermissionError("주행 중에는 설정을 바꿀 수 없어요. 시동을 끈 뒤 다시 시도해 주세요.")
    for k, v in (body.get("official") or {}).items():
      spec = OFFICIAL_SETTINGS.get(k)
      if spec is None:
        raise KeyError(k)
      if spec["type"] == "bool" and not isinstance(v, bool):
        raise ValueError(f"{spec['label']}: 켜기/끄기 값이어야 해요.")
      if spec["type"] == "choice_str" and v not in spec["choices"]:
        raise ValueError(f"{spec['label']}: 허용되지 않는 값이에요.")
    store_changes = body.get("junpilot") or {}
    for k, v in store_changes.items():
      store.validate_setting(k, v)
    for k, v in (body.get("official") or {}).items():
      self.dev.put_param(k, v)
    if store_changes:
      store.set_settings(store_changes)

  # ---- 주행 리포트 / 맞춤 튜닝 ----
  def tuning(self) -> dict:
    return {"suggestions": tracker.tuning_suggestions(tracker.list_drives(drives_dir()), store.get_settings())}

  def apply_tuning(self, body: dict):
    key = body.get("key")
    if key not in store.JUNPILOT_SETTINGS:
      raise ValueError("적용할 수 없는 항목이에요.")
    allowed = {s["key"]: s["value"] for s in self.tuning()["suggestions"] if s.get("key")}
    if allowed.get(key) != body.get("value"):
      raise ValueError("추천 내용이 바뀌었어요. 새로고침한 뒤 다시 시도해 주세요.")
    self.set_settings({"junpilot": {key: body["value"]}})

  # ---- 주행 기록 ----
  def routes(self) -> list[dict]:
    root = self.dev.log_root()
    groups: dict[str, dict] = {}
    try:
      names = os.listdir(root)
    except OSError:
      return []
    for d in names:
      path = os.path.join(root, d)
      if "--" not in d or not os.path.isdir(path):
        continue
      route, seg = d.rsplit("--", 1)
      if not seg.isdigit():
        continue
      g = groups.setdefault(route, {"route": route, "segments": [], "size": 0, "mtime": 0.0, "kinds": set()})
      g["segments"].append(int(seg))
      for f in os.listdir(path):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
          st = os.stat(fp)
          g["size"] += st.st_size
          g["mtime"] = max(g["mtime"], st.st_mtime)
          for kind, fnames in ROUTE_FILES.items():
            if f in fnames:
              g["kinds"].add(kind)
    out = []
    for g in groups.values():
      g["segments"].sort()
      g["kinds"] = sorted(g["kinds"])
      out.append(g)
    out.sort(key=lambda g: g["mtime"], reverse=True)
    return out

  def route_files(self, route: str, kinds: list[str], segments: list[int] | None) -> list[tuple[str, str]]:
    if "/" in route or ".." in route:
      raise ValueError("잘못된 경로예요.")
    root = self.dev.log_root()
    files = []
    for g in self.routes():
      if g["route"] != route:
        continue
      for seg in g["segments"]:
        if segments and seg not in segments:
          continue
        segdir = os.path.join(root, f"{route}--{seg}")
        for kind in kinds:
          for fname in ROUTE_FILES.get(kind, ()):
            fp = os.path.join(segdir, fname)
            if os.path.isfile(fp):
              files.append((f"{seg:03d}_{fname}", fp))
              break
    if not files:
      raise FileNotFoundError("보낼 파일이 없어요.")
    return files

  def send(self, body: dict) -> dict:
    if self.job and self.job.state in ("대기", "전송 중"):
      raise RuntimeError("이미 전송 중인 작업이 있어요.")
    route = str(body.get("route", ""))
    kinds = [k for k in body.get("kinds", ["qlog"]) if k in ROUTE_FILES] or ["qlog"]
    segments = [int(x) for x in (body.get("segments") or [])] or None
    files = self.route_files(route, kinds, segments)
    meta = {"route": route, "kinds": kinds, "note": str(body.get("note", ""))[:500],
            "device": self.dev.info(), "settings": self.get_settings(), "sent_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    bundle = time.strftime("%Y%m%d-%H%M%S") + "_" + route
    self.job = drive.UploadJob(bundle, files, meta)
    self.job.start()
    return self.job.status()


def app_version() -> dict:
  try:
    with open(os.path.join(APP_DIR, "version.json")) as f:
      return json.load(f)
  except (OSError, ValueError):
    return {"versionCode": 0, "versionName": ""}


def _private(addr: str) -> bool:
  try:
    ip = ipaddress.ip_address(addr)
  except ValueError:
    return False
  return ip.is_private or ip.is_loopback


def make_handler(app: App):
  class Handler(BaseHTTPRequestHandler):
    server_version = "junpilot"

    def log_message(self, *args):
      pass

    def _token(self):
      auth = self.headers.get("Authorization") or ""
      if auth.startswith("Bearer "):
        return auth[7:].strip()
      for part in (self.headers.get("Cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
          return v
      return None

    def _send(self, code: int, obj=None, body: bytes | None = None, ctype="application/json; charset=utf-8", headers=None):
      if body is None:
        body = json.dumps(obj, ensure_ascii=False).encode()
      self.send_response(code)
      self.send_header("Content-Type", ctype)
      self.send_header("Content-Length", str(len(body)))
      self.send_header("Cache-Control", "no-store")
      for k, v in (headers or {}).items():
        self.send_header(k, v)
      self.end_headers()
      self.wfile.write(body)

    def _body(self) -> dict:
      n = int(self.headers.get("Content-Length") or 0)
      if n > 1_000_000:
        raise ValueError("요청이 너무 커요.")
      return json.loads(self.rfile.read(n) or b"{}")

    def _guard(self) -> bool:
      if not _private(self.client_address[0]):
        self._send(403, {"error": "같은 와이파이나 핫스팟에서만 접속할 수 있어요."})
        return False
      return True

    def _safe(self, fn, method: str):
      """어떤 오류가 나도 연결을 그냥 끊지 않고 오류 내용을 돌려준다 (브라우저의 'Failed to fetch' 방지)."""
      try:
        fn()
      except (BrokenPipeError, ConnectionResetError):
        pass
      except Exception as e:
        _log_error(f"{method} {self.path}")
        try:
          self._send(500, {"error": f"서버 오류가 발생했어요: {type(e).__name__}: {e}"})
        except OSError:
          pass

    def do_GET(self):
      self._safe(self._get, "GET")

    def do_POST(self):
      self._safe(self._post, "POST")

    def _stream(self):
      """서버 전송 이벤트(SSE): 휴대폰 앱이 실시간 상태와 이벤트를 받는다."""
      q = app.broadcaster.subscribe()
      try:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(b": hello\n\n")
        self.wfile.flush()
        while True:
          try:
            msg = q.get(timeout=10)
          except queue.Empty:
            msg = ": ping\n\n"  # 연결 유지
          self.wfile.write(msg.encode())
          self.wfile.flush()
      except (BrokenPipeError, ConnectionResetError, OSError):
        pass
      finally:
        app.broadcaster.unsubscribe(q)

    def _get(self):
      if not self._guard():
        return
      path = urlparse(self.path).path
      if path in ("/", "/index.html"):
        with open(INDEX_HTML, "rb") as f:
          return self._send(200, body=f.read(), ctype="text/html; charset=utf-8")
      if path == "/api/app/version":
        return self._send(200, app_version())
      if path == "/app/junpilot.apk":
        apk = os.path.join(APP_DIR, "junpilot.apk")
        if not os.path.isfile(apk):
          return self._send(404, {"error": "앱 파일이 없어요."})
        with open(apk, "rb") as f:
          return self._send(200, body=f.read(), ctype="application/vnd.android.package-archive",
                            headers={"Content-Disposition": 'attachment; filename="junpilot.apk"'})
      if path == "/api/ping":
        return self._send(200, {"paired": app.authed(self._token()), "pairing": app.pairing_active()})
      if not app.authed(self._token()):
        return self._send(401, {"error": "기기 연결이 필요해요."})
      try:
        if path == "/api/status":
          return self._send(200, {"device": app.dev.info(), "onroad": app.dev.is_onroad(),
                                  "drive": {"configured": bool(drive.get_config()["url"])},
                                  "nmirror": app.nmirror.status() if app.nmirror else None,
                                  "job": app.job.status() if app.job else None})
        if path == "/api/settings":
          return self._send(200, app.get_settings())
        if path == "/api/routes":
          return self._send(200, {"routes": app.routes()})
        if path == "/api/state":
          return self._send(200, {"state": app.collector.last_state if app.collector else {}})
        if path == "/api/drives":
          return self._send(200, {"drives": tracker.list_drives(drives_dir())})
        if path.startswith("/api/drives/"):
          return self._send(200, tracker.load_drive(drives_dir(), path.rsplit("/", 1)[1]))
        if path == "/api/tuning":
          return self._send(200, app.tuning())
        if path == "/api/events":
          return self._stream()
        if path == "/api/job":
          return self._send(200, {"job": app.job.status() if app.job else None})
        if path.startswith("/api/download/"):
          _, _, _, route, seg, kind = path.split("/", 5)
          name, fp = app.route_files(unquote(route), [kind], [int(seg)])[0]
          fname = name.replace("/", "_")
          self.send_response(200)
          self.send_header("Content-Type", "application/octet-stream")
          self.send_header("Content-Length", str(os.path.getsize(fp)))
          self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
          self.end_headers()
          with open(fp, "rb") as f:  # 원본 로그는 커서 나눠 보낸다
            while chunk := f.read(1 << 20):
              self.wfile.write(chunk)
          return None
      except FileNotFoundError as e:
        return self._send(404, {"error": str(e)})
      except (KeyError, ValueError, IndexError) as e:
        return self._send(400, {"error": f"잘못된 요청이에요: {e}"})
      except Exception as e:
        _log_error(f"GET {path}")
        return self._send(500, {"error": f"서버 오류가 발생했어요: {type(e).__name__}: {e}"})
      self._send(404, {"error": "없는 주소예요."})

    def _post(self):
      if not self._guard():
        return
      path = urlparse(self.path).path
      try:
        body = self._body()
        if path == "/api/pair":
          token = app.pair(str(body.get("code", "")), str(body.get("name", "")))
          app.update_alert()
          cookie = f"{COOKIE}={token}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Strict"
          res = {"ok": True, "token": token} if body.get("client") == "app" else {"ok": True}
          return self._send(200, res, headers={"Set-Cookie": cookie})
        if path == "/api/show_code":
          if not app.dev.is_onroad():
            app.new_code()
            app.update_alert()
          return self._send(200, {"ok": True, "pairing": app.pairing_active()})
        if not app.authed(self._token()):
          return self._send(401, {"error": "기기 연결이 필요해요."})
        if path == "/api/pair_code":
          return self._send(200, {"code": app.new_trusted_code(), "minutes": PAIR_WINDOW // 60})
        if path == "/api/settings":
          app.set_settings(body)
          return self._send(200, app.get_settings())
        if path == "/api/tuning/apply":
          app.apply_tuning(body)
          return self._send(200, app.tuning())
        if path == "/api/drive":
          drive.set_config(str(body.get("url", "")), str(body.get("secret", "")))
          return self._send(200, {"ok": True})
        if path == "/api/send":
          return self._send(200, {"job": app.send(body)})
        if path == "/api/update/check":
          return self._send(200, {"ok": app.dev.check_update()})
        if path == "/api/reboot":
          if app.dev.is_onroad():
            raise PermissionError("주행 중에는 재부팅할 수 없어요.")
          app.dev.reboot()
          return self._send(200, {"ok": True})
        if path == "/api/unpair":
          tokens = app.tokens()
          tokens.pop(self._token(), None)
          store.save("tokens.json", tokens)
          return self._send(200, {"ok": True})
      except PermissionError as e:
        return self._send(403, {"error": str(e)})
      except (KeyError, ValueError, RuntimeError, FileNotFoundError) as e:
        return self._send(400, {"error": str(e)})
      except Exception as e:
        _log_error(f"POST {path}")
        return self._send(500, {"error": f"서버 오류가 발생했어요: {type(e).__name__}: {e}"})
      self._send(404, {"error": "없는 주소예요."})

  return Handler


def _log_error(where: str):
  """오류를 /data/junpilot/server_error.log 에 남김 (복구 페이지 '진단'에서 확인)."""
  import traceback
  try:
    with open(os.path.join(store.data_dir(), "server_error.log"), "a") as f:
      f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {where}\n{traceback.format_exc()}\n")
  except OSError:
    pass


def main():
  from openpilot.junpilot.device import Device
  try:
    app = App(Device())
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(app))
  except Exception:
    _log_error("시작")
    raise
  threading.Thread(target=httpd.serve_forever, daemon=True).start()  # 웹서버를 먼저 띄운다
  try:
    from openpilot.junpilot.nmirror import NMirrorServer
    app.nmirror = NMirrorServer(ip_addresses=app.dev.ip_addresses)
    app.nmirror.start()
  except Exception:
    _log_error("엔미러 연동")
  try:
    from openpilot.junpilot.collector import Collector
    app.collector = Collector(app.broadcaster)
    app.collector.start()
  except Exception:
    _log_error("주행 기록기")
  was_onroad = False
  started = time.monotonic()
  recorded = False
  while True:
    try:
      onroad = app.dev.is_onroad()
      if not recorded and time.monotonic() - started > 120:
        # 2분 이상 정상 동작한 버전은 복구 서버의 '되돌리기' 목록에 기록
        from openpilot.common.basedir import BASEDIR
        from openpilot.junpilot.recovery import record_good_commit
        record_good_commit(op_dir=BASEDIR, data_dir=store.data_dir())
        recorded = True
      if was_onroad and not onroad:
        app.new_code()  # 시동 끌 때마다 새 코드를 잠시 표시
      was_onroad = onroad
      app.update_alert()
    except Exception:
      _log_error("반복 작업")
      time.sleep(10)
    time.sleep(2)


if __name__ == "__main__":
  main()
