#!/usr/bin/env bash
set -euo pipefail

PROD_ROOT="/opt/quant-hub"
STATE_FILE="$PROD_ROOT/shared/state/rollback_target.json"
RESTORE_DB="${1:-}"

[[ -f "$STATE_FILE" ]] || { echo "No rollback target state file found at $STATE_FILE" >&2; exit 1; }

INFO="$(python3 - "$STATE_FILE" <<'PY'
import json, sys
d = json.loads(open(sys.argv[1]).read())
print(f"{d.get('prev_release_dir','')}|{d.get('prev_worker_version','')}|{d.get('db_backup','')}")
PY
)"
IFS='|' read -r PREV_DIR PREV_WORKER_VER DB_BACKUP <<<"$INFO"

if [[ -n "$PREV_DIR" && -d "$PREV_DIR" ]]; then
  echo "Restoring Linux release symlink -> $PREV_DIR"
  ln -sfn "$PREV_DIR" "$PROD_ROOT/current"
fi

if [[ "$RESTORE_DB" == "--restore-db" && -n "$DB_BACKUP" && -f "$DB_BACKUP" ]]; then
  set -a
  source "$PROD_ROOT/shared/.env"
  set +a
  echo "Restoring SQLite DB from verified backup $DB_BACKUP -> $DB_PATH"
  python3 - "$DB_BACKUP" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
res = conn.execute("PRAGMA integrity_check;").fetchone()[0]
conn.close()
if res != "ok":
    raise SystemExit(f"Backup integrity_check failed: {res}")
PY
  cp -f "$DB_BACKUP" "$DB_PATH"
fi

if [[ -n "$PREV_WORKER_VER" ]]; then
  if [[ -f "$PROD_ROOT/shared/.env" ]]; then
    set -a; source "$PROD_ROOT/shared/.env"; set +a
  fi
  if command -v wrangler >/dev/null 2>&1; then WRANGLER="wrangler"; else WRANGLER="npx --yes wrangler"; fi
  echo "Rolling back Cloudflare Worker quant-gateway -> $PREV_WORKER_VER"
  $WRANGLER rollback "$PREV_WORKER_VER" --name quant-gateway --yes || true
elif [[ -n "$PREV_DIR" && -d "${PREV_DIR}-worker" ]]; then
  "$(dirname "${BASH_SOURCE[0]}")/deploy_worker.sh" "${PREV_DIR}-worker"
fi

sudo systemctl daemon-reload
sudo systemctl restart quant_hub.service quant_markets.service
echo "Rollback complete."
