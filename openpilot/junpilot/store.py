"""준파일럿 설정 저장소 (/data/junpilot 아래 JSON 파일).

공식 Params 목록을 건드리지 않도록 준파일럿 전용 값은 여기 저장한다.
"""
import json
import os
import tempfile
import threading

from openpilot.common.hardware import PC


def data_dir() -> str:
  d = os.getenv("JUNPILOT_DIR")
  if d is None:
    d = os.path.expanduser("~/.comma/junpilot") if PC else "/data/junpilot"
  os.makedirs(d, exist_ok=True)
  return d


# 준파일럿 자체 설정. ready=False 항목은 아직 저장만 되고 동작에는 반영되지 않음
JUNPILOT_SETTINGS = {
  "cruise_auto": {"type": "bool", "default": False, "label": "크루즈 속도 자동 조절", "ready": True},
  "cruise_style": {"type": "choice", "default": 1, "choices": ["부드럽게", "보통", "빠르게"], "label": "주행 모드", "ready": True},
  "follow_gap": {"type": "int", "default": 3, "min": 1, "max": 4, "label": "차간거리 단계", "ready": False},
  "navi_slowdown": {"type": "bool", "default": True, "label": "단속카메라·구간단속 감속", "ready": True},
  "nmirror": {"type": "bool", "default": True, "label": "폰 내비 단속 정보 사용", "ready": True},
  "navi_margin": {"type": "int", "default": 0, "min": -5, "max": 10, "label": "단속 속도 여유 (km/h)", "ready": True},
  # 0=사용 안 함, 1=수동(핸들을 밀어서), 2~4=깜빡이 1~3초 후 자동
  "lane_change_mode": {"type": "choice", "default": 1,
                       "choices": ["사용 안 함", "수동 (핸들을 밀어서 변경)", "깜빡이 1초 후", "깜빡이 2초 후", "깜빡이 3초 후"],
                       "label": "차선 변경", "ready": True},
  "curve_slowdown": {"type": "int", "default": 2, "min": 0, "max": 3, "label": "커브 감속 (0=끔, 3=많이)", "ready": True},
}

_lock = threading.Lock()


def _path(name: str) -> str:
  return os.path.join(data_dir(), name)


def load(name: str, default):
  try:
    with open(_path(name)) as f:
      return json.load(f)
  except (OSError, ValueError):
    return default


def save(name: str, value) -> None:
  with _lock:
    fd, tmp = tempfile.mkstemp(dir=data_dir())
    with os.fdopen(fd, "w") as f:
      json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(name))


def get_settings() -> dict:
  saved = load("settings.json", {})
  if "lane_change_mode" not in saved and "auto_lane_change" in saved:  # 예전 설정(0=수동, 1~3=초) 옮기기
    saved["lane_change_mode"] = int(saved["auto_lane_change"]) + 1
  return {k: saved.get(k, spec["default"]) for k, spec in JUNPILOT_SETTINGS.items()}


def validate_setting(key: str, value):
  spec = JUNPILOT_SETTINGS.get(key)
  if spec is None:
    raise KeyError(key)
  t = spec["type"]
  if t == "bool":
    if not isinstance(value, bool):
      raise ValueError("켜기/끄기 값이어야 해요.")
  elif t in ("int", "choice"):
    if isinstance(value, bool) or not isinstance(value, int):
      raise ValueError("숫자여야 해요.")
    lo, hi = (0, len(spec["choices"]) - 1) if t == "choice" else (spec["min"], spec["max"])
    if not lo <= value <= hi:
      raise ValueError(f"{lo}~{hi} 사이 값이어야 해요.")
  return value


def set_settings(changes: dict) -> dict:
  current = get_settings()
  for k, v in changes.items():
    current[k] = validate_setting(k, v)
  save("settings.json", current)
  return current
