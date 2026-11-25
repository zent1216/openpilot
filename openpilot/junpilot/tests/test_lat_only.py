import sys
import types

# 장치 전용 라이브러리가 없는 PC에서도 이벤트 로직만 시험할 수 있게 Events를 가짜로 바꿈
class _Events:
  def __init__(self):
    self.names = []

  def add(self, name, static=False):
    self.names.append(name)


_fake = types.ModuleType("openpilot.selfdrive.selfdrived.events")
_fake.Events = _Events
sys.modules.setdefault("openpilot.selfdrive.selfdrived.events", _fake)

from opendbc.car import structs
from opendbc.car.hyundai.interface import CarInterface
from openpilot.cereal import log
from openpilot.selfdrive.car.car_events import CarEvents

EventName = log.OnroadEvent.EventName
BT = structs.CarState.ButtonEvent.Type


def _cp():
  return CarInterface.get_params("KIA_PV5", {b: {} for b in range(8)}, [], False, False, False)


def _cs(lkas=False, cruise=False):
  cs = structs.CarState()
  cs.cruiseState.available = True
  cs.cruiseState.enabled = cruise
  cs.gearShifter = structs.CarState.GearShifter.drive
  if lkas:
    cs.buttonEvents = [structs.CarState.ButtonEvent(type=BT.lkas, pressed=True)]
  return cs


class CC:
  def __init__(self, enabled):
    self.enabled = enabled


def names(ev):
  return set(ev.names)


def test_lfa_button_enables_and_keeps_without_cruise():
  ce = CarEvents(_cp())
  ev = ce.update(_cs(lkas=True), _cs(), CC(False))
  assert EventName.buttonEnable in names(ev)
  # 크루즈 없이 켜져 있어도 pcmDisable 없음
  for _ in range(300):
    ev = ce.update(_cs(), _cs(), CC(True))
    assert EventName.pcmDisable not in names(ev)
  # 다시 누르면 꺼짐
  ev = ce.update(_cs(lkas=True), _cs(), CC(True))
  assert EventName.buttonCancel in names(ev)
  ev = ce.update(_cs(), _cs(), CC(False))
  assert EventName.pcmDisable in names(ev)


def test_cruise_enable_then_cancel_keeps_steering():
  ce = CarEvents(_cp())
  ce.update(_cs(cruise=True), _cs(), CC(False))
  ev = ce.update(_cs(cruise=False), _cs(cruise=True), CC(True))
  assert EventName.pcmDisable not in names(ev)


def test_other_cars_unchanged():
  cp = CarInterface.get_params("KIA_EV6", {b: {} for b in range(8)}, [], False, False, False)
  ce = CarEvents(cp)
  ev = ce.update(_cs(lkas=True), _cs(), CC(False))
  assert EventName.buttonEnable not in names(ev)
