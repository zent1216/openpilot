"""준파일럿: 폰에서 콤마 주행 화면 보기.

- 영상: 콤마의 라이브 스트림용 인코더(앞 카메라, H.264)를 그대로 받아 폰으로 흘려 보낸다.
  폰(웹뷰)이 하드웨어 디코더로 풀어서 그린다. 와이파이 핫스팟에서도 되도록 WebRTC 대신 HTTP로 보낸다.
- 덮어 그리기: 차선·주행경로·앞차 위치를 콤마에서 화면 좌표(0~1)로 계산해 보내고, 폰은 그리기만 한다.
"""
import os
import struct
import time

import numpy as np

FLAG_FILE = "/dev/shm/junpilot_live"   # 이 파일이 최근에 갱신되면 매니저가 영상 인코더를 켬
FLAG_FRESH = 10.0                      # 초
BITRATE = 2_000_000
MAX_DRAW = 100.0
MIN_DRAW = 10.0
RADAR_TO_CAMERA = 1.52
LANE_W = (0.12, 0.16, 0.16, 0.12)
V4L2_BUF_FLAG_KEYFRAME = 0x8

# 진단용 (관리 서버의 /api/live/status)
STATS = {"video_source": "", "video_clients": 0, "video_msgs": 0, "video_sent": 0, "video_last": 0.0, "video_error": "",
         "overlay_clients": 0, "overlay_last": 0.0, "overlay_error": ""}


def status() -> dict:
  now = time.monotonic()
  s = dict(STATS)
  s["video_age"] = round(now - s.pop("video_last"), 1) if STATS["video_last"] else None
  s["overlay_age"] = round(now - s.pop("overlay_last"), 1) if STATS["overlay_last"] else None
  s["encoder_on"] = flag_active()
  return s


def flag_active(path: str = FLAG_FILE, now: float | None = None) -> bool:
  try:
    return (time.time() if now is None else now) - os.path.getmtime(path) < FLAG_FRESH  # noqa: TID251
  except OSError:
    return False


def touch_flag(path: str = FLAG_FILE):
  try:
    with open(path, "a"):
      pass
    os.utime(path, None)
  except OSError:
    pass


# ---------------- 화면 좌표 계산 ----------------
def camera_transform(rpy: list[float], intrinsics: np.ndarray) -> np.ndarray:
  from openpilot.common.transformations.camera import view_frame_from_device_frame
  from openpilot.common.transformations.orientation import rot_from_euler
  return intrinsics @ view_frame_from_device_frame @ rot_from_euler(rpy)


def line_polygon(T: np.ndarray, pts: np.ndarray, half_w: float, z_off: float, max_d: float, wh: tuple[float, float]) -> list:
  """3차원 선(x 앞, y 왼쪽, z 위)을 폭 있는 다각형으로 바꿔 화면 좌표(0~1)로. 안 보이면 빈 목록."""
  if pts.shape[0] == 0:
    return []
  pts = pts[(pts[:, 0] >= 0) & (pts[:, 0] <= max_d)]
  if pts.shape[0] < 2:
    return []
  pl = T @ (pts + np.array([0.0, -half_w, z_off])).T
  pr = T @ (pts + np.array([0.0, half_w, z_off])).T
  ok = (pl[2] > 0.5) & (pr[2] > 0.5)  # 카메라 바로 앞(차 안)은 버림
  if ok.sum() < 2:
    return []
  pl, pr = pl[:, ok], pr[:, ok]
  uv = np.concatenate([(pl[:2] / pl[2]).T, (pr[:2] / pr[2]).T[::-1]]) / np.array(wh)
  uv = np.clip(uv, -1.0, 2.0)
  return np.round(uv, 4).tolist()


def point(T: np.ndarray, xyz, wh) -> list | None:
  p = T @ np.asarray(xyz, dtype=float)
  if p[2] <= 1e-3:
    return None
  return [round(float(p[0] / p[2] / wh[0]), 4), round(float(p[1] / p[2] / wh[1]), 4)]


