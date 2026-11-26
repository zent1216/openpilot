"""준파일럿: 스마트크루즈 자가 학습.

크루즈 중에 운전자가 직접 손댄 순간과 그때 상황을 기억했다가, 다음에 비슷한 상황이면 그쪽으로 맞춘다.

- 커브 감속: 준파일럿이 커브라서 속도를 줄였는데 운전자가 +를 누르거나 가속 페달을 밟으면 '덜 줄여도 된다',
  커브에서 운전자가 -를 누르면 '더 줄여야 한다'. 커브 굽기 칸마다 허용 횡가속도를 조금씩 바꾼다.
- 단속 구간 여유: 단속 제한으로 맞춰 둔 속도에서 운전자가 +/-를 누르면 그 방향으로 여유를 1km/h씩 옮긴다.
- 차간거리: 운전자가 차간 버튼으로 고른 단계를 (속도대, 앞차 유무)별로 기억해 자동 차간거리에 쓴다.

모두 정해 둔 범위 안에서만 바뀌고, 관리 페이지에서 보고 초기화할 수 있다.

완전 적용(커브·단속 3번, 차간 2번) 뒤에는: 손대지 않고 지나가면 '검증 통과'로 세고, 그래도 손대면 절반 폭으로
'세밀 보정'한다.
"""
import json
import os

import numpy as np

from openpilot.junpilot import store

FILE = "cruise_learn.json"
CURVE_EDGES = (0.003, 0.006, 0.012, 0.025)   # 1/m, 앞 경로에서 가장 급한 곡률
CURVE_STEP = 0.15                             # m/s^2, 한 번 배울 때 바꾸는 허용 횡가속도
CURVE_CLIP = (-0.6, 0.6)
MARGIN_STEP = 1.0                             # km/h
MARGIN_CLIP = (-5.0, 5.0)
GAP_SPEED_EDGES_KPH = (30.0, 60.0, 90.0)
GAP_SETTLE = 1.5                              # 초, 차간 버튼을 누른 뒤 계기판 단계가 바뀌길 기다림
COOLDOWN = 3.0                                # 초, 같은 종류를 연달아 배우지 않음
GAS_HOLD = 1.0                                # 초, 커브 감속 중 가속 페달을 이만큼 밟으면 '덜 줄여라'
SAVE_EVERY = 30.0
FULL_CURVE = 3        # 이만큼 배우면 커브 감속 완전 적용, 이후는 세밀 보정
FULL_MARGIN = 3
FULL_GAP = 2
PASS_HOLD = 2.0       # 초, 커브 감속을 손대지 않고 이만큼 지나가면 검증 통과
STABLE_PASSES = 5
GAP_PASS_HOLD = 30.0  # 초, 차간 상황이 이만큼 이어지는 동안 버튼을 안 누르면 통과


def curve_bucket(k_max: float) -> int | None:
  if k_max < CURVE_EDGES[0]:
    return None
  return int(np.searchsorted(CURVE_EDGES, k_max, side="right")) - 1


def gap_key(v_ego: float, has_lead: bool) -> str:
  return f"g{int(np.searchsorted(GAP_SPEED_EDGES_KPH, v_ego * 3.6, side='right'))}{'L' if has_lead else 'N'}"


def max_curvature(velocity, yaw_rate) -> float:
  v = np.maximum(np.asarray(velocity, dtype=float), 1.0)
  if len(v) == 0 or len(v) != len(yaw_rate):
    return 0.0
  return float(np.max(np.abs(np.asarray(yaw_rate, dtype=float)) / v))


