import os

os.environ.setdefault("RAYLIB_BACKEND", "headless")
from openpilot.junpilot.ui import ko
from openpilot.system.ui.lib.multilang import multilang


def test_exact_patterns_and_passthrough():
  assert ko.translate("enable openpilot") == "오픈파일럿 사용"
  assert ko.translate("Drive above 30 km/h to engage") == "켜려면 30 km/h 이상으로 주행하세요"
  assert ko.translate("5 minutes ago") == "5분 전"
  assert ko.translate("  Back  ") == "  뒤로  "
  assert ko.translate("97") == "97" and ko.translate("") == ""
  assert ko.translate("이미 한글") == "이미 한글"
  assert ko.translate("no translation here xyz") == "no translation here xyz"
  assert ko.translate("• It may damage your device and/or vehicle.").startswith("• ")


def test_official_translation_wins():
  assert ko.translate("Back", {"Back": "이전"}) == "이전"


def test_multilang_hook_only_for_korean():
  old = multilang._language
  try:
    multilang._language = "en"
    assert multilang.auto_tr("Calibrating") == "Calibrating"
    multilang._language = "ko"
    assert multilang.auto_tr("Calibrating") == "보정 중"
  finally:
    multilang._language = old


def test_font_has_every_translated_character():
  from fontTools.ttLib import TTFont
  from openpilot.common.basedir import BASEDIR
  cmap = TTFont(os.path.join(BASEDIR, "openpilot/junpilot/ui/fonts/NotoSansKR-junpilot.otf")).getBestCmap()
  missing = sorted(c for c in ko.all_chars() if c != "\n" and ord(c) not in cmap)
  assert not missing, missing


def test_home_screen():
  assert ko.translate("openpilot") == "준파일럿"
  assert ko.translate(" Nov 24") == " 11월 24일"
  assert ko.translate("Jan 5, 2027") == "2027년 1월 5일"
  assert ko.translate("0.11.4") == "0.11.4"
