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
  "cruise_auto": {"type": "bool", "default": True, "label": "크루즈 속도 자동 조절", "ready": True},
  "cruise_style": {"type": "choice", "default": 1, "choices": ["부드럽게", "보통", "빠르게"], "label": "주행 모드", "ready": True},
  "follow_gap": {"type": "choice", "default": 0, "choices": ["그대로 두기", "1단 (가깝게)", "2단", "3단", "4단 (멀게)"],
                 "label": "크루즈 켤 때 차간거리 단계", "ready": True},
  "auto_gap": {"type": "bool", "default": True, "label": "앞차·속도에 따라 차간거리 자동 조절", "ready": True},
  "navi_slowdown": {"type": "bool", "default": True, "label": "단속카메라·구간단속 감속", "ready": True},
  "nmirror": {"type": "bool", "default": False, "label": "폰 내비 단속 정보 사용", "ready": True},
  "navi_margin": {"type": "int", "default": 0, "min": -5, "max": 10, "label": "단속 속도 여유 (km/h)", "ready": True},
  # 0=사용 안 함, 1=수동(핸들을 밀어서), 2~4=깜빡이 1~3초 후 자동
  "ready_only": {"type": "bool", "default": True, "label": "계기판 READY일 때만 주행 모드 (키온일 땐 정차)", "ready": True},
  "lane_change_mode": {"type": "choice", "default": 1,
                       "choices": ["사용 안 함", "수동 (핸들을 밀어서 변경)", "깜빡이 1초 후", "깜빡이 2초 후", "깜빡이 3초 후"],
                       "label": "차선 변경", "ready": True},
  "curve_slowdown": {"type": "int", "default": 2, "min": 0, "max": 3, "label": "커브 감속 (0=끔, 3=많이)", "ready": True},
  # 조향 튜닝: 커브에서 안쪽으로 붙으면 조향 양을 낮추거나 시점을 늦춤
  "curve_steer": {"type": "int", "default": 100, "min": 85, "max": 110,
                  "label": "커브 조향 양 (%) · 안쪽으로 붙으면 낮추기", "ready": True},
  "lead_slowdown": {"type": "choice", "default": 2, "choices": ["끔", "1.0초", "1.2초", "1.5초"],
                    "label": "앞차에 붙으면 미리 감속", "ready": True},
  "cutin_slowdown": {"type": "bool", "default": True, "label": "옆 차 끼어들기 감속", "ready": True},
  "cruise_learn": {"type": "bool", "default": True, "label": "스마트크루즈 자가 학습", "ready": True},
  "curve_learn": {"type": "bool", "default": True, "label": "커브 자가 학습", "ready": True},
  "steer_timing": {"type": "choice", "default": 2, "choices": ["더 일찍", "조금 일찍", "기본", "조금 늦게", "더 늦게"],
                   "label": "조향 시점 · 커브를 일찍 파고들면 늦게", "ready": True},
}

STEER_TIMING_OFFSET = [0.10, 0.05, 0.0, -0.05, -0.10]  # 초, 모델이 앞을 내다보는 시간에 더함


def steer_tuning() -> tuple[float, float]:
  """(커브 조향 배율, 조향 시점 보정 초). 설정을 못 읽으면 기본값."""
  try:
    s = get_settings()
    scale = min(max(int(s.get("curve_steer", 100)), 85), 110) / 100.0
    idx = int(s.get("steer_timing", 2))
    return scale, STEER_TIMING_OFFSET[idx] if 0 <= idx < len(STEER_TIMING_OFFSET) else 0.0
  except Exception:
    return 1.0, 0.0

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
