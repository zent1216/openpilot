"""엔미러(nMirror) 앱 연동: 휴대폰 TMAP의 단속카메라·구간단속 정보를 와이파이로 받는다.

neokii 님의 road_speed_limiter 방식과 같은 통신 규칙을 쓴다.
- 콤마4가 'EON:ROAD_LIMIT_SERVICE:v1'을 UDP 2899번으로 1초마다 뿌린다 (와이파이 전체 + 마지막으로 연결된 폰).
- 엔미러가 이 신호를 받으면 UDP 2843번으로 JSON({"road_limit": {...}, "active": 1})을 보낸다.

원본 코드에 있던 '폰이 보낸 명령(cmd)을 콤마4에서 실행'하는 기능은 위험해서 넣지 않았다.
받은 정보는 /dev/shm 파일로 남기고, 속도 계획기(controlsd)가 읽어 쓴다.
"""
import ipaddress
import json
import math
import os
import socket
import threading
import time

BROADCAST_PORT = 2899
RECEIVE_PORT = 2843
HELLO = b"EON:ROAD_LIMIT_SERVICE:v1"
STALE = 6.0  # 이 시간 동안 소식이 없으면 끊긴 것으로 봄
MAX_PACKET = 16 * 1024

STATE_PATH = os.getenv("JUNPILOT_NMIRROR_PATH",
                       "/dev/shm/junpilot_nmirror.json" if os.path.isdir("/dev/shm") and os.path.exists("/AGNOS") else "")

# 받는 값 (엔미러/TMAP 쪽 이름). 숫자 외의 값은 버린다
NUM_KEYS = ("road_limit_speed", "cam_type", "cam_limit_speed", "cam_limit_speed_left_dist", "section_limit_speed",
            "section_left_dist", "section_avg_speed", "section_left_time")

KPH = 1 / 3.6


def _private(addr: str) -> bool:
  try:
    ip = ipaddress.ip_address(addr)
  except ValueError:
    return False
  return (ip.is_private or ip.is_loopback) and ip not in ipaddress.ip_network("100.64.0.0/10")


def parse(data: bytes) -> dict | None:
  """받은 패킷에서 필요한 값만 골라낸다. 쓸 수 없는 패킷이면 None."""
  if len(data) > MAX_PACKET:
    return None
  try:
    obj = json.loads(data.decode("utf-8"))
  except (UnicodeDecodeError, ValueError):
    return None
  if not isinstance(obj, dict):
    return None
  out: dict = {}
  if "echo" in obj:
    out["echo"] = obj["echo"]
  if isinstance(obj.get("active"), (int, bool)):
    out["active"] = int(obj["active"])
  rl = obj.get("road_limit")
  if isinstance(rl, dict):
    vals = {}
    for k in NUM_KEYS:
      v = rl.get(k)
      if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
        vals[k] = float(v)
    if isinstance(rl.get("current_road_name"), str):
      vals["road_name"] = rl["current_road_name"][:40]
    out["road_limit"] = vals
  return out


def limit_from(rl: dict, v_ego: float, decel: float = 1.1) -> tuple[float, int]:
  """엔미러 정보로 지금 지켜야 할 제한속도(m/s)와 종류(1=카메라, 2=구간단속)를 계산. 없으면 (0, 0)."""
  sec_lim = rl.get("section_limit_speed", 0)
  if sec_lim > 0 and rl.get("section_left_dist", 0) > 0:
    return sec_lim * KPH, 2
  cam_lim = rl.get("cam_limit_speed", 0)
  dist = rl.get("cam_limit_speed_left_dist", 0)
  if cam_lim > 0 and dist > 0:
    lim = cam_lim * KPH
    # 카메라까지 decel로 줄일 수 있는 거리 + 5초 여유 안에 들어오면 감속 시작
    need = max(v_ego ** 2 - lim ** 2, 0) / (2 * decel) + v_ego * 5
    if dist <= max(need, 150):
      return lim, 1
  return 0.0, 0


