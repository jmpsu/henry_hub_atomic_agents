#!/usr/bin/env bash
# NGL / Henry Hub full read-only technical audit
# Reconstructed from the supplied 27-section audit report and project specification.
# It does not edit project files, run tests, deploy services, or write to databases.
set +e
export LC_ALL=C
umask 077

ROOT="${ROOT:-/home/joey/Projects/henry_hub_atomic_agents}"
LIVE="${LIVE:-$ROOT/.venv/quant_hub}"
DB="${DB:-$LIVE/henry_hub_pit.db}"
API="${API:-http://127.0.0.1:8090}"
DOMAIN="${DOMAIN:-quant.joeysvault.app}"
WORKER="${WORKER:-https://quant-gateway.joe-metz-psu.workers.dev}"
WRANGLER="${WRANGLER:-$ROOT/node_modules/.bin/wrangler}"

section() { printf '\n\n========== %s ==========\n' "$1"; }
subsection() { printf '\n--- %s ---\n' "$1"; }
run() {
    subsection "$(printf '%q ' "$@")"
    "$@" 2>&1
    local rc=$?
    printf '[exit=%s]\n' "$rc"
    return 0
}
run_sh() {
    subsection "$1"
    bash -c "$2" 2>&1
    local rc=$?
    printf '[exit=%s]\n' "$rc"
    return 0
}
have() { command -v "$1" >/dev/null 2>&1; }
redact() {
    sed -E \
      -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._~+\/-]+/\1[REDACTED]/Ig' \
      -e 's/((TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*[=:][[:space:]]*)[^[:space:]"'"'"']+/\1[REDACTED]/Ig' \
      -e 's/(CF-Access-Client-Secret:[[:space:]]*)[^[:space:]]+/\1[REDACTED]/Ig'
}

section "AUDIT METADATA"
date -Is
printf 'Audit user: '; id
printf 'Project: %s\nLive application: %s\nDatabase: %s\n' "$ROOT" "$LIVE" "$DB"
printf 'API: %s\nDomain: %s\nWorker: %s\n' "$API" "$DOMAIN" "$WORKER"
printf 'Audit mode: READ ONLY (no intentional file/database/service changes)\n'
printf 'Script version: reconstructed 27-section read-only audit\n'

section "1. OPERATING SYSTEM"
run hostnamectl
run uname -a
run cat /etc/os-release
run uptime
run timedatectl
run df -hT
run df -i
run free -h
run lsblk -o NAME,SIZE,FSTYPE,FSVER,MOUNTPOINTS
run findmnt
run ulimit -a

section "2. TIME SYNCHRONIZATION"
run timedatectl timesync-status
run systemctl status systemd-timesyncd --no-pager
run systemctl status chrony --no-pager
run chronyc tracking
run chronyc sources -v

section "3. NETWORK AND FIREWALL"
run ip -brief address
run ip route
run ip rule
run resolvectl status
run getent ahosts "$DOMAIN"
run getent ahosts "joeysvault.app"
run ss -lntup
run ufw status verbose
run nft list ruleset
run sysctl net.ipv4.ip_forward
run sysctl net.ipv4.tcp_syncookies

section "4. PROJECT DIRECTORY AND SOURCE INVENTORY"
if [ -d "$ROOT" ]; then
  run stat "$ROOT" "$LIVE" "$DB"
  run_sh "Root inventory, excluding generated dependencies" "find '$ROOT' -maxdepth 4 -type f ! -path '$ROOT/.venv/*' ! -path '$ROOT/.git/*' ! -path '$ROOT/node_modules/*' ! -path '*/__pycache__/*' -printf '%TY-%Tm-%Td %TH:%TM:%TS %10s %p\\n' | sort"
  run_sh "Directory inventory" "find '$ROOT' -maxdepth 3 -type d ! -path '$ROOT/.venv*' ! -path '$ROOT/.git*' ! -path '$ROOT/node_modules*' | sort"
else
  echo "PROJECT DIRECTORY MISSING: $ROOT"
fi

