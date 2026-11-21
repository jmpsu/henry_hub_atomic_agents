#!/usr/bin/env bash
set -euo pipefail

EXPECTED_VERSION="${1:?Usage: verify_production.sh <expected_version> [expected_commit]}"
EXPECTED_COMMIT="${2:-}"
PROD_ROOT="/opt/quant-hub"
WORKER_BASE="https://quant-gateway.joe-metz-psu.workers.dev"

set -a
source "$PROD_ROOT/shared/.env"
set +a

if command -v wrangler >/dev/null 2>&1; then
  WRANGLER="wrangler"
elif [[ -x /home/joey/Projects/henry_hub_atomic_agents/node_modules/.bin/wrangler ]]; then
  WRANGLER="/home/joey/Projects/henry_hub_atomic_agents/node_modules/.bin/wrangler"
else
  WRANGLER="npx --yes wrangler"
fi

echo "1/8 Checking privileged hub on 127.0.0.1:8090..."
HUB_JSON="$(curl -fsS -m 10 http://127.0.0.1:8090/health)"
python3 - "$HUB_JSON" "$EXPECTED_VERSION" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
exp = sys.argv[2]
got = d.get("release_version") or d.get("version")
assert got == exp, f"8090 version mismatch: expected {exp}, got {got} ({d})"
print(f"    8090 OK (version={got})")
PY

echo "2/8 Checking read-only markets hub on 127.0.0.1:8095..."
MKT_JSON="$(curl -fsS -m 10 http://127.0.0.1:8095/api/health)"
python3 - "$MKT_JSON" "$EXPECTED_VERSION" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
exp = sys.argv[2]
got = d.get("release_version") or d.get("version")
assert got == exp, f"8095 version mismatch: expected {exp}, got {got} ({d})"
print(f"    8095 OK (version={got})")
PY

echo "3/8 Checking SQLite DB accessibility & migrations..."
"$PROD_ROOT/current/.venv/bin/python" "$PROD_ROOT/current/migrations/migrate.py" --db "$DB_PATH" --check
python3 - "$DB_PATH" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "pit_market_data" in tables, f"Missing pit_market_data table: {tables}"
cnt = conn.execute("SELECT COUNT(*) FROM pit_market_data").fetchone()[0]
conn.close()
print(f"    SQLite OK (pit_market_data rows={cnt})")
PY

echo "4/8 Checking ChromaDB accessibility..."
"$PROD_ROOT/current/.venv/bin/python" - <<'PY'
import os, chromadb
chroma_path = os.environ.get("CHROMA_PATH") or "/opt/quant-hub/current/chroma_pit_kb"
client = chromadb.PersistentClient(path=chroma_path)
cnt = client.get_or_create_collection("henry_hub_alpha_graph").count()
print(f"    ChromaDB OK (henry_hub_alpha_graph nodes={cnt})")
PY

echo "5/8 Checking required Ollama models..."
OLLAMA_TAGS="$(curl -fsS -m 10 http://127.0.0.1:11434/api/tags)"
python3 - "$OLLAMA_TAGS" <<'PY'
import json, sys
models = {m["name"] for m in json.loads(sys.argv[1]).get("models", [])}
for req in ("qwen3:4b", "nomic-embed-text"):
    if not any(m == req or m.startswith(req + ":") for m in models):
        raise SystemExit(f"Missing required Ollama model {req}; found {sorted(models)}")
print("    Ollama OK (qwen3:4b, nomic-embed-text present)")
PY

echo "6/8 Checking public read-only endpoints..."
curl -fsS -m 10 http://127.0.0.1:8095/api/state.json >/dev/null
curl -fsS -m 15 -A "quant-hub-verifier/1.0" https://markets.joeysvault.app/api/health >/dev/null
curl -fsS -m 15 -A "quant-hub-verifier/1.0" https://ngl.joeysvault.app/api/state.json >/dev/null
echo "    Public read-only endpoints OK"

echo "7/8 Checking Cloudflare Worker version, queues, triggers, and auth..."
WORKER_VER_JSON="$(curl -fsS -m 15 -A "quant-hub-verifier/1.0" "$WORKER_BASE/_release")"
python3 - "$WORKER_VER_JSON" "$EXPECTED_VERSION" "$EXPECTED_COMMIT" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
exp_v, exp_c = sys.argv[2], sys.argv[3]
assert d.get("version") == exp_v, f"Worker version mismatch: {d}"
if exp_c:
    assert d.get("commit") == exp_c, f"Worker commit mismatch: {d}"
print(f"    Worker /_release OK (version={d['version']} commit={d.get('commit','')[:12]})")
PY

QUEUES_OUT="$($WRANGLER queues list)"
grep -q "quant-backtest-jobs" <<<"$QUEUES_OUT"
grep -q "quant-backtest-dlq" <<<"$QUEUES_OUT"
grep -q '30 13 \* \* \*' "$PROD_ROOT/current/wrangler.toml"
grep -q '45 15 \* \* THU' "$PROD_ROOT/current/wrangler.toml"

UNAUTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -A "quant-hub-verifier/1.0" -X POST "$WORKER_BASE/execute" -H "Content-Type: application/json" -d '{"query":"ping"}')"
[[ "$UNAUTH_CODE" == "401" ]] || { echo "Expected 401 on unauthenticated POST /execute, got $UNAUTH_CODE" >&2; exit 1; }
echo "    Worker queues, triggers, and 401 auth gate OK"

echo "8/8 Checking synthetic end-to-end request through Cloudflare Worker -> Tunnel -> Linux Hub..."
if [[ -n "${MOBILE_COMMAND_SECRET:-}" ]]; then
  E2E_RESP="$(curl -fsS -m 45 -A "quant-hub-verifier/1.0" -X POST "$WORKER_BASE/execute" \
    -H "Authorization: Bearer $MOBILE_COMMAND_SECRET" \
    -H "Content-Type: application/json" \
    -d '{"query":"Summarize latest Henry Hub storage and LNG feedgas availability","as_of_timestamp":"2026-11-15T00:00:00Z"}')"
  python3 - "$E2E_RESP" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
for k in ("as_of_timestamp", "db_rows", "sql_source", "data_quality", "analysis"):
    assert k in d, f"Missing {k} in E2E payload: {list(d)}"
assert isinstance(d["analysis"], dict) and d["analysis"], f"Empty analysis in E2E payload: {d}"
print(f"    Synthetic Cloudflare -> Hub E2E OK (analysis_keys={sorted(d['analysis'])})")
print("    Synthetic Cloudflare -> Hub E2E OK")
PY
else
  echo "ERROR: MOBILE_COMMAND_SECRET not present in $PROD_ROOT/shared/.env for E2E verification" >&2
  exit 1
fi

echo "ALL UNIFIED VERIFICATION CHECKS PASSED FOR v$EXPECTED_VERSION"
