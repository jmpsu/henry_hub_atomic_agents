"""Owner notifications (spec 7.5) delivered as GitHub issues on jmpsu/henry_hub_atomic_agents through the local `gh` CLI.

- incident(key, title, body): one open issue per incident key, titled "[key] title". A repeat of an open incident adds a
  comment instead of a new issue. Used for collector failures, data-quality rejections and edge-fetch failures.
- resolve(key, note): closes the open issue for that key with a comment (e.g. the collector succeeded again).
- event(stream, title, body): a comment on one rolling issue per stream (e.g. "backtests") so routine events do not
  create an issue each.
Delivery never raises into the caller: failures are returned and logged to runtime/notify.log.
Set NOTIFY=0 to disable (the test suite does). Labels are created once if missing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("NOTIFY_REPO", "jmpsu/henry_hub_atomic_agents")
LOG = Path(__file__).resolve().parent / "runtime" / "notify.log"
LABELS = {"incident": ("d73a4a", "Platform incident raised automatically"), "events": ("0e8a16", "Rolling stream of platform events"),
          "alpha-hypothesis": ("0E8A16", "Model-generated quantitative market hypothesis memo")}
_labels_ok: set = set()


def enabled() -> bool:
    return os.environ.get("NOTIFY", "1") != "0"


def _gh(*args, input_text=None, timeout=45):
    gh = shutil.which("gh") or "/home/joey/.local/bin/gh"
    p = subprocess.run([gh, *args], input=input_text, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _log(rec: dict) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **rec}) + "\n")
    except OSError:
        pass


def _label(name: str) -> None:
    if name in _labels_ok:
        return
    color, desc = LABELS[name]
    _gh("label", "create", name, "--repo", REPO, "--color", color, "--description", desc)   # fails harmlessly if it exists
    _labels_ok.add(name)


def _find_open(prefix: str, label: str):
    # plain listing (consistent immediately), filtered here; GitHub's search index lags behind new issues
    rc, out, _ = _gh("issue", "list", "--repo", REPO, "--state", "open", "--label", label, "--json", "number,title", "--limit", "200")
    if rc != 0:
        return None
    for i in json.loads(out or "[]"):
        if i["title"].startswith(prefix):
            return i["number"]
    return None


def incident(key: str, title: str, body: str) -> dict:
    if not enabled():
        return {"skipped": True}
    try:
        _label("incident")
        prefix = f"[{key}]"
        num = _find_open(prefix, "incident")
        if num:
            rc, out, err = _gh("issue", "comment", str(num), "--repo", REPO, "--body-file", "-", input_text=f"Still failing.\n\n{body}")
            res = {"action": "comment", "issue": num, "ok": rc == 0, "error": err if rc else None}
        else:
            rc, out, err = _gh("issue", "create", "--repo", REPO, "--title", f"{prefix} {title}"[:250], "--label", "incident", "--body-file", "-",
                               input_text=body)
            res = {"action": "create", "url": out if rc == 0 else None, "ok": rc == 0, "error": err if rc else None}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    _log({"kind": "incident", "key": key, **res})
    return res


def resolve(key: str, note: str) -> dict:
    if not enabled():
        return {"skipped": True}
    try:
        num = _find_open(f"[{key}]", "incident")
        if not num:
            return {"action": "none"}
        rc, _, err = _gh("issue", "close", str(num), "--repo", REPO, "--comment", note[:2000])
        res = {"action": "close", "issue": num, "ok": rc == 0, "error": err if rc else None}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    _log({"kind": "resolve", "key": key, **res})
    return res


def event(stream: str, title: str, body: str) -> dict:
    if not enabled():
        return {"skipped": True}
    try:
        _label("events")
        prefix = f"[{stream}]"
        num = _find_open(prefix, "events")
        if not num:
            rc, out, err = _gh("issue", "create", "--repo", REPO, "--title", f"{prefix} {stream} event stream", "--label", "events", "--body-file", "-",
                               input_text=f"Rolling stream of `{stream}` events. Each event is a comment.")
            if rc != 0:
                raise RuntimeError(err)
            num = int(out.rstrip("/").rsplit("/", 1)[-1])
        rc, out, err = _gh("issue", "comment", str(num), "--repo", REPO, "--body-file", "-", input_text=f"**{title}**\n\n{body}")
        res = {"action": "comment", "issue": num, "ok": rc == 0, "error": err if rc else None}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    _log({"kind": "event", "stream": stream, **res})
    return res
