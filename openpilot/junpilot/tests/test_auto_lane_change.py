from types import SimpleNamespace as NS

import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.junpilot import store
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LaneChangeState


def cs(left=False, right=False, v=25.0, bsm_l=False, bsm_r=False, pressed=False, torque=0.0):
  return NS(vEgo=v, leftBlinker=left, rightBlinker=right, leftBlindspot=bsm_l, rightBlindspot=bsm_r,
            steeringPressed=pressed, steeringTorque=torque)


@pytest.fixture(autouse=True)
def jpdir(tmp_path, monkeypatch):
  monkeypatch.setenv("JUNPILOT_DIR", str(tmp_path))


def run(dh, c, secs, prob=1.0):
  for _ in range(int(secs / DT_MDL)):
    dh.update(c, True, prob)
  return dh.lane_change_state


def test_off_by_default_needs_nudge():
  dh = DesireHelper(enable_bsm=True)
  assert run(dh, cs(left=True), 5) == LaneChangeState.preLaneChange
  assert run(dh, cs(left=True, pressed=True, torque=1.0), 0.2) == LaneChangeState.laneChangeStarting


def test_auto_after_delay():
  store.set_settings({"lane_change_mode": 3})
  dh = DesireHelper(enable_bsm=True)
  assert run(dh, cs(left=True), 1.5) == LaneChangeState.preLaneChange
  assert run(dh, cs(left=True), 0.8) == LaneChangeState.laneChangeStarting


def test_auto_waits_for_blindspot_and_needs_bsm():
  store.set_settings({"lane_change_mode": 2})
  dh = DesireHelper(enable_bsm=True)
  assert run(dh, cs(right=True, bsm_r=True), 5) == LaneChangeState.preLaneChange
  assert run(dh, cs(right=True), 0.5) == LaneChangeState.preLaneChange  # 비워진 뒤 다시 1초 기다림
  assert run(dh, cs(right=True), 0.7) == LaneChangeState.laneChangeStarting
  no_bsm = DesireHelper(enable_bsm=False)
  assert run(no_bsm, cs(right=True), 5) == LaneChangeState.preLaneChange


def test_auto_once_per_blinker_and_min_speed():
  store.set_settings({"lane_change_mode": 2})
  dh = DesireHelper(enable_bsm=True)
  run(dh, cs(left=True), 1.2)
  assert dh.lane_change_state == LaneChangeState.laneChangeStarting
  run(dh, cs(left=True), 1.0, prob=0.0)  # 변경 완료 후에도 깜빡이 유지
  assert run(dh, cs(left=True), 3) == LaneChangeState.preLaneChange  # 다시 자동으로 바꾸지 않음
  run(dh, cs(), 0.2)
  assert run(dh, cs(left=True), 1.2) == LaneChangeState.laneChangeStarting  # 깜빡이를 다시 켜면 가능
  slow = DesireHelper(enable_bsm=True)
  assert run(slow, cs(left=True, v=10.0), 3) == LaneChangeState.preLaneChange


def test_disabled_never_changes():
  store.set_settings({"lane_change_mode": 0})
  dh = DesireHelper(enable_bsm=True)
  assert run(dh, cs(left=True, pressed=True, torque=1.0), 3) == LaneChangeState.off


def test_old_setting_migrates():
  store.save("settings.json", {"auto_lane_change": 0})
  assert store.get_settings()["lane_change_mode"] == 1
  store.save("settings.json", {"auto_lane_change": 2})
  assert store.get_settings()["lane_change_mode"] == 3
