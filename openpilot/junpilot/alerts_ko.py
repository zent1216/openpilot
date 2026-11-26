"""준파일럿: 오파 주행 경고 문구 한글화.

경고 문구는 selfdrived(events.py)가 영어로 만들어 보내고, 화면(UI)이 그대로 그린다.
기록(로그)은 영어로 두고, 화면 언어가 한국어일 때 그리는 순간에만 바꾼다 (junpilot/ui/ko.py에서 호출).
화면이 경고를 소문자로 바꿔 그리기도 해서 대소문자는 무시한다. 없는 문구는 영어 그대로 둔다.
"""
import re

KO: dict[str, str] = {
  # 조작·주의
  "TAKE CONTROL": "직접 운전하세요",
  "TAKE CONTROL IMMEDIATELY": "즉시 직접 운전하세요",
  "Take Control": "직접 운전하세요",
  "take control": "직접 운전하세요",
  "DISENGAGE IMMEDIATELY": "즉시 해제하세요",
  "Pay Attention": "전방을 주시하세요",
  "Pay Attention to Engage": "전방을 주시해야 켤 수 있어요",
  "Driver Distracted": "운전자 주의 산만",
  "Too Distracted": "주의가 너무 산만해요",
  "Driver Unresponsive": "운전자 반응 없음",
  "Touch Steering Wheel": "핸들을 잡으세요",
  "Touch Steering Wheel: No Face Detected": "핸들을 잡으세요: 얼굴이 안 보여요",
  "Always keep hands on wheel and eyes on road": "항상 핸들을 잡고 전방을 보세요",
  "Be ready to take over at any time": "언제든 직접 운전할 준비를 하세요",
  "Resume Driving Manually": "직접 운전으로 돌아가세요",
  "openpilot will disengage": "오파가 곧 꺼져요",
  "openpilot Canceled": "오파 취소됨",
  "openpilot Unavailable": "오파 사용 불가",
  "openpilot failed to cancel cruise": "오파가 크루즈를 끄지 못했어요",
  "Ensure road ahead is clear": "앞이 비어 있는지 확인하세요",
  # 충돌·안전
  "BRAKE!": "브레이크!",
  "Risk of Collision": "충돌 위험",
  "AEB: Risk of Collision": "긴급제동: 충돌 위험",
  "Stock AEB: Risk of Collision": "순정 긴급제동: 충돌 위험",
  "Emergency Braking: Risk of Collision": "긴급제동: 충돌 위험",
  "Lane Departure Detected": "차선 이탈 감지",
  "Stock LKAS: Lane Departure Detected": "순정 차선유지: 차선 이탈 감지",
  "Car Detected in Blindspot": "사각지대에 차가 있어요",
  "Car in Blindspot": "사각지대에 차 있음",
  # 차선 변경
  "Changing Lanes": "차선 변경 중",
  "Confirm Lane Change": "차선 변경 확인",
  "Steer Left": "왼쪽으로 핸들을 미세요",
  "Steer Right": "오른쪽으로 핸들을 미세요",
  "Steer Left to Start Lane Change Once Safe": "안전하면 왼쪽으로 핸들을 밀어 차선을 바꾸세요",
  "Steer Right to Start Lane Change Once Safe": "안전하면 오른쪽으로 핸들을 밀어 차선을 바꾸세요",
  # 조향
  "Steering Pressed": "핸들 조작 중",
  "Steering Temporarily Unavailable": "조향 일시 불가",
  "Steering Assist Temporarily Unavailable": "조향 보조 일시 불가",
  "Turn Exceeds Steering Limit": "조향 한계를 넘는 커브예요",
  "turn exceeds limit": "조향 한계 초과",
  "Vehicle Steering Time Limit": "차량 조향 시간 제한",
  "Steering misalignment detected": "핸들 정렬이 틀어졌어요",
  "Steer ratio mismatch": "조향비가 맞지 않아요",
  "Abnormal tire stiffness": "타이어 상태 이상",
  "Excessive Actuation": "제어량이 너무 커요",
  # 크루즈·주행 상태
  "Cruise Is Off": "크루즈가 꺼져 있어요",
  "Cruise Canceled": "크루즈 취소됨",
  "Cruise was on at startup": "시동 때 크루즈가 켜져 있었어요",
  "Cruise Fault: Restart the Car": "크루즈 고장: 시동을 다시 거세요",
  "Cruise Fault: Restart the car to engage": "크루즈 고장: 시동을 다시 걸어야 켤 수 있어요",
  "Adaptive Cruise Disabled": "스마트크루즈 꺼짐",
  "Enable Adaptive Cruise to Engage": "스마트크루즈를 켜야 켤 수 있어요",
  "Enable Main Switch to Engage": "크루즈 메인 버튼을 켜야 켤 수 있어요",
  "Switch to Traffic-Aware Cruise Control to engage": "스마트크루즈로 바꿔야 켤 수 있어요",
  "Press Set to Engage": "SET을 눌러 켜세요",
  "Press Resume": "RES를 누르세요",
  "Press Resume to Exit Standstill": "RES를 눌러 정차에서 출발하세요",
  "Press Resume to Exit Brake Hold": "RES를 눌러 오토홀드를 푸세요",
  "Pedal Pressed": "페달을 밟고 있어요",
  "Release Brake to Engage": "브레이크에서 발을 떼야 켤 수 있어요",
  "Cancel Pressed": "취소 버튼 눌림",
  "Gear not D": "기어가 D가 아니에요",
  "Reverse Gear": "후진 기어",
  "Reverse\nGear": "후진\n기어",
  "Reverse": "후진",
  "Door Open": "문이 열려 있어요",
  "Seatbelt Unlatched": "안전벨트를 매세요",
  "Parking Brake Engaged": "주차 브레이크가 걸려 있어요",
  "Electronic Stability Control Active": "차체 자세 제어 작동 중",
  "Electronic Stability Control Disabled": "차체 자세 제어 꺼짐",
  "Speed Too High": "속도가 너무 빨라요",
  "Speed too low": "속도가 너무 느려요",
  "Slow down to engage": "속도를 줄여야 켤 수 있어요",
  "Model uncertain at this speed": "이 속도에서는 판단이 불확실해요",
  "LKAS Fault: Restart the Car": "차선유지 고장: 시동을 다시 거세요",
  "LKAS Fault: Restart the car to engage": "차선유지 고장: 시동을 다시 걸어야 켤 수 있어요",
  "Disable your car's stock LKAS to engage": "순정 차선유지를 꺼야 켤 수 있어요",
  "Enable your car's LKAS to engage": "순정 차선유지를 켜야 켤 수 있어요",
  "Toggle stock LKAS on or off to engage": "순정 차선유지를 껐다 켜야 켤 수 있어요",
  "Invalid LKAS setting": "차선유지 설정이 올바르지 않아요",
  # 보정
  "Calibrating": "보정 중",
  "Calibration in Progress": "보정 중",
  "Calibration Incomplete": "보정 안 끝남",
  "Calibration Invalid": "보정 오류",
  "Calibration Invalid: Remount Device & Recalibrate": "보정 오류: 기기를 다시 달고 보정하세요",
  "Drive to Calibrate": "주행하면 보정돼요",
  "Remount Detected: Recalibrating": "기기 위치 변경 감지: 다시 보정 중",
  "Device Remount Detected: Recalibrating": "기기 위치 변경 감지: 다시 보정 중",
  "Vehicle Sensors Calibrating": "차량 센서 보정 중",
  # 시스템
  "System Initializing": "시스템 준비 중",
  "System Lagging": "시스템 지연",
  "System Overheated": "시스템 과열",
  "System Unresponsive": "시스템 응답 없음",
  "Reboot Device": "기기를 재부팅하세요",
  "Reboot your Device": "기기를 재부팅하세요",
  "Car Not Ready": "차량 준비 안 됨",
  "Car Unrecognized": "차량을 인식하지 못했어요",
  "Unknown Vehicle Variant": "알 수 없는 차량 사양",
  "Dashcam Mode": "블랙박스 모드",
  "Dashcam mode": "블랙박스 모드",
  "Dashcam mode for unsupported car": "지원 안 되는 차량이라 블랙박스 모드예요",
  "Controls Mismatch": "제어 불일치",
  "CAN Bus Disconnected": "CAN 연결 끊김",
  "CAN Bus Disconnected: Check Connections": "CAN 연결 끊김: 연결을 확인하세요",
  "CAN Bus Disconnected: Likely Faulty Cable": "CAN 연결 끊김: 케이블 불량 같아요",
  "Harness Relay Malfunction": "하네스 릴레이 고장",
  "Camera Malfunction": "카메라 고장",
  "Camera Malfunction: Reboot Your Device": "카메라 고장: 기기를 재부팅하세요",
  "Camera Frame Rate Low": "카메라 프레임 낮음",
  "Camera Frame Rate Low: Reboot Your Device": "카메라 프레임 낮음: 기기를 재부팅하세요",
  "Fan Malfunction": "팬 고장",
  "Low Memory": "메모리 부족",
  "Low Memory: Reboot Your Device": "메모리 부족: 기기를 재부팅하세요",
  "Out of Storage": "저장 공간 부족",
  "Process Not Running": "프로그램이 실행되지 않음",
  "Communication Issue Between Processes": "프로그램 간 통신 문제",
  "Low Communication Rate Between Processes": "프로그램 간 통신 느림",
  "Selfdrive Process Lagging: Reboot Your Device": "주행 프로그램 지연: 기기를 재부팅하세요",
  "Driving Model Lagging": "주행 모델 지연",
  "Sensor Data Invalid": "센서 데이터 오류",
  "Vehicle Sensors Invalid": "차량 센서 오류",
  "Posenet Speed Invalid": "속도 추정 오류",
  "Radar Error: Restart the Car": "레이더 오류: 시동을 다시 거세요",
  "Radar Temporarily Unavailable": "레이더 일시 불가",
  "locationd Temporary Error": "위치 계산 일시 오류",
  "paramsd Temporary Error": "차량 학습 일시 오류",
  "Security Key Not Available": "보안 키 없음",
  "Contact comma.ai/support": "comma.ai/support에 문의하세요",
  "Big Model Loading": "큰 모델 불러오는 중",
  "Big Model Failed": "큰 모델 실패",
  "Restart the car to retry,\nsmall model is still available": "시동을 다시 걸면 재시도해요,\n작은 모델은 계속 써요",
  "Bookmark Saved": "북마크 저장됨",
  "Joystick Mode": "조이스틱 모드",
  "Lateral Maneuver Mode": "조향 시험 모드",
  "Longitudinal Maneuver Mode": "가감속 시험 모드",
  "WARNING: This branch is not tested": "주의: 시험되지 않은 버전이에요",
  "Recording": "기록 중",
  "pair to connect\nto view": "연결하려면\n페어링하세요",
}