class OverlayBuilder:
  """수신한 메시지들로 폰에 보낼 덮어 그리기 정보를 만든다."""

  def __init__(self):
    self.T: np.ndarray | None = None
    self.wh = (1.0, 1.0)
    self.calib_key = None
    from openpilot.junpilot.traffic import TrafficLight
    self.traffic = TrafficLight()

  def _update_transform(self, sm):
    from openpilot.common.transformations.camera import DEVICE_CAMERAS
    calib = sm['extrinsicsCalibration'] if sm.seen.get('extrinsicsCalibration') else None
    rpy = list(calib.rpyCalib) if calib is not None and len(calib.rpyCalib) == 3 else [0.0, 0.0, 0.0]
    key = (str(sm['deviceState'].deviceType), str(sm['narrowRoadCameraState'].sensor), tuple(round(x, 4) for x in rpy))
    if key == self.calib_key and self.T is not None:
      return
    cam = DEVICE_CAMERAS.get((key[0], key[1])) or DEVICE_CAMERAS[("tici", "ar0231")]
    nr = cam.narrow_road
    self.T = camera_transform(rpy, nr.intrinsics)
    self.wh = (float(nr.width), float(nr.height))
    self.calib_key = key

  def build(self, sm) -> dict:
    self._update_transform(sm)
    T, wh = self.T, self.wh
    md, cs, ss, rs = sm['modelV2'], sm['carState'], sm['selfdriveState'], sm['radarState']
    calib = sm['extrinsicsCalibration']
    height = float(calib.height[0]) if len(calib.height) else 1.22
    out: dict = {"aspect": round(wh[0] / wh[1], 4), "lanes": [], "edges": [], "path": [], "lead": None}

    path = np.column_stack([md.position.x, md.position.y, md.position.z]) if len(md.position.x) else np.empty((0, 3))
    max_d = float(np.clip(path[-1, 0], MIN_DRAW, MAX_DRAW)) if len(path) else MAX_DRAW
    for i, ll in enumerate(md.laneLines):
      prob = float(md.laneLineProbs[i]) if i < len(md.laneLineProbs) else 0.0
      if prob < 0.05:
        continue
      pts = np.column_stack([ll.x, ll.y, ll.z])
      out["lanes"].append({"p": round(prob, 2), "poly": line_polygon(T, pts, LANE_W[i] * prob, 0.0, max_d, wh)})
    for i, re in enumerate(md.roadEdges):
      std = float(md.roadEdgeStds[i]) if i < len(md.roadEdgeStds) else 1.0
      pts = np.column_stack([re.x, re.y, re.z])
      out["edges"].append({"a": round(float(np.clip(1.0 - std, 0.0, 1.0)), 2), "poly": line_polygon(T, pts, 0.12, 0.0, max_d, wh)})

    lead = rs.leadOne
    path_d = max_d
    if lead.present:
      d = lead.dRel + RADAR_TO_CAMERA
      path_d = float(np.clip(d * 2.0 - min(d * 0.7, 10.0), 0.0, max_d)) if d < max_d else max_d
      if len(path):
        z = float(np.interp(d, path[:, 0], path[:, 2])) + height
        y = -float(lead.yRel)  # 레이더는 왼쪽이 +, 카메라 좌표는 오른쪽이 +
        out["lead"] = {"pt": point(T, [d, y, z], wh), "left": point(T, [d, y - 0.9, z], wh),
                       "right": point(T, [d, y + 0.9, z], wh), "d": round(float(lead.dRel), 1),
                       "kph": round(float(lead.vLead) * 3.6)}
    out["path"] = line_polygon(T, path, 0.9, height, path_d, wh) if len(path) else []

    tl = self.traffic.update(time.monotonic(), cs.vEgo, list(md.velocity.x), list(md.position.x), lead.present, lead.dRel)
    cruise_speed = cs.cruiseState.speedCluster or cs.cruiseState.speed
    out["hud"] = {
      "kph": round(cs.vEgo * 3.6), "set": round(cruise_speed * 3.6) if cs.cruiseState.enabled else 0,
      "engaged": bool(ss.enabled), "active": bool(ss.active), "status": str(ss.alertStatus),
      "alert1": str(ss.alertText1), "alert2": str(ss.alertText2),
      "blinker_l": bool(cs.leftBlinker), "blinker_r": bool(cs.rightBlinker),
      "bsm_l": bool(cs.leftBlindspot), "bsm_r": bool(cs.rightBlindspot),
      "traffic": tl, "steer": round(float(cs.steeringAngleDeg), 1), "gap": int(getattr(cs, "junpilotCruiseGap", 0) or 0),
    }
    return out


