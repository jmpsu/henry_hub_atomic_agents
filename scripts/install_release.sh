#!/usr/bin/env bash
set -euo pipefail

PROD_ROOT="/opt/quant-hub"
REPO="jmpsu/henry_hub_atomic_agents"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$TAG" ]]; then
  TAG="$(gh release list --repo "$REPO" --limit 20 --json tagName,isDraft,isPrerelease -q '[.[] | select(.isDraft==false and .isPrerelease==false)][0].tagName')"
fi
[[ -n "$TAG" && "$TAG" != "null" ]] || { echo "No approved stable GitHub Release found" >&2; exit 1; }

IS_VALID="$(gh release view "$TAG" --repo "$REPO" --json isDraft,isPrerelease -q '(.isDraft==false and .isPrerelease==false)')"
[[ "$IS_VALID" == "true" ]] || { echo "Release $TAG is draft or prerelease; refusing deployment" >&2; exit 1; }

VERSION="${TAG#v}"
DL_DIR="$(mktemp -d)"
trap 'rm -rf "$DL_DIR"' EXIT

echo "==> Downloading approved GitHub Release $TAG..."
gh release download "$TAG" --repo "$REPO" --dir "$DL_DIR"

echo "==> Verifying SHA-256 checksums and release manifest..."
"$SCRIPT_DIR/verify_release.sh" "$DL_DIR" "$TAG"

MANIFEST_FILE="$(ls "$DL_DIR"/release-manifest-*.json | head -n1)"
COMMIT="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['git_commit'])" "$MANIFEST_FILE")"
LINUX_TAR="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['artifacts']['linux']['filename'])" "$MANIFEST_FILE")"
WORKER_TAR="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['artifacts']['worker']['filename'])" "$MANIFEST_FILE")"

RELEASE_DIR="$PROD_ROOT/releases/$VERSION"
WORKER_DIR="$PROD_ROOT/releases/${VERSION}-worker"
rm -rf "$RELEASE_DIR" "$WORKER_DIR"
mkdir -p "$RELEASE_DIR" "$WORKER_DIR"

echo "==> Extracting artifacts into $RELEASE_DIR and $WORKER_DIR..."
tar -xzf "$DL_DIR/$LINUX_TAR" -C "$RELEASE_DIR"
tar -xzf "$DL_DIR/$WORKER_TAR" -C "$WORKER_DIR"

ln -sfn "$PROD_ROOT/shared/.env" "$RELEASE_DIR/.env"
for d in chroma_pit_kb raw runtime snapshots; do
  if [[ -e "$PROD_ROOT/shared/$d" ]]; then
    ln -sfn "$PROD_ROOT/shared/$d" "$RELEASE_DIR/$d"
  fi
done

echo "==> Creating and validating Python environment..."
python3 -m venv "$RELEASE_DIR/.venv"
"$RELEASE_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$RELEASE_DIR/.venv/bin/pip" install --quiet -r "$RELEASE_DIR/requirements.txt"
"$RELEASE_DIR/.venv/bin/pip" check

set -a
source "$PROD_ROOT/shared/.env"
set +a

echo "==> Backing up SQLite DB before migrations..."
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DB_BACKUP="$PROD_ROOT/shared/backups/henry_hub_pit_${VERSION}_${TS}.db"
python3 - "$DB_PATH" "$DB_BACKUP" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=30.0)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
res = dst.execute("PRAGMA integrity_check;").fetchone()[0]
src.close()
dst.close()
if res != "ok":
    raise SystemExit(f"Backup integrity_check failed: {res}")
PY

PREV_DIR=""
[[ -L "$PROD_ROOT/current" ]] && PREV_DIR="$(readlink -f "$PROD_ROOT/current" || true)"

echo "==> Applying compatible versioned database migrations..."
"$RELEASE_DIR/.venv/bin/python" "$RELEASE_DIR/migrations/migrate.py" --db "$DB_PATH"

