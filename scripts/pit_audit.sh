#!/usr/bin/env bash
# READ-ONLY audit of the Henry Hub PIT platform. Runs from any directory.
# No installs, config changes, DB writes, restarts, deploys or credential rotation.
# Makes read-only network requests. Redacts secret values from all output.
set +e
export LC_ALL=C
ROOT="${HH_ROOT:-/home/joey/Projects/henry_hub_atomic_agents}"
DOMAIN="quant.joeysvault.app"
WORKER="https://quant-gateway.joe-metz-psu.workers.dev"
API="http://127.0.0.1:8090"
redact() { sed -E 's/(cf[a-z]t_[A-Za-z0-9]+|gh[opsu]_[A-Za-z0-9_*]+|Bearer [A-Za-z0-9._~+\/=-]+|"(TunnelSecret|access_token|refresh_token|client_secret)"[ ]*:[ ]*"[^"]+")/[REDACTED]/g'; }
section() { printf '\n\n===== %s =====\n' "$1"; }
run() { printf '\n--- %s ---\n' "$*"; timeout 40 "$@" 2>&1 | redact | head -${MAXL:-60}; }

section "0 METADATA"; date -Is; id -un; echo "ROOT=$ROOT"

section "1 OS / TIME / DISK / MEMORY"
run hostnamectl; run timedatectl; run timedatectl timesync-status; run df -hT /; run free -h

section "2 LIVE APPLICATION RESOLUTION (from systemd and /proc)"
UNIT=quant_hub.service
run systemctl show $UNIT -p ActiveState -p SubState -p ActiveEnterTimestamp -p User -p WorkingDirectory -p EnvironmentFiles -p ExecStart -p Restart
PID=$(systemctl show $UNIT -p MainPID --value)
echo "MainPID=$PID"
if [ -n "$PID" ] && [ "$PID" != 0 ]; then
  echo "cwd=$(readlink /proc/$PID/cwd)"; echo "exe=$(readlink /proc/$PID/exe)"
  echo "cmd=$(tr '\0' ' ' < /proc/$PID/cmdline)"
fi
LIVE=$(systemctl show $UNIT -p WorkingDirectory --value); [ -z "$LIVE" ] && LIVE="$ROOT"
echo "RESOLVED_LIVE_DIR=$LIVE"
echo "venv-nested copy present: $([ -d $ROOT/.venv/quant_hub ] && echo YES-AMBIGUOUS || echo no)"

section "3 SOURCE INVENTORY / HASHES (no contents)"
for f in command_hub.py worker.js wrangler.toml init_db.py validate_env.py; do
  for d in "$LIVE" "$ROOT/.venv/quant_hub"; do [ -f "$d/$f" ] && sha256sum "$d/$f"; done; done
echo; ls -la "$LIVE" | head -40
echo "dependency manifests: $(ls $LIVE/requirements.txt $LIVE/pyproject.toml $LIVE/package.json 2>&1 | tr '\n' ' ')"
echo "collector/ingestion modules: $(find $LIVE -maxdepth 3 \( -iname '*collector*' -o -iname '*ingest*' -o -iname '*scrap*' \) -not -path '*/.venv/*' -not -path '*/node_modules/*' | head -20 | tr '\n' ' ')"
echo "test files: $(find $LIVE -maxdepth 3 -name 'test_*.py' -not -path '*/.venv/*' | head | tr '\n' ' ')"
echo "scheduling (cron/timers mentioning hub): $( (crontab -l 2>/dev/null; systemctl list-timers --all --no-pager 2>/dev/null) | grep -iE 'henry|quant|collector|ingest' | tr '\n' ' ')"

section "4 PYTHON / NODE / OLLAMA"
run "$ROOT/.venv/bin/python" --version; run "$ROOT/.venv/bin/python" -m pip check
run node --version; run ollama --version; run ollama ps
echo "ollama models:"; curl -s -m 5 127.0.0.1:11434/api/tags | python3 -c "import sys,json;print([m['name'] for m in json.load(sys.stdin)['models']])" 2>&1

section "5 ENVIRONMENT FILE (names only)"
ENVF="$LIVE/.env"; [ -f "$ENVF" ] && { stat -c 'perms=%a owner=%U' "$ENVF"; sed -E 's/=.*/=[PRESENT]/' "$ENVF" | grep -v '^#' ; } || echo "MISSING $ENVF"
grep -E '^(DB_PATH|PORT)=' "$ENVF" 2>/dev/null
echo "EnvironmentFile in unit matches: $(systemctl show $UNIT -p EnvironmentFiles --value | awk '{print $1}')"

