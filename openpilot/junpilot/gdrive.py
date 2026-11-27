"""준파일럿: 구글 드라이브 직접 연결 (구글 기기 로그인).

1) 관리 페이지에서 '구글 로그인' → 화면에 코드와 google.com/device 주소가 뜸
2) 폰 브라우저에서 그 주소로 로그인하고 코드를 넣어 허용
3) 콤마가 받은 갱신 토큰으로 드라이브 API를 직접 써서 '준파일럿' 폴더에 올림

권한은 drive.file (준파일럿이 만든 파일만 접근). 앱 등록 값(클라이언트 ID)은 google_client.json에 둔다.
"""
import json
import os
import threading
import time

import requests

from openpilot.junpilot import store

CLIENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_client.json")
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,webViewLink"
SCOPE = "https://www.googleapis.com/auth/drive.file"
ROOT_FOLDER = "준파일럿"
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 8 * 1024 * 1024  # 256KB의 배수
TOKEN_FILE = "gdrive.json"


def client() -> dict | None:
  try:
    with open(CLIENT_FILE) as f:
      c = json.load(f)
    if c.get("client_id") and c.get("client_secret"):
      return c
  except (OSError, ValueError):
    pass
  return None


def connected() -> bool:
  return bool(store.load(TOKEN_FILE, {}).get("refresh_token")) and client() is not None


class Login:
  """기기 로그인 한 번의 진행 상태."""

  def __init__(self):
    self.state = "idle"     # idle / waiting / ok / error
    self.user_code = ""
    self.url = ""
    self.expires = 0.0
    self.error = ""
    self._stop = False

  def status(self) -> dict:
    left = max(0, int(self.expires - time.time())) if self.state == "waiting" else 0  # noqa: TID251
    return {"state": self.state, "user_code": self.user_code, "url": self.url, "expires_in": left, "error": self.error}

  def start(self, post=requests.post):
    c = client()
    if c is None:
      raise RuntimeError("구글 로그인용 앱 등록 값(google_client.json)이 아직 없어요.")
    r = post(DEVICE_URL, data={"client_id": c["client_id"], "scope": SCOPE}, timeout=15)
    if r.status_code != 200:
      raise RuntimeError(f"구글 로그인을 시작하지 못했어요: {r.text[:200]}")
    d = r.json()
    self.state, self.error = "waiting", ""
    self.user_code = d["user_code"]
    self.url = d.get("verification_url") or d.get("verification_uri") or "https://www.google.com/device"
    self.expires = time.time() + float(d.get("expires_in", 1800))  # noqa: TID251
    threading.Thread(target=self._poll, args=(c, d["device_code"], float(d.get("interval", 5)), post), daemon=True).start()

  def stop(self):
    self._stop = True

  def _poll(self, c: dict, device_code: str, interval: float, post):
    while not self._stop and time.time() < self.expires:  # noqa: TID251
      time.sleep(interval)
      try:
        r = post(TOKEN_URL, data={"client_id": c["client_id"], "client_secret": c["client_secret"], "device_code": device_code,
                                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=15)
        d = r.json()
      except Exception:
        continue
      if r.status_code == 200 and d.get("refresh_token"):
        store.save(TOKEN_FILE, {"refresh_token": d["refresh_token"], "connected_at": int(time.time())})  # noqa: TID251
        _token_cache.clear()
        self.state = "ok"
        return
      err = d.get("error", "")
      if err == "slow_down":
        interval += 5
      elif err not in ("authorization_pending", ""):
        self.state, self.error = "error", {"access_denied": "허용을 누르지 않았어요. 다시 시도해 주세요.",
                                           "expired_token": "코드 시간이 지났어요. 다시 시도해 주세요."}.get(err, err)
        return
    if self.state == "waiting":
      self.state, self.error = "error", "코드 시간이 지났어요. 다시 시도해 주세요."


_token_cache: dict = {}


def access_token(post=requests.post) -> str:
  if _token_cache.get("exp", 0) > time.time() + 60:  # noqa: TID251
    return _token_cache["token"]
  c, tok = client(), store.load(TOKEN_FILE, {})
  if c is None or not tok.get("refresh_token"):
    raise RuntimeError("구글 드라이브에 로그인되어 있지 않아요. 연결 탭에서 구글 로그인을 해 주세요.")
  r = post(TOKEN_URL, data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}, timeout=15)
  if r.status_code != 200:
    if "invalid_grant" in r.text:
      raise RuntimeError("구글 로그인이 만료됐어요. 연결 탭에서 다시 로그인해 주세요.")
    raise RuntimeError(f"구글 인증 오류: {r.text[:200]}")
  d = r.json()
  _token_cache.update(token=d["access_token"], exp=time.time() + float(d.get("expires_in", 3600)))  # noqa: TID251
  return d["access_token"]


def disconnect():
  tok = store.load(TOKEN_FILE, {})
  if tok.get("refresh_token"):
    try:
      requests.post(REVOKE_URL, data={"token": tok["refresh_token"]}, timeout=10)
    except Exception:
      pass
  store.save(TOKEN_FILE, {})
  _token_cache.clear()


def _auth() -> dict:
  return {"Authorization": f"Bearer {access_token()}"}


def folder(name: str, parent: str | None = None) -> dict:
  """준파일럿이 만든 폴더를 찾거나 만든다. {id, webViewLink}"""
  q = f"name = '{name.replace(chr(39), '')}' and mimeType = '{FOLDER_MIME}' and trashed = false"
  if parent:
    q += f" and '{parent}' in parents"
  r = requests.get(FILES_URL, headers=_auth(), params={"q": q, "fields": "files(id,webViewLink)", "spaces": "drive"}, timeout=20)
  r.raise_for_status()
  files = r.json().get("files", [])
  if files:
    return files[0]
  meta = {"name": name, "mimeType": FOLDER_MIME, **({"parents": [parent]} if parent else {})}
  r = requests.post(FILES_URL, headers=_auth(), params={"fields": "id,webViewLink"}, json=meta, timeout=20)
  r.raise_for_status()
  return r.json()


def upload(name: str, parent: str, size: int, chunks, on_bytes=lambda n: None) -> dict:
  """이어 올리기(resumable)로 파일 하나를 올린다. chunks: CHUNK 크기 바이트 묶음을 차례로 내주는 것."""
  r = requests.post(UPLOAD_URL, headers={**_auth(), "X-Upload-Content-Length": str(size),
                                         "Content-Type": "application/json; charset=UTF-8"},
                    json={"name": name, "parents": [parent]}, timeout=30)
  r.raise_for_status()
  session = r.headers["Location"]
  if size == 0:
    r = requests.put(session, headers={"Content-Length": "0"}, data=b"", timeout=60)
    r.raise_for_status()
    return r.json()
  sent = 0
  for chunk in chunks:
    end = sent + len(chunk) - 1
    for attempt in range(4):
      try:
        r = requests.put(session, headers={"Content-Range": f"bytes {sent}-{end}/{size}"}, data=chunk, timeout=300)
        if r.status_code in (200, 201):
          on_bytes(len(chunk))
          return r.json()
        if r.status_code == 308:
          break
        r.raise_for_status()
      except Exception:
        if attempt == 3:
          raise
        time.sleep(2 * (attempt + 1))
    sent = end + 1
    on_bytes(len(chunk))
  raise RuntimeError(f"{name} 올리기가 끝나지 않았어요.")
