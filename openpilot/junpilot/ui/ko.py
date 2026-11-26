# ruff: noqa: E501
"""준파일럿 한국어 화면 번역.

공식 콤마4(mici) 화면은 대부분 번역 처리(tr)가 안 돼 있어서, 그려지는 글자를 통째로 바꾼다.
- EXACT: 화면에 그려지는 문장과 정확히 같으면 바꿈
- PATTERNS: 숫자 등이 들어간 문장은 정규식으로 바꿈
공식 번역(app_ko.po)이 있으면 그쪽이 우선이다.
"""
import re

EXACT: dict[str, str] = {
  # ---------- 첫 화면 ----------
  "openpilot": "준파일럿", "release": "정식",

  # ---------- 공통 버튼/단어 ----------
  "Back": "뒤로", "back": "뒤로", "Cancel": "취소", "cancel": "취소", "Save": "저장", "Select": "선택", "Delete": "삭제",
  "Exit": "나가기", "Forget": "삭제", "Reboot": "재부팅", "reboot": "재부팅", "Update": "업데이트", "Setup": "설정",
  "Advanced": "고급", "Network": "네트워크", "network": "네트워크", "device": "장치", "software": "소프트웨어",
  "developer": "개발자", "driving": "주행", "connect": "커넥트", "connected": "연결됨", "next": "다음", "edit": "편집",
  "enable": "켜기", "dismiss": "닫기", "yes": "예", "no": "아니요", "reset": "초기화", "restart": "다시 시작",
  "start": "시작", "starting": "시작하는 중", "uninstall": "제거", "switch": "전환", "pair": "페어링", "paired": "페어링됨",
  "prime": "프라임", "firehose": "파이어호스", "tethering": "핫스팟", "metered": "데이터 절약", "unmetered": "무제한",
  "default": "기본", "hidden": "숨김", "loading": "불러오는 중", "downloading": "내려받는 중", "warning": "경고",
  "unsupported": "지원 안 됨", "version": "버전", "nickname": "별명", "aggressive": "공격적", "standard": "표준",
  "relaxed": "여유", "wi-fi": "와이파이", "Wi-Fi Manager": "와이파이 관리", "Ethernet": "이더넷", "Hotspot": "핫스팟",
  "Offline": "오프라인", "None": "없음", "N/A": "없음", "Route": "경로", "Reverse": "후진", "Reverse\nGear": "후진\n기어",
  "Reverse Gear": "후진 기어", "Text Viewer": "텍스트 보기", "IP Address": "IP 주소", "Hidden Network": "숨겨진 네트워크",
  "Security Key Not Available": "보안 키를 쓸 수 없어요", "Wrong password": "비밀번호가 틀렸어요", "wrong password": "비밀번호가 틀렸어요",
  "CONNECTING...": "연결하는 중...", "FORGETTING...": "삭제하는 중...", "Scanning Wi-Fi networks...": "와이파이를 찾는 중이에요...",
  "please wait...": "잠시만 기다려 주세요...", "not connected": "연결 안 됨", "not in range": "범위 밖", "not set": "설정 안 됨",
  "obtaining IP...": "IP 받는 중...", "searching for networks": "네트워크를 찾는 중", "no sim": "유심 없음",

  # ---------- 홈 / 알림 ----------
  "check alerts": "알림 확인", "no alerts": "알림 없음", "openpilot starting": "오픈파일럿 시작 중",
  "system booting": "시스템 시작 중", "start the car": "시동을 걸어 주세요", "to use openpilot": "오픈파일럿을 쓰려면",
  "camera starting": "카메라 시작 중", "Waiting for route": "경로를 기다리는 중",
  "up to date": "최신 버전", "update required": "업데이트 필요", "update failed": "업데이트 실패",
  "failed to update": "업데이트 실패", "download update": "업데이트 받기", "check for update": "업데이트 확인",
  "download failed": "내려받기 실패", "install now": "지금 설치", "System Update": "시스템 업데이트",
  "updater failed\nto respond": "업데이터가\n응답하지 않아요", "reboot to try again": "재부팅해서 다시 시도해 주세요",
  "Please connect to Wi-Fi to update.": "업데이트하려면 와이파이에 연결해 주세요.",
  "the download size\nis approximately 1 GB": "내려받기 크기는\n약 1GB예요",
  "this may take up to\na minute...": "최대 1분 정도\n걸릴 수 있어요...",
  "waiting for\ninternet...": "인터넷을\n기다리는 중...",
  "Bookmark Saved": "북마크 저장됨",

  # ---------- 설정: 주행 ----------
  "enable openpilot": "오픈파일럿 사용",
  "Enable to use openpilot driver assistance.\nDisable to use your car's stock driver assistance.": "켜면 오픈파일럿 주행 보조를 써요.\n끄면 차량 순정 주행 보조를 써요.",
  "driving personality": "주행 성향",
  "Standard is recommended.\nAggressive follows closer, with firmer gas and braking.\nRelaxed leaves more space.\nUse the steering wheel distance button on supported cars.": "표준을 추천해요.\n공격적은 더 가깝게 따라가고 가감속이 강해요.\n여유는 차간거리를 더 둬요.\n지원 차량은 핸들의 차간거리 버튼으로도 바꿀 수 있어요.",
  "lane departure warnings": "차선 이탈 경고",
  "Warn when you drift across a detected lane line.\nOnly above 31 mph (50 km/h), with no turn signal.": "인식된 차선을 넘으면 경고해요.\n50km/h 이상에서 깜빡이를 켜지 않았을 때만 동작해요.",
  "always-on driver monitor": "운전자 감시 항상 켜기",
  "Monitor the driver even when openpilot is not engaged.": "오픈파일럿을 쓰지 않을 때도 운전자를 감시해요.",
  "use metric units": "km/h 단위 사용",
  "record & upload mic audio": "마이크 소리 녹음",
  "Record microphone audio while driving.\nAudio is included in dashcam videos in comma connect.": "주행 중 마이크 소리를 녹음해요.\n블랙박스 영상에 소리가 함께 저장돼요.",
  "record & upload cabin camera": "실내 카메라 녹화",
  "Upload cabin camera data to help improve driver monitoring.": "운전자 감시 개선을 위해 실내 카메라 영상을 기록해요.",
  "initial max speed": "시작 최고 속도",
  "Max speed when engaging openpilot.\nIf you are already driving faster, your current speed is used.\nResume restores the previous max speed.": "오픈파일럿을 켤 때의 최고 속도예요.\n이미 더 빠르게 달리고 있으면 현재 속도를 써요.\n재개 버튼을 누르면 이전 최고 속도로 돌아가요.",
  "alpha longitudinal": "알파 가감속 제어", "enable alpha\nlongitudinal": "알파 가감속\n제어 켜기", "enabling alpha longitudinal": "알파 가감속 제어 켜는 중",
  "Use alpha openpilot longitudinal control instead of stock ACC. This may disable Automatic Emergency Braking (AEB).": "순정 크루즈 대신 오픈파일럿 알파 가감속 제어를 써요. 긴급제동(AEB)이 꺼질 수 있어요.",
  "WARNING: alpha longitudinal control may disable Automatic Emergency Braking (AEB)": "경고: 알파 가감속 제어를 켜면 긴급제동(AEB)이 꺼질 수 있어요",
  "Enabling this will switch to openpilot longitudinal control.": "켜면 오픈파일럿이 가감속을 직접 제어해요.",
  "On this car, openpilot defaults to the stock system's built-in ACC.": "이 차에서는 기본으로 순정 스마트크루즈를 써요.",
  "navigation (alpha)": "내비게이션 (알파)",
  "Turn-by-turn navigation with a route map. Set a destination from comma connect.": "경로 지도와 함께 길 안내를 해요. 목적지는 콤마 커넥트에서 정해요.",

  # ---------- 설정: 장치 ----------
  "device ID": "장치 ID", "factory reset": "공장 초기화", "reset calibration": "보정 초기화", "power off": "전원 끄기",
  "regulatory info": "인증 정보", "review\ntraining guide": "사용 안내\n다시 보기", "driver\ncamera preview": "운전자\n카메라 미리보기",
  "Preview the cabin camera to check driver monitoring visibility. The vehicle must be off.": "실내 카메라로 운전자 감시가 잘 보이는지 확인해요. 시동이 꺼져 있어야 해요.",
  "Mount the device within 4° left or right and 5° up or 9° down. openpilot calibrates continuously; resetting is rarely needed. Resetting clears learned calibration.": "장치를 좌우 4°, 위 5°, 아래 9° 안으로 달아 주세요. 오픈파일럿은 계속 보정하므로 초기화는 거의 필요 없어요. 초기화하면 학습한 보정값이 지워져요.",
  "Resetting erases all user content & data.": "초기화하면 모든 사용자 데이터가 지워져요.",
  "reset &\nerase": "초기화\n& 삭제", "resetting erases\nall user content & data": "초기화하면\n모든 데이터가 지워져요",
  "Remove openpilot from this device.": "이 장치에서 오픈파일럿을 지워요.", "uninstall openpilot": "오픈파일럿 제거",
  "slide to\nuninstall": "밀어서\n제거", "decline &\nuninstall": "거절하고\n제거",
  "Reboot your Device": "장치를 재부팅해 주세요", "reboot\ndevice": "장치\n재부팅",
  "resetting device": "장치 초기화 중", "reset failed": "초기화 실패", "System Reset": "시스템 초기화",
  "reset triggered by\ntapping the screen": "화면을 눌러서\n초기화가 시작됐어요",
  "user data partition\ncould not be mounted": "사용자 데이터 영역을\n불러오지 못했어요",
  "For a deeper reset, go to\nhttps://flash.comma.ai": "완전히 초기화하려면\nhttps://flash.comma.ai 로 가세요",
  "how to restore to a\nfactory state later": "나중에 공장 상태로\n되돌리는 방법",

  # ---------- 설정: 소프트웨어 ----------
  "target branch": "대상 브랜치", "Select the software branch to download on the next update check.": "다음 업데이트 확인 때 받을 소프트웨어 브랜치를 골라요.",
  "WARNING: This branch is not tested": "경고: 테스트되지 않은 브랜치예요",
  "Failed to get available branches. Ensure you're connected to the internet and try again.": "브랜치 목록을 받지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요.",
  "Ensure you're connected to the internet and try again.": "인터넷 연결을 확인하고 다시 시도해 주세요.",
  "choose software": "소프트웨어 선택", "install openpilot": "오픈파일럿 설치", "custom software URL...": "사용자 지정 소프트웨어 주소...",
  "slide to install\nopenpilot": "밀어서\n오픈파일럿 설치", "slide to install\ncustom software": "밀어서\n사용자 지정 소프트웨어 설치",
  "caution: installing\n3rd party software": "주의: 외부 소프트웨어\n설치", "download\n& install": "내려받고\n설치",
  "• It has not been tested by comma.": "• 콤마가 테스트하지 않았어요.", "• It may damage your device and/or vehicle.": "• 장치나 차량이 손상될 수 있어요.",
  "• It may not comply with safety standards.": "• 안전 기준을 지키지 않을 수 있어요.",
  "No custom software found at this URL: ": "이 주소에서 소프트웨어를 찾지 못했어요: ", "Invalid URL: ": "잘못된 주소예요: ",
  "Incompatible openpilot version.": "호환되지 않는 오픈파일럿 버전이에요.",

  # ---------- 설정: 개발자 ----------
  "enable ADB": "ADB 켜기", "Use Android Debug Bridge (ADB) over USB or the network.": "USB나 네트워크로 ADB를 써요.",
  "enable SSH": "SSH 켜기", "Access the device remotely using your SSH keys.": "SSH 키로 장치에 원격 접속해요.",
  "ssh keys": "SSH 키", "enter GitHub username...": "깃허브 사용자 이름 입력...",
  "Grant SSH access to all public keys in your GitHub settings. Only enter your own username.": "깃허브에 등록된 공개 키로 SSH 접속을 허용해요. 본인 이름만 입력하세요.",
  "Please connect to Wi-Fi to fetch your key.": "키를 받으려면 와이파이에 연결해 주세요.",
  "joystick debug\nmode": "조이스틱\n디버그 모드", "Joystick Mode": "조이스틱 모드", "Control the car with a joystick for debugging.": "디버깅용으로 조이스틱으로 차를 조작해요.",
  "lateral maneuver mode": "조향 시험 모드", "Lateral Maneuver Mode": "조향 시험 모드", "Run lateral maneuvers for testing steering control.": "조향 제어 시험 동작을 해요.",
  "longitudinal maneuver mode": "가감속 시험 모드", "Longitudinal Maneuver Mode": "가감속 시험 모드", "Run longitudinal maneuvers for testing gas and brake control.": "가속·제동 제어 시험 동작을 해요.",
  "ui debug mode": "화면 디버그 모드", "Show touch locations and the UI frame rate.": "터치 위치와 화면 프레임 수를 보여 줘요.",

  # ---------- 설정: 네트워크 ----------
  "enable tethering": "핫스팟 켜기", "Enable Tethering": "핫스팟 켜기", "tethering password": "핫스팟 비밀번호", "Tethering Password": "핫스팟 비밀번호",
  "Enter new tethering password": "새 핫스팟 비밀번호 입력", "Share the device's internet connection through a Wi-Fi hotspot.": "장치의 인터넷을 와이파이 핫스팟으로 공유해요.",
  "enable roaming": "로밍 켜기", "Enable Roaming": "로밍 켜기", "Allow cellular data roaming.": "모바일 데이터 로밍을 허용해요.",
  "apn settings": "APN 설정", "APN Setting": "APN 설정", "enter APN...": "APN 입력...", "Enter APN": "APN 입력",
  "Set the access point name required by your cellular carrier. Leave blank for automatic configuration.": "통신사가 요구하는 APN을 입력해요. 비워 두면 자동으로 설정돼요.",
  "leave blank for automatic configuration": "비워 두면 자동으로 설정돼요",
  "cellular metered": "모바일 데이터 절약", "Cellular Metered": "모바일 데이터 절약",
  "Prevent large uploads over the cellular connection.": "모바일 데이터로 큰 파일을 올리지 않아요.",
  "Prevent large data uploads when on a metered cellular connection": "데이터 요금제 연결에서는 큰 파일을 올리지 않아요",
  "Wi-Fi Network Metered": "와이파이 데이터 절약", "Prevent large data uploads when on a metered Wi-Fi connection": "데이터 절약 와이파이에서는 큰 파일을 올리지 않아요",
  "Metered prevents large uploads on this Wi-Fi connection. Default uses the network's detected setting.": "데이터 절약을 켜면 이 와이파이에서 큰 파일을 올리지 않아요. 기본은 네트워크 설정을 따라요.",
  "network usage": "네트워크 사용", "Enter SSID": "네트워크 이름 입력", "Enter password": "비밀번호 입력", "enter password...": "비밀번호 입력...",
  "slide to forget": "밀어서 삭제", "slide to delete": "밀어서 삭제",
  "add profile": "프로필 추가", "installing profile": "프로필 설치 중", "enter a nickname...": "별명 입력...", "esim error": "eSIM 오류",
  "not an LPA code": "eSIM 코드가 아니에요", "scan QR code": "QR 코드 스캔", "hold QR code to camera": "QR 코드를 카메라에 대 주세요",
  "Failed to delete eSIM profile": "eSIM 프로필을 지우지 못했어요", "Failed to download eSIM profile": "eSIM 프로필을 받지 못했어요",
  "Failed to switch eSIM profile": "eSIM 프로필을 바꾸지 못했어요", "Failed to update eSIM profile nickname": "eSIM 별명을 바꾸지 못했어요",
  "QR Code Error": "QR 코드 오류",

  # ---------- 페어링 / 프라임 / 파이어호스 ----------
  "pair to connect": "커넥트와 페어링", "pair to connect\nto view": "보려면\n커넥트와 페어링", "pairing device": "장치 페어링 중",
  "Device must be registered with the comma.ai backend to pair.": "페어링하려면 장치가 comma.ai에 등록돼 있어야 해요.",
  "Please connect to Wi-Fi to complete initial pairing.": "처음 페어링을 하려면 와이파이에 연결해 주세요.",
  "scan QR code or visit connect.comma.ai": "QR 코드를 찍거나 connect.comma.ai 에 접속하세요",
  "connect lets you review recent driving footage and bookmark events.": "커넥트에서 최근 주행 영상과 북마크를 볼 수 있어요.",
  "swipe for QR code": "밀어서 QR 코드 보기", "manage prime": "프라임 관리", "prime lite": "프라임 라이트", "not subscribed": "구독 안 함",
  "upgrade to prime": "프라임 가입", "upgrade\nto prime": "프라임\n가입", "claim prime trial": "프라임 체험 받기", "claim\nprime trial": "프라임\n체험 받기",
  "try prime for\n30 days": "프라임\n30일 체험", "scan to claim trial": "스캔해서 체험 받기", "scan to manage\nprime status": "스캔해서\n프라임 관리",
  "scan to open\ndevice prime settings": "스캔해서\n프라임 설정 열기",
  "prime adds 24/7 LTE to device and 1 year of cloud storage in connect.": "프라임은 24시간 LTE와 1년 클라우드 저장을 제공해요.",
  "prime also includes commacare extended device warranty.": "프라임에는 장치 보증 연장도 포함돼요.",
  "prime lets you view live video and GPS location remotely in connect.": "프라임으로 실시간 영상과 위치를 원격으로 볼 수 있어요.",
  "firehose mode": "파이어호스 모드", "uploaded segments:": "올린 구간:",
  "Firehose Mode maximizes your training data uploads to improve openpilot.": "파이어호스 모드는 오픈파일럿 개선을 위한 학습 데이터를 최대한 올려요.",
  "Firehose Mode can also work while you're driving if connected to a hotspot or unlimited SIM card.": "핫스팟이나 무제한 유심에 연결돼 있으면 주행 중에도 동작해요.",
  "For maximum effectiveness, bring your device inside weekly.": "효과를 높이려면 일주일에 한 번 장치를 실내로 가져오세요.",
  "More data means bigger models, which means better driving.": "데이터가 많을수록 모델이 커지고 주행이 좋아져요.",
  "INACTIVE: connect to an unmetered network": "꺼짐: 무제한 네트워크에 연결해 주세요", "connect to an\nunmetered network": "무제한 네트워크에\n연결해 주세요",
  "cabin camera data": "실내 카메라 데이터",

  # ---------- 첫 설정 / 약관 ----------
  "what is openpilot?": "오픈파일럿이란?", "openpilot learns to drive by watching humans, like you, drive.": "오픈파일럿은 사람이 운전하는 모습을 보고 배워요.",
  "1. openpilot is a driver assistance system.": "1. 오픈파일럿은 운전 보조 시스템이에요.",
  "2. You must pay attention at all times.": "2. 항상 전방을 주시해야 해요.",
  "3. You must be ready to take over at any time.": "3. 언제든 직접 운전할 준비가 돼 있어야 해요.",
  "4. You are fully responsible for driving the car.": "4. 운전 책임은 전적으로 운전자에게 있어요.",
  "terms &\nconditions": "이용\n약관", "terms and\nconditions": "이용\n약관", "accept\nterms": "약관\n동의",
  "or go to https://comma.ai/terms": "또는 https://comma.ai/terms 에서 확인하세요",
  "You must accept the Terms & Conditions to use openpilot.": "오픈파일럿을 쓰려면 약관에 동의해야 해요.",
  "scroll to continue": "스크롤해서 계속", "scroll for details": "스크롤해서 자세히 보기", "finish setup": "설정 마치기",
  "connect to\ncontinue": "계속하려면\n연결하세요", "connect to\ninternet": "인터넷에\n연결하세요",
  "Connect it to a good USB-C adapter and Wi-Fi.": "좋은 USB-C 충전기와 와이파이에 연결해 주세요.",
  "do you want to share video data for training?": "학습용 영상 데이터를 공유할까요?", "allow data uploading": "데이터 올리기 허용",
  "no, don't upload": "아니요, 올리지 않을게요", "Sharing your data with comma helps improve openpilot for everyone.": "데이터를 공유하면 모두를 위한 오픈파일럿 개선에 도움이 돼요.",
  "driver monitoring\ncheck": "운전자 감시\n확인", "looking for driver": "운전자를 찾는 중", "make sure comma\nfour can see your face": "콤마4가 얼굴을\n볼 수 있게 해 주세요",
  "openpilot uses the cabin camera to check if the driver is distracted.": "오픈파일럿은 실내 카메라로 운전자가 한눈파는지 확인해요.",
  "Next, we'll check if comma four can detect the driver properly.": "다음으로 콤마4가 운전자를 잘 인식하는지 확인할게요.",
  "If it does not have a clear view of the driver, unplug and remount before continuing.": "운전자가 잘 보이지 않으면 장치를 다시 달고 계속하세요.",
  "Remount if your face is blocked, or driver monitoring has difficulty tracking your face.": "얼굴이 가려지거나 인식이 잘 안 되면 장치를 다시 달아 주세요.",
  "swipe down to go back": "아래로 밀어서 뒤로", "swipe down to go\nback and try again": "아래로 밀어서\n다시 시도",

  # ---------- 주행 화면 알림 ----------
  "TAKE CONTROL": "직접 운전하세요", "TAKE CONTROL IMMEDIATELY": "즉시 직접 운전하세요", "Take Control": "직접 운전하세요", "take control": "직접 운전하세요",
  "DISENGAGE IMMEDIATELY": "즉시 해제하세요", "BRAKE!": "브레이크!", "Resume Driving Manually": "직접 운전으로 돌아가세요",
  "openpilot will disengage": "오픈파일럿이 해제돼요", "openpilot Canceled": "오픈파일럿 취소됨", "openpilot Unavailable": "오픈파일럿 사용 불가",
  "openpilot can't start": "오픈파일럿을 시작할 수 없어요",
  "Pay Attention": "전방을 주시하세요", "Pay Attention to Engage": "켜려면 전방을 주시하세요", "Always keep hands on wheel and eyes on road": "항상 핸들을 잡고 전방을 보세요",
  "Be ready to take over at any time": "언제든 직접 운전할 준비를 하세요", "Ensure road ahead is clear": "앞이 비어 있는지 확인하세요",
  "Touch Steering Wheel": "핸들을 잡으세요", "Touch Wheel": "핸들을 잡으세요", "Touch Steering Wheel: No Face Detected": "핸들을 잡으세요: 얼굴이 안 보여요",
  "Driver Distracted": "운전자 한눈팔기", "Driver Unresponsive": "운전자 반응 없음", "Too Distracted": "한눈팔기가 너무 많아요",
  "Seatbelt Unlatched": "안전벨트를 매세요", "Door Open": "문이 열려 있어요", "Gear not D": "기어가 D가 아니에요",
  "Parking Brake Engaged": "주차 브레이크가 걸려 있어요", "Pedal Pressed": "페달을 밟았어요", "Release Brake to Engage": "켜려면 브레이크에서 발을 떼세요",
  "Steering Pressed": "핸들 조작 중", "Cancel Pressed": "취소 버튼 눌림", "Cruise Is Off": "크루즈가 꺼져 있어요", "Cruise Canceled": "크루즈 취소됨",
  "Cruise was on at startup": "시동 때 크루즈가 켜져 있었어요", "Adaptive Cruise Disabled": "스마트크루즈 꺼짐",
  "Enable Adaptive Cruise to Engage": "켜려면 스마트크루즈를 켜세요", "Enable Main Switch to Engage": "켜려면 크루즈 메인 스위치를 켜세요",
  "Press Set to Engage": "켜려면 SET을 누르세요", "Press Resume": "RES를 누르세요", "Press Resume to Exit Standstill": "출발하려면 RES를 누르세요",
  "Press Resume to Exit Brake Hold": "브레이크 홀드를 풀려면 RES를 누르세요", "Slow down to engage": "켜려면 속도를 줄이세요",
  "Speed Too High": "속도가 너무 빨라요", "Speed too low": "속도가 너무 느려요", "Model uncertain at this speed": "이 속도에서는 모델이 불확실해요",
  "Switch to Traffic-Aware Cruise Control to engage": "켜려면 스마트크루즈로 바꾸세요",
  "Changing Lanes": "차선 변경 중", "Confirm Lane Change": "차선 변경 확인", "Steer Left": "왼쪽으로 핸들", "Steer Right": "오른쪽으로 핸들",
  "Steer Left to Start Lane Change Once Safe": "안전하면 왼쪽으로 핸들을 돌려 차선을 바꾸세요",
  "Steer Right to Start Lane Change Once Safe": "안전하면 오른쪽으로 핸들을 돌려 차선을 바꾸세요",
  "Car Detected in Blindspot": "사각지대에 차가 있어요", "Car in Blindspot": "사각지대 차량",
  "Lane Departure Detected": "차선 이탈", "Stock LKAS: Lane Departure Detected": "순정 차로 유지: 차선 이탈",
  "Risk of Collision": "충돌 위험", "AEB: Risk of Collision": "긴급제동: 충돌 위험", "Stock AEB: Risk of Collision": "순정 긴급제동: 충돌 위험",
  "Emergency Braking: Risk of Collision": "긴급제동: 충돌 위험", "Braking (AEB).": "긴급제동 중.",
  "Turn Exceeds Steering Limit": "핸들 한계를 넘는 커브예요", "turn exceeds limit": "핸들 한계 초과", "Vehicle Steering Time Limit": "차량 조향 시간 제한",
  "Steering Temporarily Unavailable": "조향을 잠시 쓸 수 없어요", "Steering Assist Temporarily Unavailable": "조향 보조를 잠시 쓸 수 없어요",
  "Calibrating": "보정 중", "Calibration in Progress": "보정 중이에요", "Calibration Incomplete": "보정이 끝나지 않았어요", "Drive to Calibrate": "보정하려면 주행하세요",
  "Calibration Invalid": "보정 오류", "Calibration Invalid: Remount Device & Recalibrate": "보정 오류: 장치를 다시 달고 재보정하세요",
  "Recalibrating": "재보정 중", "Remount Detected: Recalibrating": "장치 위치 변경: 재보정 중", "Device Remount Detected: Recalibrating": "장치 위치 변경: 재보정 중",
  "Vehicle Sensors Calibrating": "차량 센서 보정 중", "Vehicle Sensors Invalid": "차량 센서 오류", "Sensor Data Invalid": "센서 데이터 오류",
  "System Initializing": "시스템 시작 중", "System Lagging": "시스템 지연", "System Overheated": "시스템 과열", "Low Memory": "메모리 부족",
  "Low Memory: Reboot Your Device": "메모리 부족: 장치를 재부팅하세요", "Out of Storage": "저장 공간 부족", "Fan Malfunction": "팬 고장",
  "Camera Malfunction": "카메라 고장", "Camera Malfunction: Reboot Your Device": "카메라 고장: 장치를 재부팅하세요",
  "Camera Frame Rate Low": "카메라 프레임 낮음", "Camera Frame Rate Low: Reboot Your Device": "카메라 프레임 낮음: 장치를 재부팅하세요",
  "CAN Bus Disconnected": "CAN 통신 끊김", "CAN Bus Disconnected: Check Connections": "CAN 통신 끊김: 연결을 확인하세요",
  "CAN Bus Disconnected: Likely Faulty Cable": "CAN 통신 끊김: 케이블 불량일 수 있어요",
  "Harness Relay Malfunction": "하네스 릴레이 고장", "Controls Mismatch": "제어 불일치", "Excessive Actuation": "과도한 제어",
  "Communication Issue Between Processes": "프로세스 간 통신 문제", "Low Communication Rate Between Processes": "프로세스 간 통신 느림",
  "Process Not Running": "프로세스가 실행되지 않음", "Selfdrive Process Lagging: Reboot Your Device": "제어 프로세스 지연: 장치를 재부팅하세요",
  "Driving Model Lagging": "주행 모델 지연", "Posenet Speed Invalid": "속도 추정 오류", "locationd Temporary Error": "위치 추정 일시 오류",
  "paramsd Temporary Error": "차량 파라미터 일시 오류", "Electronic Stability Control Active": "차체 자세 제어 작동 중",
  "Electronic Stability Control Disabled": "차체 자세 제어 꺼짐", "Radar Error: Restart the Car": "레이더 오류: 시동을 다시 거세요",
  "Radar Temporarily Unavailable": "레이더를 잠시 쓸 수 없어요", "Cruise Fault: Restart the Car": "크루즈 고장: 시동을 다시 거세요",
  "Cruise Fault: Restart the car to engage": "크루즈 고장: 시동을 다시 걸고 켜세요", "LKAS Fault: Restart the Car": "차로 유지 고장: 시동을 다시 거세요",
  "LKAS Fault: Restart the car to engage": "차로 유지 고장: 시동을 다시 걸고 켜세요", "Invalid LKAS setting": "차로 유지 설정 오류",
  "Disable your car's stock LKAS to engage": "켜려면 순정 차로 유지를 끄세요", "Enable your car's LKAS to engage": "켜려면 차량 차로 유지를 켜세요",
  "Toggle stock LKAS on or off to engage": "켜려면 순정 차로 유지를 껐다 켜세요",
  "Car Not Ready": "차량 준비 안 됨", "Car Unrecognized": "차량 인식 안 됨", "Unknown Vehicle Variant": "알 수 없는 차량 사양",
  "Dashcam Mode": "블랙박스 모드", "Dashcam mode": "블랙박스 모드", "Dashcam mode for unsupported car": "지원하지 않는 차량이라 블랙박스 모드예요",
  "Contact comma.ai/support": "comma.ai/support 에 문의하세요", "Steer ratio mismatch": "조향비 불일치", "Abnormal tire stiffness": "타이어 강성 이상",
  "Steering misalignment detected": "조향 정렬 이상", "Big Model Loading": "큰 모델 불러오는 중", "Big Model Failed": "큰 모델 실패", "Big Model Failed ": "큰 모델 실패 ",
  "Restart the car to retry,\nsmall model is still available": "시동을 다시 걸어 재시도하세요,\n작은 모델은 계속 쓸 수 있어요",
}

