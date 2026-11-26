import re

from openpilot.junpilot.alerts_ko import KO, translate


def test_translate():
  assert translate("TAKE CONTROL IMMEDIATELY") == "즉시 직접 운전하세요"
  assert translate("take control") == "직접 운전하세요"
  assert translate("Calibrating: 45%") == "보정 중: 45%"
  assert translate("Steer Assist Unavailable Below 30 km/h") == "30 km/h 아래에서는 조향 보조를 못 해요"
  assert translate("") == "" and translate("Something New") == "Something New"


def test_covers_fixed_event_texts():
  """events.py의 고정 문구가 빠짐없이 한글로 있어야 함 (새 경고가 생기면 여기서 걸림)."""
  import os
  src = open(os.path.join(os.path.dirname(__file__), "../../selfdrive/selfdrived/events.py")).read()
  texts = set(re.findall(r'Alert\(\s*"([^"{}]+)"', src)) | set(re.findall(r'Alert\(\s*"[^"]*",\s*"([^"{}]+)"', src))
  texts |= set(re.findall(r'(?:NoEntryAlert|SoftDisableAlert|ImmediateDisableAlert|EngagementAlert|StartupAlert)\(\s*"([^"{}]+)"', src))
  texts = {t.replace("\\n", "\n") for t in texts}
  missing = sorted(t for t in texts if translate(t) == t and re.search("[A-Za-z]", t) and t not in ("REPLAY",))
  assert not missing, missing
  assert len(KO) > 100


def test_ui_draw_translation_handles_lowercase_alerts():
  from openpilot.junpilot.ui.ko import translate as ui_tr
  assert ui_tr("take control immediately") == "즉시 직접 운전하세요"
  assert ui_tr("steering temporarily unavailable") == "조향 일시 불가"
  assert ui_tr("calibrating:\n45%") in ("calibrating:\n45%", "보정 중:\n45%")
