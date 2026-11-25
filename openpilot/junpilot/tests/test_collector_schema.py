from openpilot.cereal import log
from openpilot.junpilot import collector


def test_snapshot_from_real_schema():
  """실제 메시지 구조로 snapshot_from이 돌아야 함 (예전에 없는 필드(leadOne.status)를 읽다가 수집이 통째로 멈춰
  주행 리포트·P/N 판단이 안 됐음)."""
  sm = {}
  for w in ('carState', 'selfdriveState', 'radarState', 'carControl', 'modelV2', 'deviceState'):
    ev = log.Event.new_message()
    ev.init(w)
    sm[w] = getattr(ev, w)
  s = collector.snapshot_from(sm, {})
  assert collector.state_json(s)["lead"] is False
