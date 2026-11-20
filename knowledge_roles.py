"""R1.7 / R1.8 / V2: every knowledge object carries a `domain_role`, and the pricing side may read only two of the three roles.

  market_narrative      commentary, notices, forecast discussions, agent findings and theses, backtest write-ups, news, research notes. Never touches a price.
  physical_fundamental  measured or modelled physical quantities (storage, production, weather observations, LNG exports and feedgas, flows) and the
                        definitions that classify them.
  pricing_parameter     a number that is an explicit input of a price formula (k, L, shipping, regas, T&F) and the node that defines the pricing model.

Rules are keyed by the knowledge-graph domain (kb_nodes.domain) and by the literature store's document kind. Anything not listed is `market_narrative`
(the safe default: it cannot reach a price). A literature document is upgraded to `pricing_parameter` only when a verbatim quote from it was accepted
into runtime/lng_params.json under the O13-R checks. Roles are stored in side tables (kb_roles, lit_roles) so no existing table layout changes."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

NARRATIVE, PHYSICAL, PARAMETER = "market_narrative", "physical_fundamental", "pricing_parameter"
ROLES = (NARRATIVE, PHYSICAL, PARAMETER)
PRICING_READABLE = frozenset({PHYSICAL, PARAMETER})
KB_DOMAIN_ROLE = {"storage": PHYSICAL, "production": PHYSICAL, "weather": PHYSICAL, "carbon": PHYSICAL, "price": PHYSICAL, "fundamentals": PHYSICAL, "entity": PHYSICAL,
                  "pipeline_notice": NARRATIVE, "noaa_discussion": NARRATIVE, "agent_finding": NARRATIVE, "alpha_synthesis": NARRATIVE, "backtest": NARRATIVE}
KB_KEY_ROLE = {"forward_pricing_model": PARAMETER}           # series_key overrides the domain rule
LIT_KIND_ROLE = {"news": NARRATIVE, "paper": NARRATIVE, "research": NARRATIVE}


def kb_role(domain: str, series_key: str = "") -> str:
    return KB_KEY_ROLE.get(series_key) or KB_DOMAIN_ROLE.get(domain, NARRATIVE)


def lit_role(kind: str, doc_id: str = "", parameter_docs: frozenset = frozenset()) -> str:
    return PARAMETER if doc_id in parameter_docs else LIT_KIND_ROLE.get(kind, NARRATIVE)


def assert_pricing_input(role: str) -> None:
    """V2 guard for any code that is about to feed a knowledge object into a price: only physical_fundamental and pricing_parameter pass."""
    if role not in PRICING_READABLE:
        raise ValueError(f"knowledge role {role!r} may not feed a price (narrative never touches pricing weights)")


def tag_kb(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS kb_roles(id TEXT PRIMARY KEY, domain_role TEXT NOT NULL)")
    rows = conn.execute("SELECT id, domain, series_key FROM kb_nodes").fetchall()
    conn.executemany("INSERT OR REPLACE INTO kb_roles VALUES (?,?)", [(i, kb_role(d, k)) for i, d, k in rows])
    return len(rows)


def parameter_docs(params_path: Path | str) -> frozenset:
    """doc_ids whose quotes were accepted into the LNG parameters file (library-sourced k or L)."""
    try:
        doc = json.loads(Path(params_path).read_text())
    except (OSError, ValueError):
        return frozenset()
    return frozenset(p.get("doc_id") for p in (doc.get("params") or {}).values() if p.get("source") == "library" and p.get("doc_id"))


def tag_lit(conn: sqlite3.Connection, params_path: Path | str | None = None) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS lit_roles(doc_id TEXT PRIMARY KEY, domain_role TEXT NOT NULL)")
    pd = parameter_docs(params_path) if params_path else frozenset()
    rows = conn.execute("SELECT doc_id, kind FROM lit_docs").fetchall()
    conn.executemany("INSERT OR REPLACE INTO lit_roles VALUES (?,?)", [(d, lit_role(k, d, pd)) for d, k in rows])
    return len(rows)


def role_of_kb(conn: sqlite3.Connection, node_id: str) -> str:
    try:
        r = conn.execute("SELECT domain_role FROM kb_roles WHERE id=?", (node_id,)).fetchone()
    except sqlite3.OperationalError:
        r = None
    return r[0] if r else NARRATIVE


def role_of_lit(conn: sqlite3.Connection, doc_id: str) -> str:
    try:
        r = conn.execute("SELECT domain_role FROM lit_roles WHERE doc_id=?", (doc_id,)).fetchone()
    except sqlite3.OperationalError:
        r = None
    return r[0] if r else NARRATIVE
