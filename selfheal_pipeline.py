#!/usr/bin/env python3
"""Spec 4.4: turn a validated selector repair into a reviewed GitHub pull request.

Selector-based agents are registered in ingestion/selectors.json:
  {"<agent_id>": {"collector": "<run_all name>", "selectors": ["span.price", ...], "range": [lo, hi], "fixtures": "tests/fixtures/selfheal/<agent_id>"}}
Selectors are tried in order; the first that yields a number wins. A repair is PREPENDED and the old selectors stay as
fallbacks, so pages in the old layout (the preserved fixtures) keep extracting their known values.
Fixture directory: *.html pages with *.expected (one number each) preserved from past successful runs.

repair(agent_id, html) does, in order, and stops at the first failure:
  1. diagnose the current selector against the failing page (structured record)
   2. propose a repair with local qwen2.5-coder:32b (selfheal.propose_repair: grounded, constrained retry)
  3. validate the proposal on EVERY preserved fixture AND on the failing page's value range
  4. create an isolated worktree on a new branch selfheal/<collector>/<UTC timestamp> from origin/<base>
  5. apply the patch (selectors.json), add the failing page as a new fixture, run the full test suite in the worktree
  6. commit, push the branch, and open a pull request with a repair report (gh pr create); never merges
The merge is the owner's decision. After it, the GitHub webhook drives the rerun (command_hub /selfheal/rerun).

Usage: selfheal_pipeline.py AGENT_ID PAGE.html [--base BRANCH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import selfheal  # noqa: E402

REG = "ingestion/selectors.json"
REPO = "jmpsu/henry_hub_atomic_agents"


def run(cmd, cwd, timeout=600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def fixtures(dir_: Path) -> list:
    out = []
    for h in sorted(dir_.glob("*.html")):
        e = h.with_suffix(".expected")
        if e.exists():
            out.append({"html": h.read_text(encoding="utf8", errors="ignore"), "expected": float(e.read_text().strip()), "name": h.name})
    return out


def parse_any(html: str, selectors: list) -> float:
    last = None
    for sel in selectors:
        try:
            return selfheal.parse_value(html, sel)
        except (LookupError, ValueError) as e:
            last = e
    raise LookupError(f"no selector produced a number ({last})")


def validate_list(selectors: list, fx: list) -> dict:
    res = []
    for f in fx:
        try:
            res.append(abs(parse_any(f["html"], selectors) - f["expected"]) < 1e-9)
        except LookupError:
            res.append(False)
    return {"passed": bool(res) and all(res), "n_fixtures": len(res), "results": res}


def repair(agent_id: str, page_html: str, base: str | None = None, dry_run: bool = False, llm=None, now=None) -> dict:
    reg = json.loads((ROOT / REG).read_text())
    if agent_id not in reg:
        return {"stage": "lookup", "ok": False, "error": f"{agent_id} is not a selector-based agent"}
    cfg = reg[agent_id]
    rng = tuple(cfg["range"]) if cfg.get("range") else None
    current = list(cfg["selectors"])
    try:
        v = parse_any(page_html, current)
        diag = {"agent_id": agent_id, "selector": current[0], "ok": rng is None or rng[0] <= v <= rng[1], "value": v,
                "error": None if (rng is None or rng[0] <= v <= rng[1]) else f"value {v} outside expected range {rng}"}
    except LookupError as e:
        diag = {"agent_id": agent_id, "selector": current[0], "ok": False, "value": None, "error": str(e)}
    report = {"agent_id": agent_id, "collector": cfg["collector"], "diagnosis": diag}
    if diag["ok"]:
        return {**report, "stage": "diagnose", "ok": True, "action": "none (selector still works)"}
    prop = selfheal.propose_repair(diag, page_html, llm or selfheal.ollama_llm)
    report["proposal"] = prop
    fx = fixtures(ROOT / cfg["fixtures"])
    new_list = [prop["selector"]] + [x for x in current if x != prop["selector"]]
    val = validate_list(new_list, fx)
    report["selectors_after"] = new_list
    try:
        page_value = selfheal.parse_value(page_html, prop["selector"])
        in_range = rng is None or rng[0] <= page_value <= rng[1]
    except (LookupError, ValueError):
        page_value, in_range = None, False
    report.update(validation=val, page_value=page_value, page_value_in_range=in_range)
    if not (val["passed"] and in_range):
        return {**report, "stage": "validate", "ok": False, "error": "proposal rejected by fixtures or value range"}
    base = base or run(["git", "rev-parse", "--abbrev-ref", "HEAD"], ROOT)[1]
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    branch = f"selfheal/{cfg['collector']}/{agent_id.lower()}-{ts}"
    wt = ROOT / "runtime" / "worktrees" / f"selfheal-{ts}"
    report["branch"] = branch
    if dry_run:
        return {**report, "stage": "dry_run", "ok": True}
    rc, out = run(["git", "fetch", "--quiet", "origin", base], ROOT)
    if rc:
        return {**report, "stage": "fetch", "ok": False, "error": out[-400:]}
    rc, out = run(["git", "worktree", "add", "-b", branch, str(wt), f"origin/{base}"], ROOT)
    if rc:
        return {**report, "stage": "worktree", "ok": False, "error": out[-400:]}
    try:
        reg_wt = json.loads((wt / REG).read_text())
        reg_wt[agent_id]["selectors"] = new_list
        (wt / REG).write_text(json.dumps(reg_wt, indent=1, sort_keys=True) + "\n")
        fdir = wt / cfg["fixtures"]
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / f"{ts}.html").write_text(page_html)
        (fdir / f"{ts}.expected").write_text(f"{page_value}\n")
        rc, out = run([str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "-q"], wt, timeout=900)
        report["tests"] = out.splitlines()[-1] if out else ""
        if rc:
            return {**report, "stage": "tests", "ok": False, "error": out[-800:]}
        run(["git", "add", REG, cfg["fixtures"]], wt)
        rc, out = run(["git", "commit", "-q", "-m", f"selfheal: {agent_id} add selector {prop['selector']!r} ahead of {current!r}\n\n"
                        f"Proposed by local qwen2.5-coder:32b, validated on {val['n_fixtures']} preserved fixtures and the failing page "
                       f"(value {page_value}). Tests: {report['tests']}.\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"], wt)
        if rc:
            return {**report, "stage": "commit", "ok": False, "error": out[-400:]}
        rc, out = run(["git", "push", "-q", "origin", branch], wt, timeout=120)
        if rc:
            return {**report, "stage": "push", "ok": False, "error": out[-400:]}
        validation = {k: val[k] for k in ("passed", "n_fixtures", "results")}
        body = (f"## Self-heal repair report\n\n- Agent: `{agent_id}` (collector `{cfg['collector']}`)\n"
                f"- Failure: {diag['error']}\n- Selectors: `{current}` → `{new_list}` (model attempts {prop['attempts']})\n"
                f"- Fixture validation: {json.dumps(validation)}\n- Failing page value with the new selector: {page_value} "
                f"(range {list(rng) if rng else 'none'})\n- Test suite in an isolated worktree: {report['tests']}\n\n"
                "The proposal is model output: review the diff before merging. Merging triggers the webhook rerun of the collector.\n\n"
                "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        rc, out = run(["gh", "pr", "create", "--repo", REPO, "--base", base, "--head", branch, "--title",
                       f"selfheal: repair {agent_id} selector", "--body", body], wt, timeout=120)
        if rc:
            return {**report, "stage": "pr", "ok": False, "error": out[-400:]}
        return {**report, "stage": "pr", "ok": True, "pr_url": out.splitlines()[-1]}
    finally:
        run(["git", "worktree", "remove", "--force", str(wt)], ROOT)
        shutil.rmtree(wt, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_id")
    ap.add_argument("page")
    ap.add_argument("--base")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    r = repair(a.agent_id, Path(a.page).read_text(encoding="utf8", errors="ignore"), a.base, a.dry_run)
    print(json.dumps(r, indent=1, default=str))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