section "6 DATABASE (read-only)"
DBP=$(grep -E '^DB_PATH=' "$ENVF" 2>/dev/null | cut -d= -f2-); [ -z "$DBP" ] && DBP="$LIVE/henry_hub_pit.db"
echo "DB_PATH=$DBP exists=$([ -f "$DBP" ] && echo yes || echo NO)"
python3 - "$DBP" <<'PYE'
import sqlite3,sys
p=sys.argv[1]
try:
    c=sqlite3.connect(f"file:{p}?mode=ro",uri=True)
    print("tables:",[r[0] for r in c.execute("select name from sqlite_master where type='table'")])
    print("integrity:",c.execute("pragma integrity_check").fetchone()[0])
    cols=[r[1] for r in c.execute("pragma table_info(pit_market_data)")]
    print("columns:",cols)
    n=c.execute("select count(*) from pit_market_data").fetchone()[0]; print("rows:",n)
    print("distinct agents:",c.execute("select count(distinct agent_id) from pit_market_data").fetchone()[0],"of 81 required")
    print("available_timestamp range:",c.execute("select min(available_timestamp),max(available_timestamp) from pit_market_data").fetchone())
    print("future-dated available_timestamp rows:",c.execute("select count(*) from pit_market_data where available_timestamp > strftime('%Y-%m-%dT%H:%M:%SZ','now')").fetchone()[0])
    print("production-contract columns present (source_id,raw_payload_hash,revision_timestamp,unit,provenance):",[x for x in ('source_id','raw_payload_hash','revision_timestamp','unit','provenance') if x in cols])
except Exception as e: print("DB ERROR:",e)
PYE
echo "raw payload archive dir: $(ls -d $LIVE/raw* $LIVE/vintages* $LIVE/payloads* 2>&1 | head -3 | tr '\n' ' ')"

section "7 LOCAL API"
curl -s -m 8 -o /dev/null -w "GET /execute (expect 405): %{http_code}\n" $API/execute
curl -s -m 8 -o /dev/null -w "GET /health: %{http_code}\n" $API/health
curl -s -m 8 $API/openapi.json | python3 -c "import sys,json;print('routes:',list(json.load(sys.stdin)['paths']))" 2>&1
ss -ltn | grep -E ':(8090|11434) '

section "8 CLOUDFLARED"
run systemctl status cloudflared --no-pager -n 3; MAXL=40 run grep -A3 -E 'hostname: quant|hostname: ollama' /etc/cloudflared/config.yml
echo "quant route target: $(grep -A1 'quant.joeysvault.app' /etc/cloudflared/config.yml | tail -1)"

section "9 DNS / TLS"
run getent ahosts $DOMAIN
echo | timeout 15 openssl s_client -connect $DOMAIN:443 -servername $DOMAIN 2>/dev/null | openssl x509 -noout -subject -enddate -ext subjectAltName 2>&1 | head -6

section "10 ACCESS AND WORKER BOUNDARIES"
curl -s -m 15 -o /dev/null -w "origin unauth GET (expect 403): %{http_code}\n" https://$DOMAIN/health
curl -s -m 15 -o /dev/null -w "origin unauth POST (expect 403): %{http_code}\n" -X POST https://$DOMAIN/execute -d '{}'
curl -s -m 15 -o /dev/null -w "worker GET (expect 405): %{http_code}\n" $WORKER
curl -s -m 15 -o /dev/null -w "worker POST no bearer (expect 401): %{http_code}\n" -X POST $WORKER -d '{}'
curl -s -m 15 -o /dev/null -w "worker POST bad bearer (expect 401): %{http_code}\n" -X POST $WORKER -H 'Authorization: Bearer wrong' -d '{}'
echo "wrangler.toml:"; cat "$LIVE/wrangler.toml" 2>/dev/null
source ~/.config/joey-secrets/joey-secrets.sh 2>/dev/null && js_load >/dev/null 2>&1
export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN_WORKER_ADMIN:-$CLOUDFLARE_API_TOKEN}"
echo "worker secret NAMES:"; (cd "$LIVE" && timeout 60 npx wrangler secret list 2>&1 | grep '"name"' | redact)
echo "access apps:"; curl -s -m 15 "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/access/apps" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -c "import sys,json;print([(a['name'],a['domain']) for a in json.load(sys.stdin)['result']])" 2>&1

section "11 GIT / SECRET EXPOSURE"
cd "$ROOT" && git status --short --branch | head -15
echo "tracked sensitive paths:"; git ls-files | grep -Ei '\.env|credential|secret|\.db$|chroma|audit/|\.pem' || echo none
echo "tracked compiled/cache files:"; git ls-files | grep -E '__pycache__|\.pyc$' || echo none
echo ".gitignore:"; cat .gitignore
echo "secrets patterns in tracked files (names only):"; git grep -lE 'cf[a-z]t_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}' 2>/dev/null || echo none
ls -la artifacts/ 2>/dev/null | head

section "12 GITHUB"
run gh auth status; run gh api user --jq '.login'

section "13 SPECIFICATION"
G="$ROOT/artifacts/Ultimate_Goal.md"; wc -l "$G"
echo "spec mentions 81 agents: $(grep -c '81' "$G")"; echo "agent roster in ODT: $(read_spec 2>/dev/null | grep -c '^Agent_')"
echo "distinct agent ids in DB vs roster: see section 6"

section "14 DONE"; date -Is; echo "READ-ONLY. No files modified."
