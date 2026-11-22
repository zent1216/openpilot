"""주행 기록 묶음을 구글 드라이브(Apps Script 수신기)로 보낸다.

수신기 코드: openpilot/junpilot/apps_script/Code.gs
요청 본문(JSON): secret, bundle, name, part, total, data(base64)
"""
import base64
import json
import os
import threading
import time

import requests

from openpilot.junpilot import store

CHUNK = 8 * 1024 * 1024  # 원본 8MB (base64 후 약 11MB, Apps Script 한도 50MB 이내)


def get_config() -> dict:
  cfg = store.load("drive.json", {})
  return {"url": cfg.get("url", ""), "secret": cfg.get("secret", "")}


def set_config(url: str, secret: str) -> None:
  url, secret = url.strip(), secret.strip()
  if url and not url.startswith("https://script.google.com/"):
    raise ValueError("Apps Script 웹앱 주소(https://script.google.com/...)여야 함")
  store.save("drive.json", {"url": url, "secret": secret})


def _post(url: str, payload: dict, timeout: float = 120) -> None:
  # Apps Script는 302로 응답 주소를 넘겨준다. requests가 따라가서 결과 JSON을 받는다.
  r = requests.post(url, data=json.dumps(payload), headers={"Content-Type": "text/plain"}, timeout=timeout)
  r.raise_for_status()
  try:
    res = r.json()
  except ValueError as e:
    raise RuntimeError(f"수신기 응답이 이상함: {r.text[:200]}") from e
  if not res.get("ok"):
    raise RuntimeError(f"수신기 오류: {res.get('error', '알 수 없음')}")


class UploadJob:
  def __init__(self, bundle: str, files: list[tuple[str, str]], meta: dict, post=_post):
    """files: (드라이브에 저장할 이름, 장치 파일 경로) 목록"""
    self.bundle = bundle
    self.files = files
    self.meta = meta
    self.post = post
    self.total_bytes = sum(os.path.getsize(p) for _, p in files) + 1
    self.sent_bytes = 0
    self.state = "대기"
    self.error = ""
    self.started = time.time()
    self.finished: float | None = None

  def status(self) -> dict:
    return {"bundle": self.bundle, "state": self.state, "error": self.error,
            "progress": round(100 * self.sent_bytes / self.total_bytes, 1),
            "files": [n for n, _ in self.files], "started": self.started, "finished": self.finished}

  def _send_bytes(self, cfg: dict, name: str, data_iter, total_parts: int):
    for part, chunk in enumerate(data_iter):
      payload = {"secret": cfg["secret"], "bundle": self.bundle, "name": name, "part": part, "total": total_parts,
                 "data": base64.b64encode(chunk).decode()}
      for attempt in range(3):
        try:
          self.post(cfg["url"], payload)
          break
        except Exception:
          if attempt == 2:
            raise
          time.sleep(2 * (attempt + 1))
      self.sent_bytes += len(chunk)

  def run(self):
    cfg = get_config()
    try:
      if not cfg["url"] or not cfg["secret"]:
        raise RuntimeError("구글 드라이브 연결 설정이 비어 있음")
      self.state = "전송 중"
      meta = json.dumps(self.meta, ensure_ascii=False, indent=2).encode()
      self._send_bytes(cfg, "meta.json", [meta], 1)
      for name, path in self.files:
        size = os.path.getsize(path)
        parts = max(1, -(-size // CHUNK))

        def chunks(p=path):
          with open(p, "rb") as f:
            while True:
              b = f.read(CHUNK)
              if not b:
                break
              yield b
        self._send_bytes(cfg, name, chunks() if size else [b""], parts)
      self.state = "완료"
    except Exception as e:
      self.state = "실패"
      self.error = str(e)
    finally:
      self.finished = time.time()

  def start(self):
    threading.Thread(target=self.run, daemon=True).start()
