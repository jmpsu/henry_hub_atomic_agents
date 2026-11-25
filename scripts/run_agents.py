#!/usr/bin/env python3
"""Daily post-collection step: fold new data into the knowledge library, then run the research agents.

Both run inside the hub process (127.0.0.1:8090) because it owns the Chroma collection; this script only calls it over
loopback (Cloudflare Access protects the public hostname, not loopback). Called by hh-collect-cpc.service (ExecStopPost, so it
also runs when a collector failed - that is exactly when the diagnostics and repair agents have work).

Exit 0 when both calls succeeded and every agent reported ok; 1 otherwise. A summary line per step goes to stdout (journal).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

HUB = os.environ.get("HUB_URL", "http://127.0.0.1:8090")


def post(path: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(HUB + path, method="POST", data=b"", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode(errors="replace")[:300]}
    except Exception as e:  # noqa: BLE001
        return 0, {"detail": f"{type(e).__name__}: {e}"}


def main() -> int:
    st, kb = post("/kb/ingest", 900)
    print("kb_ingest", st, json.dumps({k: kb.get(k) for k in ("new", "changed", "nodes_total", "detail") if k in kb}))
    st2, rep = post("/agents/run?notice_limit=150", 3000)
    if st2 == 409:
        print("agents already running (started by another trigger)")
        return 0 if st == 200 else 1
    agents = rep.get("agents", {})
    print("agents", st2, json.dumps({k: v.get("ok") for k, v in agents.items()}), "findings", rep.get("findings"), rep.get("detail", ""))
    return 0 if st == 200 and st2 == 200 and agents and all(v.get("ok") for v in agents.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