class CruiseLearner:
  def __init__(self, path: str | None = None):
    self.path = path or os.path.join(store.data_dir(), FILE)
    d = self._load()
    self.curve: dict[str, float] = d.get("curve", {})        # 칸 → 허용 횡가속도 보정
    self.curve_n: dict[str, int] = d.get("curve_n", {})
    self.margin: float = float(d.get("margin", 0.0))          # 단속 구간 여유 보정(km/h)
    self.margin_n: int = int(d.get("margin_n", 0))
    self.gap: dict[str, list] = d.get("gap", {})               # 상황 → [단계, 횟수, 세밀 보정 횟수]
    self.fine: dict[str, int] = d.get("fine", {})               # 항목("curve2", "margin", "gap:g1L") → 세밀 보정 횟수
    self.passes: dict[str, int] = d.get("passes", {})           # 항목 → 검증 통과 횟수
    self.since: dict[str, int] = d.get("since", {})             # 항목 → 마지막 세밀 보정 뒤 통과 횟수
    # 검증: 지금 지나는 구간 (종류별로 따로) → (항목, 시작 시각, 손댔는지)
    self._eps: dict[str, tuple[str | None, float, bool]] = {}
    self._dirty = False
    self._saved_t = 0.0
    self._last: dict[str, float] = {}
    self._gas_t: float | None = None
    self._gas_done = False
    self._gap_pending: tuple[float, str] | None = None

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
      json.dump({"curve": self.curve, "curve_n": self.curve_n, "margin": self.margin, "margin_n": self.margin_n,
                 "gap": self.gap, "fine": self.fine, "passes": self.passes, "since": self.since}, f)
    os.replace(tmp, self.path)
    self._dirty = False

  def reset(self):
    self.curve, self.curve_n, self.margin, self.margin_n, self.gap = {}, {}, 0.0, 0, {}
    self.fine, self.passes, self.since = {}, {}, {}
    self._dirty = True
    self.save()

  def status(self, item: str, n: int, full: int) -> str:
    """진행 상태 문구."""
    if n < full:
      return f"{full - n}번 더 배우면 완전 적용"
    fine, since, passes = self.fine.get(item, 0), self.since.get(item, 0), self.passes.get(item, 0)
    if fine and since < STABLE_PASSES:
      return f"{fine}회 세밀 보정 중" + (f" · 보정 뒤 {since}번 통과" if since else "")
    if passes >= STABLE_PASSES:
      return f"안정 · 검증 {passes}번 통과" + (f" (세밀 보정 {fine}회)" if fine else "")
    return f"완전 적용 · 검증 중 ({passes}/{STABLE_PASSES})"

  # ---- 적용 ----
  def curve_lat_adj(self, k_max: float) -> float:
    b = curve_bucket(k_max)
    return self.curve.get(str(b), 0.0) if b is not None else 0.0

  def margin_adj(self) -> float:
    return self.margin

  def gap_for(self, v_ego: float, has_lead: bool) -> int | None:
    g = self.gap.get(gap_key(v_ego, has_lead))
    return int(round(g[0])) if g else None

  # ---- 학습 ----
  def _ok(self, kind: str, now: float) -> bool:
    if now - self._last.get(kind, -1e9) < COOLDOWN:
      return False
    self._last[kind] = now
    return True

  def _learn_curve(self, k_max: float, sign: float):
    b = curve_bucket(k_max)
    if b is None:
      return None
    key = str(b)
    fine = self.curve_n.get(key, 0) >= FULL_CURVE
    step = CURVE_STEP / 2 if fine else CURVE_STEP
    self.curve[key] = round(float(np.clip(self.curve.get(key, 0.0) + sign * step, *CURVE_CLIP)), 3)
    self.curve_n[key] = self.curve_n.get(key, 0) + 1
    if fine:
      self._mark_fine(f"curve{key}")
    self._dirty = True
    return f"curve{key}"

  def _mark_fine(self, item: str):
    self.fine[item] = self.fine.get(item, 0) + 1
    self.since[item] = 0

  def _mark_pass(self, item: str):
    self.passes[item] = self.passes.get(item, 0) + 1
    self.since[item] = self.since.get(item, 0) + 1
    self._dirty = True

  def _track(self, kind: str, now: float, item: str | None, touched: bool, hold: float):
    """구간(커브 감속·단속 구간·차간 상황)을 손대지 않고 hold초 넘게 지나가면, 완전 적용된 항목은 검증 통과."""
    key, t0, was = self._eps.get(kind, (None, 0.0, False))
    if item != key:
      if key is not None and not was and now - t0 >= hold and self._full(key):
        self._mark_pass(key)
      self._eps[kind] = (item, now, touched)
    elif touched:
      self._eps[kind] = (key, t0, True)

  def _full(self, item: str) -> bool:
    if item.startswith("curve"):
      return self.curve_n.get(item[5:], 0) >= FULL_CURVE
    if item == "margin":
      return self.margin_n >= FULL_MARGIN
    g = self.gap.get(item[4:])
    return bool(g) and g[1] >= FULL_GAP

  def update(self, now: float, *, cruise: bool, v_ego: float, k_max: float, curve_limited: bool, camera_active: bool,
             accel_pressed: bool, decel_pressed: bool, gas_pressed: bool, gap_pressed: bool, cur_gap: int,
             has_lead: bool) -> str | None:
    """크루즈 제어 주기마다 호출. 배운 게 있으면 무엇인지 돌려준다."""
    learned = None
    if cruise:
      if accel_pressed and curve_limited and self._ok("curve", now):
        learned = self._learn_curve(k_max, +1)
      elif decel_pressed and curve_bucket(k_max) is not None and not camera_active and self._ok("curve", now):
        learned = self._learn_curve(k_max, -1)
      elif (accel_pressed or decel_pressed) and camera_active and not curve_limited and self._ok("margin", now):
        fine = self.margin_n >= FULL_MARGIN
        step = MARGIN_STEP / 2 if fine else MARGIN_STEP
        self.margin = float(np.clip(self.margin + (step if accel_pressed else -step), *MARGIN_CLIP))
        self.margin_n += 1
        if fine:
          self._mark_fine("margin")
        self._dirty = True
        learned = "margin"

      # 커브 감속 중 가속 페달을 1초 넘게 밟으면 '덜 줄여도 된다' (커브 한 번에 한 번만)
      if gas_pressed and curve_limited:
        self._gas_t = self._gas_t if self._gas_t is not None else now
        if not self._gas_done and now - self._gas_t >= GAS_HOLD and self._ok("curve", now):
          learned = self._learn_curve(k_max, +1) or learned
          self._gas_done = True
      else:
        self._gas_t = None
        if not curve_limited:
          self._gas_done = False

      if gap_pressed:
        self._gap_pending = (now, gap_key(v_ego, has_lead))
      if self._gap_pending is not None and now - self._gap_pending[0] >= GAP_SETTLE:
        key = self._gap_pending[1]
        self._gap_pending = None
        if 1 <= cur_gap <= 4:
          old = self.gap.get(key)
          n = (old[1] if old else 0) + 1
          # 최근 선택을 더 믿되 한 번 실수로 확 바뀌지 않게 (처음은 그대로)
          val = float(cur_gap) if old is None else old[0] + 0.6 * (cur_gap - old[0])
          self.gap[key] = [round(val, 2), n]
          if old is not None and old[1] >= FULL_GAP and int(round(old[0])) != cur_gap:
            self._mark_fine(f"gap:{key}")
          self._dirty = True
          learned = f"gap:{key}"
      touched = accel_pressed or decel_pressed or gas_pressed
      b = curve_bucket(k_max) if curve_limited else None
      self._track("curve", now, f"curve{b}" if b is not None else None, touched, PASS_HOLD)
      self._track("margin", now, "margin" if camera_active and not curve_limited else None, accel_pressed or decel_pressed,
                  PASS_HOLD)
      self._track("gap", now, f"gap:{gap_key(v_ego, has_lead)}", gap_pressed, GAP_PASS_HOLD)
    else:
      self._gas_t, self._gap_pending = None, None
      self._eps = {}

    if learned is not None or (self._dirty and now - self._saved_t > SAVE_EVERY):
      self._saved_t = now
      try:
        self.save()
      except OSError:
        pass
    return learned


