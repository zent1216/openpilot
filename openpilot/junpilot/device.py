"""관리 페이지가 장치에 접근하는 부분을 한곳에 모음 (테스트에서는 가짜로 교체)."""
import os
import signal
import subprocess

# 휴대폰/노트북에서 바꿀 수 있는 공식 설정 (모두 정차 중에만 변경 가능)
# 운전자 감시를 끄거나 약하게 하는 항목은 넣지 않는다.
OFFICIAL_SETTINGS = {
  "OpenpilotEnabledToggle": {"type": "bool", "label": "오픈파일럿 사용"},
  "IsLdwEnabled": {"type": "bool", "label": "차선 이탈 경고"},
  "IsMetric": {"type": "bool", "label": "km/h 단위 사용"},
  "DisengageOnAccelerator": {"type": "bool", "label": "가속 페달 밟으면 해제"},
  "AlwaysOnDM": {"type": "bool", "label": "운전자 감시 항상 켜기"},
  "RecordFront": {"type": "bool", "label": "운전자 카메라 녹화"},
  "RecordAudio": {"type": "bool", "label": "소리 녹음"},
  "LanguageSetting": {"type": "choice_str", "label": "화면 언어", "choices": {"ko": "한국어", "en": "English"}},
}


class Device:
  def __init__(self):
    from openpilot.common.params import Params
    self.params = Params()

  # ---- 설정 ----
  def get_param(self, key):
    return self.params.get(key, return_default=True)

  def put_param(self, key, value):
    self.params.put(key, value)

  def is_onroad(self) -> bool:
    # 이 버전에는 IsOnroad가 없고 IsOffroad만 있음 (매니저가 시작 시 True, 주행 시작 시 False)
    return not self.params.get_bool("IsOffroad")

  # ---- 정보 ----
  def info(self) -> dict:
    out = {k: self.params.get(k) for k in ("Version", "GitBranch", "GitCommit", "DongleId", "UpdaterState",
                                             "UpdaterCurrentDescription", "UpdaterNewDescription")}
    out["UpdateAvailable"] = self.params.get_bool("UpdateAvailable")
    out["car"] = None
    cp_bytes = self.params.get("CarParamsPersistent")
    if cp_bytes:
      from opendbc.car.structs import car
      with car.CarParams.from_bytes(cp_bytes) as CP:
        out["car"] = {
          "fingerprint": CP.carFingerprint,
          "vin": CP.carVin,
          "fingerprintSource": str(CP.fingerprintSource),
          "openpilotLongitudinal": CP.openpilotLongitudinalControl,
          "fw": [{"ecu": str(f.ecu), "address": f.address, "subAddress": f.subAddress,
                  "version": f.fwVersion.hex(), "brand": f.brand, "logging": f.logging} for f in CP.carFw],
        }
    return out

  def log_root(self) -> str:
    from openpilot.common.hardware.hw import Paths
    return Paths.log_root()

  def ip_addresses(self) -> list[str]:
    try:
      out = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=2).stdout
    except Exception:
      return []
    ips = []
    for line in out.splitlines():
      parts = line.split()
      if "inet" in parts:
        ip = parts[parts.index("inet") + 1].split("/")[0]
        if not ip.startswith("127."):
          ips.append(ip)
    return ips

  # ---- 화면 알림 / 업데이트 ----
  def set_pairing_alert(self, show: bool, text: str = ""):
    from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
    set_offroad_alert("Offroad_JunpilotPairing", show, text)

  def check_update(self) -> bool:
    out = subprocess.run(["pgrep", "-f", "openpilot.system.updated.updated"], capture_output=True, text=True).stdout.split()
    for pid in out:
      try:
        os.kill(int(pid), signal.SIGUSR1)
        return True
      except (OSError, ValueError):
        pass
    return False

  def reboot(self):
    self.params.put_bool("DoReboot", True)
