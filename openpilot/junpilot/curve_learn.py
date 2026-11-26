"""준파일럿: 커브 조향 자가 학습.

커브에서 운전자가 핸들을 직접 돌려 고쳐 준 만큼을 기억했다가, 비슷한 커브(같은 방향·비슷한 굽기·비슷한 속도)에서
모델이 낸 곡률에 그 비율을 곱해 준다.

- 배우는 것: (운전자가 실제로 만든 곡률) / (모델이 원래 내려던 곡률). 1보다 작으면 '덜 꺾어야 했다'.
- 배우는 때: 오파가 조향 중이고, 운전자가 0.5초 넘게 핸들을 돌려 고친 커브 (깜빡이·차선변경·저속·급조작 제외)
- 안전 장치: 한 번에 조금씩만 배우고, 적용은 0.85~1.10배 안에서만. 표본이 쌓이기 전에는 거의 적용 안 함.
  학습값은 모델 원래 곡률 기준이라 학습이 학습을 부추기는 되먹임이 없다.
- 완전 적용(5번) 뒤: 같은 종류의 커브를 고치지 않고 2초 넘게 지나가면 '검증 통과'로 센다.
  그 뒤에도 고치면 더 작은 폭으로 '세밀 보정'한다 (몇 번 보정했는지, 마지막 보정 뒤 몇 번 통과했는지 기록).
"""
import json
import os
import time

import numpy as np

from openpilot.junpilot import store

FILE = "curve_learn.json"
CURV_EDGES = (0.002, 0.004, 0.008, 0.015, 0.03)    # 1/m. 반경 약 500·250·125·67·33m
SPEED_EDGES_KPH = (50.0,)                            # 50km/h 아래 / 위
MIN_KPH = 20.0
MIN_CURV = CURV_EDGES[0]
HOLD = 0.5            # 초, 이만큼 이어서 고쳐야 표본으로 씀
MAX_HOLD = 6.0        # 초, 너무 길면(그냥 직접 운전) 버림
RATIO_CLIP = (0.7, 1.3)
SCALE_CLIP = (0.85, 1.10)
ALPHA = 0.2           # 표본 하나가 학습값에 주는 비중
FINE_ALPHA = 0.08     # 완전 적용 뒤 세밀 보정 비중
PASS_HOLD = 2.0       # 초, 고치지 않고 이만큼 지나가면 검증 통과
STABLE_PASSES = 5     # 마지막 보정 뒤 이만큼 통과하면 '안정'
FULL_COUNT = 5        # 이만큼 쌓이면 학습값을 온전히 적용
SAVE_EVERY = 30.0


def bucket(curv: float, v_ego: float) -> str | None:
  a = abs(curv)
  if a < MIN_CURV or v_ego * 3.6 < MIN_KPH:
    return None
  ci = int(np.searchsorted(CURV_EDGES, a, side="right")) - 1
  si = int(np.searchsorted(SPEED_EDGES_KPH, v_ego * 3.6, side="right"))
  return f"{'L' if curv > 0 else 'R'}{ci}s{si}"