def describe(path: str | None = None) -> dict:
  lr = CruiseLearner(path)
  names = ["완만한", "보통", "급한", "아주 급한"]
  curve = []
  for k in sorted(lr.curve):
    adj = lr.curve[k]
    n = lr.curve_n.get(k, 0)
    curve.append({"label": f"{names[min(int(k), 3)]} 커브",
                  "value": "덜 줄임" if adj > 0 else "더 줄임" if adj < 0 else "그대로",
                  "amount": abs(adj), "samples": n, "status": lr.status(f"curve{k}", n, FULL_CURVE)})
  sp = ["30km/h 미만", "30~60km/h", "60~90km/h", "90km/h 이상"]
  gap = [{"label": f"{sp[int(k[1])]} · {'앞차 있음' if k[2] == 'L' else '앞차 없음'}", "gap": int(round(v[0])), "samples": v[1],
          "status": lr.status(f"gap:{k}", v[1], FULL_GAP)}
         for k, v in sorted(lr.gap.items())]
  return {"curve": curve, "margin": lr.margin, "margin_samples": lr.margin_n,
          "margin_status": lr.status("margin", lr.margin_n, FULL_MARGIN), "gap": gap,
          "fine_total": sum(lr.fine.values()), "pass_total": sum(lr.passes.values()),
          "empty": not (lr.curve or lr.gap or lr.margin_n)}