# ---------------- 영상 ----------------
def pack_frame(data: bytes, keyframe: bool, ts_us: int) -> bytes:
  """[길이 4바이트][키프레임 1바이트][시각(us) 8바이트][H.264 데이터]"""
  return struct.pack(">IBQ", len(data), 1 if keyframe else 0, ts_us) + data


def video_frames(stop, params=None):
  """라이브 인코더 프레임을 차례로 내준다 (stop()이 참이면 끝)."""
  from openpilot.cereal import messaging
  from openpilot.common.params import Params
  params = params or Params()
  STATS["video_clients"] += 1
  try:
    params.put("LivestreamEncoderBitrate", BITRATE)
    params.put("LivestreamRequestKeyframe", True)
  except Exception as e:
    STATS["video_error"] = f"설정 실패: {e}"
  sock = messaging.sub_sock("livestreamNarrowRoadEncodeData", conflate=False, timeout=200)
  try:
    yield from _video_loop(stop, params, sock)
  finally:
    STATS["video_clients"] -= 1


def _video_loop(stop, params, sock):
  """고화질(라이브 인코더)을 먼저 받고, 4초 안에 안 오면 늘 녹화되는 저화질(qcamera) 영상으로 바꿈."""
  from openpilot.cereal import messaging
  STATS["video_error"] = ""
  STATS["video_source"] = "고화질"
  seen_key = False
  got_any = False
  started = last_touch = time.monotonic()
  while not stop():
    now = time.monotonic()
    if now - last_touch > 2.0:
      touch_flag()
      last_touch = now
      if not seen_key:
        params.put("LivestreamRequestKeyframe", True)
    if not got_any and now - started > 4.0 and STATS["video_source"] == "고화질":
      sock = messaging.sub_sock("qNarrowRoadEncodeData", conflate=False, timeout=200)
      STATS["video_source"] = "저화질"
      seen_key = False
    msg = messaging.recv_one(sock)
    if msg is None:
      continue
    got_any = True
    STATS["video_msgs"] += 1
    ed = getattr(msg, msg.which())
    key = bool(ed.idx.flags & V4L2_BUF_FLAG_KEYFRAME)
    if not seen_key:
      if not key:
        continue
      seen_key = True
      params.put("LivestreamRequestKeyframe", False)
    STATS["video_sent"] += 1
    STATS["video_last"] = time.monotonic()
    yield pack_frame(bytes(ed.header) + bytes(ed.data), key, int(msg.logMonoTime // 1000))


def overlay_frames(stop, hz: float = 15.0):
  """덮어 그리기 정보를 hz번/초로 내준다."""
  import json
  from openpilot.cereal import messaging
  sm = messaging.SubMaster(['modelV2', 'carState', 'selfdriveState', 'radarState', 'extrinsicsCalibration',
                            'deviceState', 'narrowRoadCameraState'])
  ob = OverlayBuilder()
  period = 1.0 / hz
  STATS["overlay_clients"] += 1
  try:
    while not stop():
      t0 = time.monotonic()
      sm.update(0)
      if sm.seen['modelV2'] and sm.seen['carState'] and sm.seen['deviceState']:
        try:
          data = json.dumps(ob.build(sm), separators=(",", ":"))
          STATS["overlay_last"] = time.monotonic()
          STATS["overlay_error"] = ""
          yield data
        except Exception as e:  # 한 번 실패해도 계속
          STATS["overlay_error"] = f"{type(e).__name__}: {e}"
          yield json.dumps({"error": STATS["overlay_error"]})
      else:
        yield json.dumps({"idle": True})  # 주행 중이 아니라 그릴 정보가 없음
      time.sleep(max(0.0, period - (time.monotonic() - t0)))
  finally:
    STATS["overlay_clients"] -= 1
