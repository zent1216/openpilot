from types import SimpleNamespace as NS

from openpilot.junpilot import changelog


def test_history_parses_and_strips(monkeypatch):
  changelog._cache.clear()
  calls = []

  def run(cmd, **kw):
    calls.append(cmd)
    if "rev-parse" in cmd:
      return NS(stdout="abc\n")
    return NS(stdout="1764200000\t준파일럿: 끼어들기 감속 부드럽게\n1764100000\tPV5: 버튼 안정화\n")
  items = changelog.history("/x", run=run)
  assert items == [{"time": 1764200000, "text": "끼어들기 감속 부드럽게"}, {"time": 1764100000, "text": "버튼 안정화"}]
  assert any("--author=zent1216" in c for c in calls[1])
  n = len(calls)
  changelog.history("/x", run=run)  # 같은 버전이면 다시 안 읽음
  assert len(calls) == n + 1


def test_history_no_git():
  changelog._cache.clear()

  def run(cmd, **kw):
    raise FileNotFoundError
  assert changelog.history("/x", run=run) == []