# 숫자 등이 들어간 문장
PATTERNS: list[tuple[re.Pattern, str]] = [(re.compile(p), r) for p, r in [
  (r"^Drive Above (.+)$", r"\1 이상으로 주행하세요"),
  (r"^Drive above (.+) to engage$", r"켜려면 \1 이상으로 주행하세요"),
  (r"^Steer Assist Unavailable Below (.+)$", r"\1 미만에서는 조향 보조가 안 돼요"),
  (r"^Disengage to (.+)$", r"\1 하려면 해제하세요"),
  (r"^Driving Personality: (.+)$", r"주행 성향: \1"),
  (r"^Remount Device \(Pitch: (.+)°, Yaw: (.+)°\)$", r"장치를 다시 달아 주세요 (상하 \1°, 좌우 \2°)"),
  (r"^Angle offset too high \(Offset: (.+)°\)$", r"각도 오프셋이 너무 커요 (\1°)"),
  (r"^Check tires, pressure, or alignment \(Factor: (.+)\)$", r"타이어 상태, 공기압, 정렬을 확인하세요 (계수 \1)"),
  (r"^Steering rack geometry may be off \(Ratio: (.+)\)$", r"조향 장치 이상일 수 있어요 (비율 \1)"),
  (r"^Speed Error: (.+) m/s$", r"속도 오차: \1 m/s"),
  (r"^(\d+)% frames dropped$", r"프레임 \1% 손실"),
  (r'^Forget Wi-Fi Network "(.+)"\?$', r'와이파이 "\1"을(를) 삭제할까요?'),
  (r'^for "(.+)"$', r'"\1" 비밀번호'),
  (r"^slide to\n(.+)$", r"밀어서\n\1"),
  (r"^please wait(.*)$", r"잠시만 기다려 주세요\1"),
  (r"^this may take up to\na minute(.*)$", r"최대 1분 정도\n걸릴 수 있어요\1"),
  (r"^Update available\. (.*)Tap to update\. Read the release notes at blog\.comma\.ai\.$", r"업데이트가 있어요. \1눌러서 업데이트하세요."),
  (r"^openpilot (.+) \((.+)\) is ready to install\. $", r"오픈파일럿 \1 (\2) 설치 준비가 됐어요. "),
  (r"^(\d+) (minutes?|hours?|days?) ago$", r"\1\2 전"),
  # 상단 알림 (기기 정보 % 대체 후)
  (r"^Device overheated\. The system is cooling down before starting\. Current internal component temperature: (.+)\.$", r"장치가 과열됐어요. 시작 전에 식히는 중이에요. 현재 내부 온도: \1."),
  (r"^Update check needed\. Connect to the internet to check for updates\. If you don't connect, openpilot won't engage in (.+)\.$", r"업데이트 확인이 필요해요. 인터넷에 연결해 주세요. 연결하지 않으면 \1 뒤에 오픈파일럿을 켤 수 없어요."),
  (r"^Excessive (.+) actuation\. This was detected on your last drive\. (.*)$", r"과도한 \1 제어가 지난 주행에서 감지됐어요. comma.ai/support 에 문의하세요."),
  (r"^Junpilot web: (.+)$", r"준파일럿 관리 페이지: \1"),
]]
# 단위 등 단어 치환은 PATTERNS 결과에도 적용
WORDS = {"minutes": "분", "minute": "분", "hours": "시간", "hour": "시간", "days": "일", "day": "일"}