class NMirrorServer:
  def __init__(self, clock=time.monotonic, ip_addresses=list):
    self.clock = clock
    self.ip_addresses = ip_addresses
    self.lock = threading.Lock()
    self.peer: str | None = None
    self.last_rx = 0.0
    self.last_limit = 0.0
    self.road_limit: dict = {}
    self.active = 0
    self.packets = 0

  # ---- 받기 ----
  def handle(self, data: bytes, addr: str, reply=None) -> bool:
    if not _private(addr):
      return False
    msg = parse(data)
    if msg is None:
      return False
    now = self.clock()
    with self.lock:
      self.peer = addr
      self.last_rx = now
      self.packets += 1
      if "active" in msg:
        self.active = msg["active"]
      if "road_limit" in msg:
        self.road_limit = msg["road_limit"]
        self.last_limit = now
    if "echo" in msg and reply is not None:
      reply(json.dumps(msg["echo"]).encode())
    self.write_state()
    return True

  def status(self) -> dict:
    now = self.clock()
    with self.lock:
      connected = self.peer is not None and now - self.last_rx < STALE
      fresh = connected and now - self.last_limit < STALE
      return {"connected": connected, "peer": self.peer if connected else None, "active": self.active if connected else 0,
              "road_limit": dict(self.road_limit) if fresh else {}, "age": round(now - self.last_rx, 1) if self.last_rx else None}

  def write_state(self):
    if not STATE_PATH:
      return
    st = self.status()
    try:
      tmp = STATE_PATH + ".tmp"
      with open(tmp, "w") as f:
        json.dump({"mono": time.monotonic(), "road_limit": st["road_limit"], "active": st["active"]}, f)
      os.replace(tmp, STATE_PATH)
    except OSError:
      pass

  # ---- 보내기 (내 위치 알리기) ----
  def targets(self) -> list[str]:
    out = {"255.255.255.255"}
    for ip in self.ip_addresses():
      try:
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        out.add(str(net.broadcast_address))
      except ValueError:
        pass
    with self.lock:
      if self.peer:
        out.add(self.peer)
    return sorted(out)

  def run(self):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("0.0.0.0", RECEIVE_PORT))
    rx.settimeout(1.0)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    last_hello = last_ips = 0.0
    ips: list[str] = []
    while True:
      now = time.monotonic()
      if now - last_hello >= 1.0:
        last_hello = now
        if now - last_ips > 10:
          last_ips = now
          ips = self.targets()
        with self.lock:
          peer = self.peer
        for t in set(ips) | ({peer} if peer else set()):
          try:
            tx.sendto(HELLO, (t, BROADCAST_PORT))
          except OSError:
            pass
        self.write_state()  # 끊겼을 때도 오래된 정보가 남지 않게
      try:
        data, (addr, _port) = rx.recvfrom(MAX_PACKET + 1)
      except TimeoutError:
        continue
      except OSError:
        time.sleep(1)
        continue
      self.handle(data, addr, reply=lambda b, a=addr: tx.sendto(b, (a, BROADCAST_PORT)))

  def start(self):
    threading.Thread(target=self.run, daemon=True, name="nmirror").start()


# ---- 속도 계획기(controlsd)에서 읽기 ----
_cache: dict = {"t": -1e9, "rl": {}}


def read_road_limit(path: str | None = None, clock=time.monotonic) -> dict:
  """엔미러가 마지막으로 보낸 정보 (0.5초마다 파일을 다시 읽음, 오래됐으면 빈 값)."""
  path = STATE_PATH if path is None else path
  now = clock()
  if now - _cache["t"] < 0.5:
    return _cache["rl"]
  _cache["t"] = now
  rl = {}
  if path:
    try:
      with open(path) as f:
        d = json.load(f)
      if time.monotonic() - d.get("mono", 0) < STALE:
        rl = d.get("road_limit") or {}
    except (OSError, ValueError):
      pass
  _cache["rl"] = rl
  return rl
