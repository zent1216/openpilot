"""준파일럿: 업데이트 내역 (설치된 버전까지 준파일럿에서 바뀐 것).

기기의 오픈파일럿 폴더 git 기록에서 준파일럿 커밋만 골라 날짜와 한 줄 설명으로 보여준다.
"""
import subprocess

AUTHOR = "zent1216"
PREFIXES = ("준파일럿: ", "준파일럿 ", "PV5: ")
_cache: dict = {}


def _clean(subject: str) -> str:
  for p in PREFIXES:
    if subject.startswith(p):
      return subject[len(p):]
  return subject


def history(op_dir: str, limit: int = 30, run=subprocess.run) -> list[dict]:
  """[{time: 유닉스초, text: 설명}] 최신순. git이 없거나 실패하면 빈 목록."""
  try:
    head = run(["git", "-C", op_dir, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    if head and _cache.get("head") == head and _cache.get("limit") == limit:
      return _cache["items"]
    out = run(["git", "-C", op_dir, "log", f"--author={AUTHOR}", f"-n{limit}", "--format=%ct%x09%s"],
              capture_output=True, text=True, timeout=10).stdout
  except Exception:
    return []
  items = []
  for line in out.splitlines():
    t, _, s = line.partition("\t")
    if t.isdigit() and s:
      items.append({"time": int(t), "text": _clean(s.strip())})
  _cache.update(head=head, limit=limit, items=items)
  return items