OFFROAD = {
  "Connect to the internet. openpilot won't automatically start until it connects to the internet to check for updates.": "인터넷에 연결해 주세요. 업데이트를 확인하기 전까지 오픈파일럿이 자동으로 시작하지 않아요.",
  "Update failed. Ensure the software is correctly installed. Uninstall and re-install if this error persists, or reflash the device at flash.comma.ai.": "업데이트에 실패했어요. 소프트웨어가 제대로 설치됐는지 확인하고, 계속되면 다시 설치하거나 flash.comma.ai 에서 초기화하세요.",
  "Device not registered. This device failed to register with comma.ai, so it won't connect or upload to comma.ai servers and receives no support. If you purchased it at comma.ai/shop, open a ticket at comma.ai/support.": "장치가 등록되지 않았어요. 준파일럿은 콤마 서버를 쓰지 않으므로 주행에는 문제없어요.",
  "Uploads ignored. Uploads are being ignored due to a potential safety policy violation. Contact comma.ai/support if you believe this was made in error.": "업로드가 무시되고 있어요. 안전 정책 위반 가능성 때문이에요.",
  "Car not recognized. openpilot was unable to identify your car. It's either unsupported or its ECUs are not recognized. Please submit a pull request to add the firmware versions to the proper vehicle. Need help? Join discord.comma.ai.": "차량을 인식하지 못했어요. 지원하지 않는 차이거나 ECU 펌웨어를 알 수 없어요. 준파일럿 관리 페이지에서 펌웨어 값을 확인해 주세요.",
  "Device mount changed. openpilot detected a change in the device's mounting position. Ensure the device is fully seated in the mount and the mount is firmly secured to the windshield.": "장치 위치가 바뀌었어요. 장치가 거치대에 완전히 끼워졌는지, 거치대가 앞유리에 단단히 붙어 있는지 확인하세요.",
  "Poor driver visibility. Ensure the device has a clear view of the driver, which can be checked in the device settings. Extreme lighting conditions or unconventional mounting positions may also trigger this alert.": "운전자가 잘 보이지 않아요. 장치 설정에서 운전자 카메라를 확인하세요. 강한 빛이나 특이한 장착 위치도 원인일 수 있어요.",
  "Finish setup. Pair your device with comma connect to view recent drives and bookmarked routes.": "설정을 마쳐 주세요. 콤마 커넥트와 페어링하면 최근 주행을 볼 수 있어요.",
  "Chestnut overheated. Ensure good airflow.": "체스트넛이 과열됐어요. 통풍을 확인하세요.",
}
EXACT.update(OFFROAD)