section "5. ROOT VERSUS LIVE APPLICATION SOURCE"
if [ -d "$ROOT" ]; then
  run_sh "Python source declarations and critical logic" "grep -RInE '^(class |def |async def )|FastAPI\\(|@app\\.|@router\\.|sqlite3\\.connect|create_engine|ollama|nomic|chromadb|as_of_timestamp|available_timestamp|target_timestamp' '$ROOT' --include='*.py' --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ 2>/dev/null | head -n 1200"
  run_sh "Root/live source difference" "if [ -d '$ROOT' ] && [ -d '$LIVE' ]; then diff -qr --exclude='__pycache__' --exclude='*.pyc' '$ROOT' '$LIVE' 2>/dev/null | head -n 500; else echo 'Root or live directory missing'; fi"
fi

section "6. PYTHON ENVIRONMENT"
run python3 --version
run python3 -m pip --version
if [ -x "$ROOT/.venv/bin/python" ]; then
  run "$ROOT/.venv/bin/python" --version
  run "$ROOT/.venv/bin/python" -m pip --version
  run "$ROOT/.venv/bin/python" -m pip check
  run "$ROOT/.venv/bin/python" -m pip list --format=columns
  run_sh "Python interpreter and package import paths" "'$ROOT/.venv/bin/python' -c 'import sys,site; print(sys.executable); print(*sys.path,sep=\"\\n\"); print(\"site-packages:\",site.getsitepackages())'"
else
  echo "Project virtualenv not found: $ROOT/.venv/bin/python"
fi

section "7. NODE AND WRANGLER"
run node --version
run npm --version
run npx --version
if [ -x "$WRANGLER" ]; then
  run "$WRANGLER" --version
  run "$WRANGLER" whoami
  run "$WRANGLER" deployments list
  run "$WRANGLER" secret list
else
  echo "Project-local Wrangler not found: $WRANGLER"
fi

section "8. OLLAMA RUNTIME"
run ollama --version
run systemctl status ollama --no-pager
run pgrep -a ollama
if have curl; then
  subsection "Ollama HTTP tags endpoint"
  curl --silent --show-error --max-time 8 http://127.0.0.1:11434/api/tags 2>&1 | redact
  printf '\n'
fi
run ollama list
if have curl; then
  subsection "Ollama model metadata (qwen3:4b and nomic-embed-text if installed)"
  for model in qwen3:4b nomic-embed-text; do
    printf '\nModel: %s\n' "$model"
    curl --silent --show-error --max-time 10 -H 'Content-Type: application/json' \
      -d "{\"name\":\"$model\"}" http://127.0.0.1:11434/api/show 2>&1 | redact
    printf '\n'
  done
fi

section "9. RUNNING APPLICATION PROCESSES"
run_sh "Relevant application processes" "ps -eo pid,ppid,user,comm,%cpu,%mem,rss,vsz,etime,args --sort=-%mem | grep -Ei 'uvicorn|fastapi|quant_hub|henry_hub|ollama|cloudflared|python' | grep -v grep"
run_sh "Process working directories and executable paths" "for p in \$(pgrep -f 'uvicorn|quant_hub|henry_hub|cloudflared|ollama' 2>/dev/null); do [ -r /proc/\$p/cmdline ] || continue; echo PID=\$p; printf 'cmdline='; tr '\\0' ' ' </proc/\$p/cmdline; echo; printf 'cwd='; readlink /proc/\$p/cwd; printf 'exe='; readlink /proc/\$p/exe; done"

section "10. SYSTEMD SERVICES AND TIMERS"
run systemctl --no-pager --type=service --state=running
run systemctl --no-pager --type=timer --all
run systemctl --user --no-pager --type=service --all
run systemctl --user --no-pager --type=timer --all
run systemctl status cloudflared --no-pager
run systemctl --user status cloudflared --no-pager
run systemctl status ollama --no-pager
run systemctl --user status ollama --no-pager

