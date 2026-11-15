#!/usr/bin/env bash
set -euo pipefail

WORKER_DIR="${1:?Usage: deploy_worker.sh <extracted_worker_dir> [state_dir]}"
STATE_DIR="${2:-/opt/quant-hub/shared/state}"

[[ -f "$WORKER_DIR/worker.js" && -f "$WORKER_DIR/wrangler.toml" ]] || {
  echo "Invalid worker artifact dir: $WORKER_DIR" >&2; exit 1;
}

if [[ -f /opt/quant-hub/shared/.env ]]; then
  set -a
  source /opt/quant-hub/shared/.env
  set +a
fi

if command -v wrangler >/dev/null 2>&1; then
  WRANGLER="wrangler"
elif [[ -x /home/joey/Projects/henry_hub_atomic_agents/node_modules/.bin/wrangler ]]; then
  WRANGLER="/home/joey/Projects/henry_hub_atomic_agents/node_modules/.bin/wrangler"
else
  WRANGLER="npx --yes wrangler"
fi

mkdir -p "$STATE_DIR"

PREV_WORKER_VER="$($WRANGLER deployments list --name quant-gateway --json 2>/dev/null | python3 -c '
import json, sys
try:
    deps = json.load(sys.stdin)
    if deps:
        latest = deps[-1] if isinstance(deps, list) else deps.get("deployments", [{}])[-1]
        vers = latest.get("versions", [])
        if vers:
            print(vers[0].get("version_id", ""))
except Exception:
    pass
' || true)"
printf '%s\n' "$PREV_WORKER_VER" > "$STATE_DIR/previous_worker_version"

META_INFO="$(python3 - "$WORKER_DIR/release_metadata.json" <<'PY'
import json, sys
m = json.loads(open(sys.argv[1]).read())
print(f"{m['version']}|{m['commit']}")
PY
)"
VER="${META_INFO%%|*}"
COMMIT="${META_INFO##*|}"

echo "Deploying Cloudflare Worker quant-gateway v$VER ($COMMIT)..."
(cd "$WORKER_DIR" && $WRANGLER deploy --message "v${VER} commit ${COMMIT}")

echo "Verifying Worker deployment status..."
$WRANGLER deployments status --name quant-gateway >/dev/null