echo "==> Pre-activation validation of $RELEASE_DIR..."
"$RELEASE_DIR/.venv/bin/python" -m compileall -q "$RELEASE_DIR/command_hub.py" "$RELEASE_DIR/release" "$RELEASE_DIR/migrations"

echo "==> Deploying matching Cloudflare Worker..."
"$SCRIPT_DIR/deploy_worker.sh" "$WORKER_DIR" "$PROD_ROOT/shared/state"
PREV_WORKER_VER="$(cat "$PROD_ROOT/shared/state/previous_worker_version" 2>/dev/null || true)"

python3 - "$PROD_ROOT/shared/state/rollback_target.json" "$PREV_DIR" "$PREV_WORKER_VER" "$DB_BACKUP" "$VERSION" "$COMMIT" <<'PY'
import json, sys
out, prev_dir, prev_w, db_bak, ver, commit = sys.argv[1:]
json.dump({
    "prev_release_dir": prev_dir,
    "prev_worker_version": prev_w,
    "db_backup": db_bak,
    "target_version": ver,
    "target_commit": commit,
}, open(out, "w"), indent=2)
PY

rollback_on_fail() {
  echo "ERROR: Coordinated deployment failed; initiating automatic rollback..." >&2
  "$RELEASE_DIR/scripts/rollback_release.sh" --restore-db || true
  exit 1
}
trap rollback_on_fail ERR

echo "==> Switching active Linux release and restarting systemd services..."
ln -sfn "$RELEASE_DIR" "$PROD_ROOT/current"

LEGACY_PIDS="$(ss -tlnp 2>/dev/null | awk '/:8095 /{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | sort -u || true)"
for pid in $LEGACY_PIDS; do
  UNIT_NAME="$(ps -o unit= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [[ -n "$UNIT_NAME" && "$UNIT_NAME" != "quant_markets.service" && "$UNIT_NAME" != "user@"* ]]; then
    sudo systemctl stop "$UNIT_NAME" 2>/dev/null || true
    sudo systemctl disable "$UNIT_NAME" 2>/dev/null || true
  elif [[ "$UNIT_NAME" == "user@"* ]]; then
    USER_UNIT="$(systemctl --user status "$pid" 2>/dev/null | head -n1 | awk '{print $2}' || true)"
    if [[ -n "$USER_UNIT" && "$USER_UNIT" == *.service ]]; then
      systemctl --user stop "$USER_UNIT" 2>/dev/null || true
      systemctl --user disable "$USER_UNIT" 2>/dev/null || true
    else
      kill "$pid" 2>/dev/null || sudo kill "$pid" 2>/dev/null || true
    fi
  else
    kill "$pid" 2>/dev/null || sudo kill "$pid" 2>/dev/null || true
  fi
  sleep 1
done

sudo install -m 0644 "$RELEASE_DIR/deploy/systemd/quant_hub.service" /etc/systemd/system/quant_hub.service
sudo install -m 0644 "$RELEASE_DIR/deploy/systemd/quant_markets.service" /etc/systemd/system/quant_markets.service
sudo systemctl daemon-reload
sudo systemctl enable quant_hub.service quant_markets.service
sudo systemctl restart quant_hub.service quant_markets.service

sleep 3
echo "==> Running unified production verification..."
"$RELEASE_DIR/scripts/verify_production.sh" "$VERSION" "$COMMIT"

trap - ERR
python3 - "$PROD_ROOT/shared/state/active_release.json" "$VERSION" "$TAG" "$COMMIT" "$RELEASE_DIR" <<'PY'
import json, sys
from datetime import datetime, timezone
out, ver, tag, commit, rdir = sys.argv[1:]
json.dump({
    "version": ver,
    "tag": tag,
    "git_commit": commit,
    "release_dir": rdir,
    "promoted_at": datetime.now(timezone.utc).isoformat(),
    "status": "healthy",
}, open(out, "w"), indent=2)
PY
echo "==> Release $TAG promoted to healthy production."