section "11. ENVIRONMENT CONFIGURATION, VALUES REDACTED"
for f in "$ROOT/.env" "$ROOT/.env.local" "$LIVE/.env" "$HOME/.config/environment.d"; do
  if [ -f "$f" ]; then
    subsection "Environment file metadata: $f"
    stat -c '%A %U:%G %s bytes %y %n' "$f"
    subsection "Environment variable names only: $f"
    grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$f" 2>/dev/null | sed -E 's/=.*$/=[REDACTED]/'
  elif [ -d "$f" ]; then
    subsection "Environment directory metadata: $f"
    find "$f" -maxdepth 2 -type f -printf '%M %u:%g %s %p\n' 2>/dev/null
  fi
done

section "12. LIVE DATABASE STRUCTURE AND DATA QUALITY"
if [ -f "$DB" ] && have python3; then
  subsection "SQLite read-only schema and table counts"
  DB_PATH="$DB" python3 - <<'PY'
import os, sqlite3
p=os.environ['DB_PATH']
try:
    con=sqlite3.connect('file:'+p+'?mode=ro', uri=True, timeout=5)
    con.execute('PRAGMA query_only=ON')
    print('database:', p)
    print('integrity_check:', con.execute('PRAGMA integrity_check').fetchone()[0])
    for (name, sql) in con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
        print('\nTABLE', name)
        print(sql or '')
        try: print('row_count:', con.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0])
        except Exception as e: print('row_count_error:', e)
        try:
            cols=con.execute('PRAGMA table_info("'+name.replace('"','""')+'")').fetchall()
            print('columns:', ', '.join(str(c[1])+':'+str(c[2]) for c in cols))
        except Exception as e: print('column_error:', e)
    con.close()
except Exception as e: print('DATABASE_AUDIT_ERROR:', repr(e))
PY
else
  echo "Database missing or Python unavailable: $DB"
fi

section "13. ROOT DATABASE COMPARISON"
for candidate in "$ROOT/henry_hub_pit.db" "$ROOT/data/henry_hub_pit.db" "$ROOT/db/henry_hub_pit.db"; do
  if [ -f "$candidate" ]; then
    stat -c '%n %s bytes modified=%y' "$candidate"
    sha256sum "$candidate" "$DB" 2>/dev/null
  fi
done

section "14. API LOCAL HEALTH AND ROUTE BEHAVIOR"
if have curl; then
  subsection "Local health"
  curl -i --silent --show-error --max-time 10 "$API/health" 2>&1 | redact
  subsection "Local GET execute, expected method rejection"
  curl -i --silent --show-error --max-time 10 "$API/execute" 2>&1 | redact
  subsection "Local OpenAPI document"
  curl --silent --show-error --max-time 15 "$API/openapi.json" 2>&1 | python3 -c 'import json,sys; d=json.load(sys.stdin); print("title:",d.get("info",{}).get("title")); print("version:",d.get("info",{}).get("version")); [print(p, ",".join(v.keys())) for p,v in d.get("paths",{}).items()]' 2>&1
else
  echo "curl unavailable; API checks skipped"
fi

section "15. API SOURCE AND RUNTIME CONFIGURATION ALIGNMENT"
run_sh "Relevant source configuration declarations" "grep -RInE '8090|FastAPI|uvicorn|/health|/execute|openapi|CORSMiddleware|ACCESS|TOKEN' '$ROOT' --include='*.py' --include='*.service' --include='*.toml' --include='*.yaml' --include='*.yml' --exclude-dir=.venv --exclude-dir=.git 2>/dev/null | head -n 600"
run_sh "Root/live source difference" "diff -qr '$ROOT' '$LIVE' --exclude=.venv --exclude=.git --exclude=node_modules 2>/dev/null | head -n 300"

section "16. CLOUDFLARED CONFIGURATION AND TUNNEL"
run cloudflared --version
for f in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml "$HOME/.cloudflared/config.yml" "$HOME/.cloudflared/config.yaml"; do
  if [ -f "$f" ]; then
    subsection "Redacted routing configuration: $f"
    sed -E '/(token|secret|credentials-file|client-secret)/I s#(:[[:space:]]*).*#:\ [REDACTED]#' "$f"
    subsection "Ingress validation: $f"
    run cloudflared tunnel ingress validate --config "$f"
  fi
