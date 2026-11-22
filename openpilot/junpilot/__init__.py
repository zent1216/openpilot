"""준파일럿(junpilot) 전용 설정.

추가 기능은 가능한 한 이 폴더에 모아 공식 코드 변경을 최소화한다.
"""
import os

from openpilot.common.hardware import PC

BRAND_NAME = "준파일럿"

# 기본값: 콤마4 장치에서는 콤마 서버와의 통신(업로드, athena, 등록)을 모두 차단한다.
# 다시 켜려면 장치에서 JUNPILOT_ONLINE=1 환경변수를 설정한다.
OFFLINE = (not PC) and os.getenv("JUNPILOT_ONLINE") != "1"
