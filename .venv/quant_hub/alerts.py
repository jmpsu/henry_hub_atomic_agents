"""Alpha research alerting. A memo is a MODEL HYPOTHESIS, never a measured fact: it must cite its evidence,
model version, assumptions, contradictory evidence and out-of-sample backtest results before it can be published.
Publishing is dry-run by default (gh issue create)."""
import subprocess
from datetime import datetime, timezone

REQUIRED = ["relationship", "instruments", "analogs", "observations", "direction", "magnitude", "horizon",
            "markets", "assumptions", "contradictory_evidence", "confidence", "backtest_method",
            "vector_nodes", "model_version", "backtest_results"]


def validate_hypothesis(h: dict) -> list:
    problems = [f"missing field: {k}" for k in REQUIRED if k not in h or h[k] in (None, "", [], {})]
    br = h.get("backtest_results") or {}
    if br and br.get("sample") != "out_of_sample":
        problems.append("backtest_results must be out-of-sample")
    if br and "cost_bps" not in br:
        problems.append("backtest_results must include transaction costs (cost_bps)")
    if h.get("direction") not in ("up", "down", "neutral"):
        problems.append("direction must be up, down or neutral")
    return problems


def format_memo(h: dict, now=None) -> str:
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    br = h["backtest_results"]
    bullet = lambda xs: "\n".join(f"- {x}" for x in xs)
    return (f"# Alpha research memo {now}\n\n"
            "> **MODEL-GENERATED HYPOTHESIS. Vector similarity is retrieval, not proof of causation.**\n\n"
            f"**Relationship:** {h['relationship']}\n\n**Instruments:** {', '.join(h['instruments'])}\n\n"
            f"**Direction / magnitude / horizon:** {h['direction']} / {h['magnitude']} / {h['horizon']}\n\n"
            f"**Markets:** {', '.join(h['markets'])}\n\n## Evidence\n### Historical analogs\n{bullet(h['analogs'])}\n"
            f"### Structured observations\n{bullet(h['observations'])}\n### Vector nodes\n{bullet(h['vector_nodes'])}\n\n"
            f"## Assumptions\n{bullet(h['assumptions'])}\n\n## Contradictory evidence\n{bullet(h['contradictory_evidence'])}\n\n"
            f"**Confidence:** {h['confidence']}\n\n## Backtest ({h['backtest_method']})\n"
            f"- sample: {br['sample']}\n- n: {br.get('n')}\n- rmse: {br.get('rmse')}\n- directional hit rate: {br.get('directional_hit_rate')}\n"
            f"- mean return after costs: {br.get('mean_return_after_costs')} (cost_bps={br['cost_bps']})\n\n"
            f"Model: {h['model_version']}\n")


def publish_memo(h: dict, repo="jmpsu/henry_hub_atomic_agents", dry_run=True):
    problems = validate_hypothesis(h)
    if problems:
        raise ValueError("memo rejected: " + "; ".join(problems))
    title = f"Alpha hypothesis: {h['relationship'][:70]}"
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", format_memo(h), "--label", "alpha-hypothesis"]
    if dry_run:
        return {"dry_run": True, "title": title, "command": cmd}
    return {"dry_run": False, "output": subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()}