_MONTHS = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_DATE = re.compile(r"^(\s*)(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2})(?:, (\d{4}))?(\s*)$")


def _date(text: str) -> str | None:
  """'Nov 24' -> '11월 24일' (첫 화면 날짜 등)"""
  m = _DATE.match(text)
  if not m:
    return None
  year = f"{m.group(4)}년 " if m.group(4) else ""
  return f"{m.group(1)}{year}{_MONTHS[m.group(2)]}월 {int(m.group(3))}일{m.group(5)}"


_cache: dict[str, str] = {}
_HANGUL = re.compile("[\uac00-\ud7a3]")
_LETTER = re.compile("[A-Za-z]")


def _words(s: str) -> str:
  for k, v in WORDS.items():
    s = s.replace(k, v)
  return s


def translate(text: str, base: dict[str, str] | None = None) -> str:
  """그려질 문장을 한국어로. 모르는 문장은 그대로 돌려준다."""
  if not text or _HANGUL.search(text) or not _LETTER.search(text):
    return text  # 이미 한글이거나 숫자·기호뿐이면 그대로
  hit = _cache.get(text)
  if hit is not None:
    return hit
  out = (base or {}).get(text) or EXACT.get(text)
  if out is None:
    stripped = text.strip()
    if stripped != text and stripped:
      t = (base or {}).get(stripped) or EXACT.get(stripped)
      if t:
        out = text.replace(stripped, t)
  if out is None:
    out = _date(text)
  if out is None:
    for pat, rep in PATTERNS:
      m = pat.match(text)
      if m:
        out = _words(m.expand(rep))
        break
  if out is None:
    # 주행 경고 문구 (화면은 소문자로 바꿔 그리기도 해서 대소문자 무시)
    from openpilot.junpilot.alerts_ko import translate as alert_ko
    t = alert_ko(text)
    if t != text:
      out = t
  if out is None:
    out = text
  if len(_cache) > 5000:
    _cache.clear()
  _cache[text] = out
  return out


def all_chars() -> set[str]:
  """한글 글꼴에 넣을 글자 목록."""
  chars: set[str] = set()
  for v in EXACT.values():
    chars.update(v)
  for _, rep in PATTERNS:
    chars.update(rep)
  for v in WORDS.values():
    chars.update(v)
  chars.update("년월일")
  return chars