done
run_sh "Cloudflared tunnel list" "cloudflared tunnel list 2>&1 | redact"
run systemctl status cloudflared --no-pager
run systemctl --user status cloudflared --no-pager
run_sh "Cloudflared processes" "pgrep -a cloudflared"

section "17. CLOUDFLARE DNS AND TLS"
run getent ahosts "$DOMAIN"
if have openssl; then
  subsection "HTTPS certificate"
  timeout 12 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName 2>&1
fi
if have curl; then
  subsection "Protected application health without Access credentials"
  curl -i --silent --show-error --max-time 15 "https://$DOMAIN/health" 2>&1 | redact
  subsection "Protected application execute GET"
  curl -i --silent --show-error --max-time 15 "https://$DOMAIN/execute" 2>&1 | redact
fi

section "18. CLOUDFLARE WORKER CONFIGURATION"
run_sh "Worker source" "find '$ROOT' -maxdepth 5 -type f \\( -iname '*worker*' -o -name 'wrangler.toml' -o -name 'wrangler.json' -o -name 'wrangler.jsonc' \\) ! -path '*/node_modules/*' ! -path '*/.venv/*' -print"
run_sh "Wrangler configuration" "for f in '$ROOT/wrangler.toml' '$ROOT/wrangler.json' '$ROOT/wrangler.jsonc'; do if [ -f \"\$f\" ]; then echo ====\$f; sed -E '/(secret|token|password|key)/I s#(:[[:space:]]*|=[[:space:]]*).*#\\1[REDACTED]#' \"\$f\"; fi; done"
if have curl; then
  subsection "Worker GET behavior"
  curl -i --silent --show-error --max-time 15 "$WORKER" 2>&1 | redact
  subsection "Worker POST without bearer credential, expected rejection"
  curl -i --silent --show-error --max-time 15 -X POST -H 'Content-Type: application/json' -d '{"query":"audit unauthorized request"}' "$WORKER" 2>&1 | redact
fi

section "19. GITHUB AND AUDIT INTEGRATION"
run gh --version
run gh auth status
run_sh "GitHub CLI identity (limited fields)" "gh api user --jq '{login: .login, id: .id}' 2>&1 | redact"
run_sh "Gist command availability" "gh gist --help | head -n 80"
run_sh "Audit directory inventory" "find '$ROOT' -maxdepth 4 -type d \\( -iname '*audit*' -o -iname '*report*' -o -iname '*gist*' \\) -print 2>/dev/null"
run_sh "Gist references in live application" "grep -RInE 'gist.github.com|gh gist|audit_gist_url' '$LIVE' --include='*.py' --include='*.md' --exclude-dir=__pycache__ 2>/dev/null | head -n 300"

section "20. GIT REPOSITORY AND SECRET-EXCLUSION AUDIT"
run git -C "$ROOT" status --short --branch
run git -C "$ROOT" log -5 --oneline --decorate
run git -C "$ROOT" ls-files
run_sh "Remotes, credentials redacted" "git -C '$ROOT' remote -v | sed -E 's#(https?://)[^/@]+:[^/@]+@#\\1[REDACTED]@#g'"
run_sh "Tracked sensitive paths" "git -C '$ROOT' ls-files | grep -Ei '(^|/)(\.env|.*secret.*|.*credential.*|.*token.*|id_rsa|.*\.pem$|.*\.key$)' || true"
run_sh "Ignore rules" "for f in '$ROOT/.gitignore' '$ROOT/.dockerignore'; do [ ! -f \"\$f\" ] || { echo ====\$f; cat \"\$f\"; }; done"

section "21. CREDENTIAL FILE METADATA, NEVER VALUES"
for d in "$ROOT" "$HOME/.cloudflared" "$HOME/.config" /etc/cloudflared; do
  [ -d "$d" ] || continue
  find "$d" -maxdepth 3 -type f \( -iname '*credential*' -o -iname '*secret*' -o -iname '*token*' -o -name '.env' -o -iname '*.pem' -o -iname '*.key' -o -iname '*cert*' \) \
    ! -path '*/node_modules/*' ! -path '*/.venv/*' -printf '%M %u:%g %s bytes %TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null
 done