# 숫자가 들어가는 문구
PATTERNS: list[tuple[re.Pattern, str]] = [
  (re.compile(r"^Calibrating: (\d+)%$", re.I), r"보정 중: \1%"),
  (re.compile(r"^Calibration in Progress: (\d+)%$", re.I), r"보정 중: \1%"),
  (re.compile(r"^Drive Above (.+)$"), r"\1 이상으로 달리세요"),
  (re.compile(r"^Drive above (.+) to engage$"), r"\1 이상이어야 켤 수 있어요"),
  (re.compile(r"^Steer Assist Unavailable Below (.+)$"), r"\1 아래에서는 조향 보조를 못 해요"),
  (re.compile(r"^(\d+) minutes? Left$"), r"\1분 남음"),
  (re.compile(r"^(\d+)% full$"), r"\1% 찼어요"),
  (re.compile(r"^(\d+)% used$"), r"\1% 사용 중"),
  (re.compile(r"^([\d.]+)% frames dropped$"), r"프레임 \1% 누락"),
  (re.compile(r"^Driving Personality: (.+)$"), r"주행 성향: \1"),
  (re.compile(r"^Remount Device \((.+)\)$"), r"기기를 다시 다세요 (\1)"),
  (re.compile(r"^Angle offset too high \((.+)\)$"), r"각도 오차가 커요 (\1)"),
  (re.compile(r"^Check tires, pressure, or alignment \((.+)\)$"), r"타이어·공기압·얼라인먼트를 확인하세요 (\1)"),
  (re.compile(r"^Steering rack geometry may be off \((.+)\)$"), r"조향 장치 정렬이 틀어졌을 수 있어요 (\1)"),
]


def translate(text: str) -> str:
  if not text:
    return text
  ko = KO.get(text) or KO.get(text.strip())
  if ko is not None:
    return ko
  for pat, rep in PATTERNS:
    if pat.match(text):
      return pat.sub(rep, text)
  low = text.lower()
  for pat, rep in PATTERNS:
    if re.match(pat.pattern, low, re.I):
      return re.sub(pat.pattern, rep, low, flags=re.I)
  # "TAKE CONTROL"처럼 대문자로만 오는 경우
  return _KO_UPPER.get(text.upper(), text)


_KO_UPPER = {k.upper(): v for k, v in KO.items()}
