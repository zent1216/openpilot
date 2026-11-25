from openpilot.junpilot import ready
from openpilot.junpilot.ready import ReadyGate, ready_from_frame


def test_bit_from_pv5_frame():
  assert ready_from_frame(bytes([0, 0, 0, 0x10] + [0] * 28)) is True
  assert ready_from_frame(bytes([0, 0, 0, 0x00] + [0] * 28)) is False
  assert ready_from_frame(b"\x00") is None


def test_gate(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))
  t = [0.0]
  g = ReadyGate(path=str(tmp_path / "r.json"), clock=lambda: t[0])
  assert g.allow_onroad(False, ready=None)       # 신호 없으면 막지 않음
  assert not g.allow_onroad(False, ready=False)  # 키온 → 정차
  assert g.allow_onroad(False, ready=True)       # READY → 주행
  # 주행 중 READY가 꺼져도 10초는 유지
  assert g.allow_onroad(True, ready=False)
  t[0] += 5
  assert g.allow_onroad(True, ready=False)
  t[0] += 6
  assert not g.allow_onroad(True, ready=False)
  from openpilot.junpilot import store
  store.set_settings({"ready_only": False})
  t[0] += 3
  assert g.allow_onroad(False, ready=False)


def test_state_file(tmp_path):
  p = str(tmp_path / "r.json")
  ready.write_state(False, p)
  g = ReadyGate(path=p)
  g.enabled = True
  g._last_cfg = 1e18
  assert g.allow_onroad(False) is False