class CurveLearner:
  def __init__(self, path: str | None = None):
    self.path = path or os.path.join(store.data_dir(), FILE)
    self.bins: dict[str, dict] = self._load()
    self._win: list[tuple[float, float]] = []   # (모델 곡률, 실제 곡률)
    self._win_key: str | None = None
    self._win_t0 = 0.0
    self._dirty = False
    self._saved_t = time.monotonic()
    self._pass_key: str | None = None   # 검증: 지금 지나는 커브 칸
    self._pass_t0 = 0.0
    self._pass_bad = False

  def _load(self) -> dict:
    try:
      with open(self.path) as f:
        d = json.load(f)
      return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
      return {}

  def save(self):
    if not self._dirty:
      return
    os.makedirs(os.path.dirname(self.path), exist_ok=True)
    tmp = self.path + ".tmp"
    with open(tmp, "w") as f:
      json.dump(self.bins, f)
    os.replace(tmp, self.path)
    self._dirty = False

  def reset(self):
    self.bins = {}
    self._dirty = True
    self.save()

  def scale(self, model_curv: float, v_ego: float) -> float:
    """모델 곡률에 곱할 배율."""
    b = self.bins.get(bucket(model_curv, v_ego) or "")
    if not b:
      return 1.0
    conf = min(b["n"] / FULL_COUNT, 1.0)
    return float(np.clip(1.0 + (b["ratio"] - 1.0) * conf, *SCALE_CLIP))

  def update(self, now: float, v_ego: float, model_curv: float, actual_curv: float, lat_active: bool,
             steering_pressed: bool, blinker: bool) -> str | None:
    """매 주기 호출. 표본 하나를 배웠으면 그 칸 이름을 돌려준다."""
    key = bucket(model_curv, v_ego)
    correcting = lat_active and steering_pressed and not blinker and key is not None
    learned = None
    if correcting and (self._win_key in (None, key)):
      if self._win_key is None:
        self._win_key, self._win_t0 = key, now
      self._win.append((model_curv, actual_curv))
    else:
      learned = self._finish(now)
      if correcting:  # 다른 칸으로 넘어가며 계속 고치는 중이면 새로 시작
        self._win_key, self._win_t0 = key, now
        self._win = [(model_curv, actual_curv)]

    self._track_pass(now, key if lat_active and not blinker else None, steering_pressed)

    # 배울 때는 드물어서 바로 저장 (시동을 끄면 조향 프로세스가 바로 꺼져 모아 두면 잃음)
    if learned is not None or (self._dirty and now - self._saved_t > SAVE_EVERY):
      self._saved_t = now
      try:
        self.save()
      except OSError:
        pass
    return learned

  def _track_pass(self, now: float, key: str | None, pressed: bool):
    """완전 적용된 칸의 커브를 운전자가 고치지 않고 지나가면 검증 통과로 센다."""
    if key != self._pass_key:
      old = self._pass_key
      if old is not None and not self._pass_bad and now - self._pass_t0 >= PASS_HOLD:
        b = self.bins.get(old)
        if b and b["n"] >= FULL_COUNT:
          b["pass"] = b.get("pass", 0) + 1
          b["pass_since"] = b.get("pass_since", 0) + 1
          self._dirty = True
      self._pass_key, self._pass_t0, self._pass_bad = key, now, False
    if pressed:
      self._pass_bad = True

  def _finish(self, now: float) -> str | None:
    key, win, t0 = self._win_key, self._win, self._win_t0
    self._win_key, self._win = None, []
    if key is None or not (HOLD <= now - t0 <= MAX_HOLD) or len(win) < 5:
      return None
    m = np.array(win)
    model, actual = m[:, 0].mean(), m[:, 1].mean()
    if abs(model) < MIN_CURV or np.sign(model) != np.sign(actual):
      return None
    ratio = float(np.clip(actual / model, *RATIO_CLIP))
    b = dict(self.bins.get(key, {"ratio": 1.0, "n": 0}))
    fine = b["n"] >= FULL_COUNT  # 완전 적용 뒤에도 고쳤으면 작은 폭으로 세밀 보정
    b["ratio"] = round(b["ratio"] + (FINE_ALPHA if fine else ALPHA) * (ratio - b["ratio"]), 4)
    b["n"] += 1
    if fine:
      b["fine"] = b.get("fine", 0) + 1
      b["pass_since"] = 0
    self.bins[key] = b
    self._dirty = True
    return key


def status(b: dict) -> str:
  """진행 상태 문구."""
  n = b["n"]
  if n < FULL_COUNT:
    return f"{FULL_COUNT - n}번 더 배우면 완전 적용"
  fine, since = b.get("fine", 0), b.get("pass_since", 0)
  if fine and since < STABLE_PASSES:
    return f"{fine}회 세밀 보정 중" + (f" · 보정 뒤 {since}번 통과" if since else "")
  if since >= STABLE_PASSES or b.get("pass", 0) >= STABLE_PASSES:
    return f"안정 · 검증 {b.get('pass', 0)}번 통과" + (f" (세밀 보정 {fine}회)" if fine else "")
  return f"완전 적용 · 검증 중 ({b.get('pass', 0)}/{STABLE_PASSES})"


def describe(bins: dict) -> list[dict]:
  """관리 화면용: 칸마다 사람이 읽을 수 있는 설명."""
  names = ["완만한", "보통", "조금 급한", "급한", "아주 급한"]
  out = []
  for key in sorted(bins):
    b = bins[key]
    side = "왼쪽" if key[0] == "L" else "오른쪽"
    ci, si = int(key[1]), int(key.split("s")[1])
    pct = round((min(max(1.0 + (b["ratio"] - 1.0) * min(b["n"] / FULL_COUNT, 1.0), SCALE_CLIP[0]), SCALE_CLIP[1])) * 100)
    out.append({"key": key, "label": f"{side} {names[min(ci, 4)]} 커브 · {'50km/h 이상' if si else '50km/h 미만'}",
                "percent": pct, "samples": b["n"], "fine": b.get("fine", 0), "passes": b.get("pass", 0),
                "pass_since": b.get("pass_since", 0), "status": status(b)})
  return out
