from openpilot.junpilot import store
from openpilot.junpilot.device import OFFICIAL_SETTINGS
from openpilot.junpilot.setting_help import help_for


def test_every_setting_has_help():
  """설정만 나열하지 말고, 항목마다 언제 어떻게 바꾸는지 설명이 있어야 함."""
  for k in list(store.JUNPILOT_SETTINGS) + list(OFFICIAL_SETTINGS):
    assert len(help_for(k)) > 10, k
