"""Self-healing scraper core. Repairs are proposed as DATA (a new selector), never as code; a proposal is
accepted only if it reproduces the expected values on preserved fixtures. PR creation is dry-run by
default and requires validation to pass; merging always needs a human (this module never merges)."""
import json
import re
import subprocess
from html.parser import HTMLParser


class _Collect(HTMLParser):
    def __init__(self, selector):
        super().__init__()
        m = re.fullmatch(r"(?:(?P<tag>[a-z0-9]+))?(?:#(?P<id>[\w-]+))?(?:\.(?P<cls>[\w-]+))?", selector.strip())
        if not m or not selector.strip():
            raise ValueError("unsupported selector: " + selector)
        self.tag, self.id, self.cls = m["tag"], m["id"], m["cls"]
        self.depth, self.buf, self.out = 0, [], []

    def _match(self, tag, attrs):
        a = dict(attrs)
        return ((not self.tag or tag == self.tag) and (not self.id or a.get("id") == self.id)
                and (not self.cls or self.cls in (a.get("class") or "").split()))

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID:   # void elements never get an end tag; counting them would leave the match open forever
            return
        if self.depth:
            self.depth += 1
        elif self._match(tag, attrs):
            self.depth, self.buf = 1, []

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.out.append("".join(self.buf).strip())

    def handle_data(self, data):
        if self.depth:
            self.buf.append(data)


def extract(html: str, selector: str) -> list:
    p = _Collect(selector)
    p.feed(html)
    return p.out


def parse_value(html: str, selector: str):
    """Deterministic scalar extraction: first match, thousands separators stripped, must be numeric."""
    hits = extract(html, selector)
    if not hits:
        raise LookupError("selector matched nothing")
    txt = re.sub(r"[,\s$]", "", hits[0])
    return float(txt)


def diagnose(agent_id: str, html: str, selector: str, expected_range=None) -> dict:
    """Structured diagnostic record for a collector run (no side effects)."""
    d = {"agent_id": agent_id, "selector": selector, "ok": False, "error": None, "value": None}
    try:
        v = parse_value(html, selector)
        if expected_range and not (expected_range[0] <= v <= expected_range[1]):
            d["error"] = f"value {v} outside expected range {expected_range}"
        else:
            d.update(ok=True, value=v)
    except (LookupError, ValueError) as e:
        d["error"] = str(e)
    return d


REPAIR_SCHEMA = {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}


def propose_repair(diag: dict, html: str, llm) -> dict:
    """llm(prompt, schema) -> dict. The prompt ends with /no_think; callers use num_predict 180."""
    prompt = (f"A scraper selector '{diag['selector']}' failed ({diag['error']}) for {diag['agent_id']}. "
              f"Return one CSS-like selector (tag, #id, .class or tag.class) that isolates the numeric value in this HTML:\n"
              f"{html[:1200]}\n/no_think")
    out = llm(prompt, REPAIR_SCHEMA)
    return {"selector": str(out.get("selector", "")).strip()}


def validate_proposal(candidate_selector: str, fixtures: list) -> dict:
    """fixtures: [{"html":..., "expected": float}, ...] preserved from past successful runs. All must match."""
    results = []
    for f in fixtures:
        try:
            got = parse_value(f["html"], candidate_selector)
            results.append(abs(got - f["expected"]) < 1e-9)
        except (LookupError, ValueError):
            results.append(False)
    return {"passed": bool(results) and all(results), "n_fixtures": len(results), "results": results}


def open_pull_request(branch: str, title: str, body: str, validation: dict, tests_passed: bool, dry_run=True, repo="jmpsu/henry_hub_atomic_agents"):
    """Refuses unless deterministic validation AND the test suite passed. Never merges."""
    if not (validation.get("passed") and tests_passed):
        raise PermissionError("repair rejected: validation or tests did not pass")
    cmd = ["gh", "pr", "create", "--repo", repo, "--head", branch, "--title", title, "--body", body]
    if dry_run:
        return {"dry_run": True, "command": cmd}
    return {"dry_run": False, "output": subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()}
