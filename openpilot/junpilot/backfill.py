"""준파일럿: 리포트가 없는 지난 주행기록(요약 로그 qlog)으로 주행 리포트를 만든다.

주행 중 기록기가 멈춰 있던 동안의 주행도 리포트·튜닝에 쓰이도록, 정차 중에 한 주행씩 천천히 처리한다.
이미 리포트가 있는 시간대와 겹치는 주행은 건너뛴다.
"""
import json
import os
import threading
import time
from dataclasses import replace

from openpilot.junpilot import collector
from openpilot.junpilot.tracker import DriveTracker, list_drives

NEED = ('carState', 'selfdriveState', 'radarState', 'carControl', 'modelV2', 'deviceState')
DONE_FILE = "backfilled.txt"
OVERLAP_MARGIN = 120.0  # 초


def _read_events(path: str):
  import zstandard as zstd
  from openpilot.cereal import log
  with open(path, "rb") as f:
    dat = f.read()
  if dat.startswith(b'\x28\xB5\x2F\xFD'):
    with zstd.ZstdDecompressor().stream_reader(dat) as r:
      dat = r.read()
  try:
    yield from log.Event.read_multiple_bytes(dat)
  except Exception:  # 마지막 구간이 잘려 있을 수 있음
    return


def report_from_route(seg_qlogs: list[str], route_start: float) -> dict | None:
  """구간 순서대로 된 qlog 경로들로 주행 리포트(dict)를 만든다. 짧은 주행이면 None."""
  t0: list[float] = []

  def wall() -> float:
    return route_start + (now[0] - t0[0] if t0 else 0.0)

  now = [0.0]
  tr = DriveTracker(save_dir=None, wall_clock=wall)
  sm: dict = {}
  last = -1.0
  for path in seg_qlogs:
    for ev in _read_events(path):
      w = ev.which()
      if w not in NEED:
        continue
      sm[w] = getattr(ev, w)
      now[0] = ev.logMonoTime / 1e9
      if not t0:
        t0.append(now[0])
      if len(sm) == len(NEED) and now[0] - last >= 0.1:
        last = now[0]
        tr.update(collector.snapshot_from(sm, {}, t=now[0]))
  if tr.stats is None or len(sm) < len(NEED):
    return None
  tr.update(replace(collector.snapshot_from(sm, {}, t=now[0] + 0.1), onroad=False))
  return tr.last_saved


def _load_done(save_dir: str) -> set:
  try:
    with open(os.path.join(save_dir, DONE_FILE)) as f:
      return set(json.load(f))
  except (OSError, ValueError):
    return set()


def _save_done(save_dir: str, done: set):
  os.makedirs(save_dir, exist_ok=True)
  tmp = os.path.join(save_dir, DONE_FILE + ".tmp")
  with open(tmp, "w") as f:
    json.dump(sorted(done)[-500:], f)
  os.replace(tmp, os.path.join(save_dir, DONE_FILE))


def backfill_one(routes: list[dict], log_root: str, save_dir: str, skip_route: str | None = None) -> str | None:
  """리포트 없는 주행 하나를 처리하고 그 이름을 돌려준다. 할 게 없으면 None."""
  done = _load_done(save_dir)
  drives = list_drives(save_dir)
  for g in sorted(routes, key=lambda r: r.get("mtime", 0)):
    route = g["route"]
    if route in done or route == skip_route or "qlog" not in g.get("kinds", []):
      continue
    qlogs = [os.path.join(log_root, f"{route}--{s}", "qlog.zst") for s in sorted(g["segments"])]
    qlogs = [p for p in qlogs if os.path.isfile(p)]
    done.add(route)
    if not qlogs:
      _save_done(save_dir, done)
      return route
    end = os.path.getmtime(qlogs[-1])
    start = end - 60.0 * len(qlogs)
    overlap = any(d.get("start", 0) < end + OVERLAP_MARGIN and d.get("end", 0) > start - OVERLAP_MARGIN for d in drives)
    if not overlap:
      data = report_from_route(qlogs, start)
      if data is not None:
        data["from_log"] = True  # 로그로 나중에 만든 리포트
        os.makedirs(save_dir, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(data["start"])) + ".json"
        tmp = os.path.join(save_dir, name + ".tmp")
        with open(tmp, "w") as f:
          json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(save_dir, name))
    _save_done(save_dir, done)
    return route
  return None


def start(app):
  """정차 중일 때만, 한 주행씩 쉬엄쉬엄 처리."""
  def loop():
    try:
      os.nice(10)
    except OSError:
      pass
    while True:
      time.sleep(30)
      try:
        if app.dev.is_onroad():
          continue
        while not app.dev.is_onroad() and backfill_one(app.routes(), app.dev.log_root(), collector.drives_dir()):
          time.sleep(2)
      except Exception as e:
        if app.collector is not None:
          app.collector.last_error = f"지난 주행 리포트 만들기: {type(e).__name__}: {e}"
  threading.Thread(target=loop, daemon=True, name="junpilot-backfill").start()
