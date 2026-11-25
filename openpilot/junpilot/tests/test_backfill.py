import os

import zstandard as zstd

from openpilot.cereal import log
from openpilot.junpilot import backfill
from openpilot.junpilot.tracker import list_drives

ROUTE = "0000002a--abcdef1234"


def _qlog(path, t0, secs, v=15.0):
  out = b""
  t = t0
  while t < t0 + secs:
    for w in backfill.NEED:
      ev = log.Event.new_message()
      ev.logMonoTime = int(t * 1e9)
      m = ev.init(w)
      if w == "carState":
        m.vEgo = v
      elif w == "deviceState":
        m.started = True
      elif w == "selfdriveState":
        m.enabled = True
      out += ev.to_bytes()
    t += 0.1
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "wb") as f:
    f.write(zstd.compress(out))


def test_backfill_makes_report_once(tmp_path):
  root, save = str(tmp_path / "logs"), str(tmp_path / "drives")
  for s in (0, 1):
    _qlog(os.path.join(root, f"{ROUTE}--{s}", "qlog.zst"), 100 + 60 * s, 60)
  routes = [{"route": ROUTE, "segments": [0, 1], "kinds": ["qlog"], "mtime": 1}]
  assert backfill.backfill_one(routes, root, save) == ROUTE
  ds = list_drives(save)
  assert len(ds) == 1 and ds[0]["from_log"] and ds[0]["distance_km"] > 1.5 and ds[0]["engaged_pct"] > 90
  assert backfill.backfill_one(routes, root, save) is None  # 다시 만들지 않음