section "22. PROJECT SPECIFICATION DOCUMENTS"
for f in "$ROOT/Ultimate_Goal.md" "$ROOT/Ultimate_Goal(1).md" "$ROOT/agent-fetch-prompt.odt" "$ROOT/AGENTS.md" "$ROOT/README.md"; do
  if [ -f "$f" ]; then
    subsection "Document metadata: $f"
    stat -c '%n %s bytes modified=%y' "$f"
    case "$f" in
      *.md|*.txt) subsection "Document contents: $f"; sed -n '1,1200p' "$f" ;;
      *.odt) subsection "ODT archive listing: $f"; unzip -l "$f" 2>&1 | head -n 100; if have python3; then python3 - "$f" <<'PY'
import sys, zipfile, xml.etree.ElementTree as ET
p=sys.argv[1]
try:
    with zipfile.ZipFile(p) as z:
        root=ET.fromstring(z.read('content.xml'))
    ns={'text':'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    for para in root.findall('.//text:p',ns):
        t=''.join(para.itertext())
        if t.strip(): print(t)
except Exception as e: print('ODT_READ_ERROR:',e)
PY
fi ;;
    esac
  fi
done

section "23. DATA INGESTION AND MARKET-SOURCE IMPLEMENTATION SEARCH"
run_sh "Source and schedule references outside generated directories" "grep -RInE 'agent|collector|scrap|ingest|schedule|cron|APScheduler|Celery|Cloudflare Queues|EIA|NOAA|FERC|pipeline|LNG|Mont Belvieu|Henry Hub|propane|ethane|available_timestamp|target_timestamp|publication_timestamp|valid_time|as_of_timestamp' '$ROOT' --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ --include='*.py' --include='*.toml' --include='*.yaml' --include='*.yml' --include='*.json' --include='*.md' 2>/dev/null | head -n 1600"

section "24. APPLICATION TEST INVENTORY"
run_sh "Test and validation declarations" "find '$ROOT' -maxdepth 6 -type f \( -iname 'test_*.py' -o -iname '*_test.py' -o -iname '*test*.sh' -o -iname 'pytest.ini' -o -iname 'tox.ini' -o -iname 'pyproject.toml' \) ! -path '*/.venv/*' ! -path '*/node_modules/*' -print"
run_sh "Test markers and validation references" "grep -RInE 'pytest|unittest|assert |TestClient|schema|validation|walk.forward|backtest|point.in.time|PIT' '$ROOT' --include='*.py' --include='*.toml' --include='*.ini' --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ 2>/dev/null | head -n 1000"

section "25. RESOURCE AND LOG HEALTH"
run ps -eo pid,comm,%cpu,%mem,rss,vsz,etime --sort=-%mem
run journalctl -p err -n 100 --no-pager
run journalctl -u cloudflared -n 80 --no-pager
run journalctl -u ollama -n 80 --no-pager
run journalctl --user -p err -n 80 --no-pager

section "26. ENDPOINT AND CONNECTION SUMMARY"
run ss -lntup
if have curl; then
  for url in "$API/health" "$API/openapi.json" "https://$DOMAIN/health" "$WORKER"; do
    subsection "Endpoint status: $url"
    curl -sS -o /dev/null -w 'http_code=%{http_code} remote_ip=%{remote_ip} time_total=%{time_total}\n' --max-time 12 "$url" 2>&1
  done
fi

section "27. AUDIT COMPLETION"
date -Is
printf 'Project: %s\n' "$ROOT"
printf 'Live application: %s\n' "$LIVE"
printf 'Database: %s\n' "$DB"
printf 'No files intentionally modified. No database writes performed. No secrets intentionally displayed.\n'
printf 'NOTE: This is a reconstructed read-only audit based on the supplied report; it is not byte-for-byte recovery of the missing original source.\n'
