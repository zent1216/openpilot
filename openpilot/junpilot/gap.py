"""준파일럿: 앞차와 속도에 따라 순정 크루즈 차간거리 단계를 자동으로 바꾼다 (OPKR 가변 차간거리 방식 참고).

- 앞차가 있고 느리게 갈 때(막히는 길)는 단계를 줄여 끼어들기를 줄이고 출발 반응을 빠르게 함
- 빨라지거나 앞차가 없으면 사용자가 고른 기본 단계로 돌아감
- 단계가 자주 바뀌지 않게, 같은 판단이 HOLD_TIME 동안 이어질 때만 바꿈
"""
CV_KPH = 3.6
SLOW_KPH = 40.0
MID_KPH = 70.0
HYST_KPH = 5.0
HOLD_TIME = 3.0
DEFAULT_GAP = 3


class AutoGap:
  def __init__(self):
    self.gap = 0
    self.pending = 0
    self.pending_t = 0.0

  def _want(self, v_ego: float, has_lead: bool, base: int) -> int:
    kph = v_ego * CV_KPH
    # 지금 단계 쪽으로 기준 속도를 조금 밀어 경계에서 왔다 갔다 하지 않게 함
    slow = SLOW_KPH + (HYST_KPH if self.gap and self.gap < base - 1 else -HYST_KPH if self.gap else 0)
    mid = MID_KPH + (HYST_KPH if self.gap and self.gap < base else -HYST_KPH if self.gap else 0)
    if not has_lead:
      return base
    if kph < slow:
      return max(1, base - 2)
    if kph < mid:
      return max(1, base - 1)
    return base

  def update(self, now: float, v_ego: float, has_lead: bool, base_gap: int, enabled: bool) -> int:
    """원하는 차간거리 단계(1~4)를 돌려준다."""
    base = base_gap if 1 <= base_gap <= 4 else DEFAULT_GAP
    if not enabled:
      self.gap, self.pending = base, 0
      return base
    want = self._want(v_ego, has_lead, base)
    if self.gap == 0:
      self.gap = want
    if want == self.gap:
      self.pending = 0
    elif want != self.pending:
      self.pending, self.pending_t = want, now
    elif now - self.pending_t >= HOLD_TIME:
      self.gap, self.pending = want, 0
    return self.gap
