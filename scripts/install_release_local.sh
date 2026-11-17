#!/usr/bin/env bash
# Build a release from a committed git ref and install it on this machine WITHOUT sudo and WITHOUT ever restoring the database.
#   scripts/install_release_local.sh <version> [git-ref=HEAD] [--prepare-only]
# Why not scripts/install_release.sh: it needs sudo, and its failure trap runs rollback_release.sh --restore-db, which overwrites the live DB with the
# install-time backup. This script only switches the /opt/quant-hub/current symlink, restarts the two uvicorn processes (SIGKILL: systemd
# Restart=on-failure does not restart on SIGTERM) and reverts the symlink if health checks fail. Cloudflare Worker and systemd units are untouched.
set -euo pipefail
V="${1:?usage: install_release_local.sh <version> [git-ref] [--prepare-only]}"; REF="${2:-HEAD}"; MODE="${3:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; PROD=/opt/quant-hub; REL="$PROD/releases/$V"; DIST="$ROOT/dist/$V"
COMMIT="$(git -C "$ROOT" rev-parse "$REF")"
grep -q "^VERSION = \"$V\"" <(git -C "$ROOT" show "$COMMIT:release/version.py") || { echo "release/version.py at $REF is not $V" >&2; exit 1; }
WT="$(mktemp -d)"; trap 'git -C "$ROOT" worktree remove --force "$WT" 2>/dev/null || true' EXIT
echo "==> build $V from $COMMIT (clean worktree)"; git -C "$ROOT" worktree add -q --detach "$WT/src" "$COMMIT"
bash "$WT/src/scripts/build_release.sh" "$V" "$COMMIT" "$DIST" >/dev/null
bash "$ROOT/scripts/verify_release.sh" "$DIST" "v$V"
set -a; source "$PROD/shared/.env"; set +a
[ -e "$REL" ] && { echo "$REL already exists; refusing to overwrite" >&2; exit 1; }
echo "==> verified DB backup"; BAK="$PROD/shared/backups/henry_hub_pit_${V}_$(date -u +%Y%m%dT%H%M%SZ).db"
python3 - "$DB_PATH" "$BAK" <<'PY'
import sqlite3, sys
s = sqlite3.connect(sys.argv[1], timeout=30); d = sqlite3.connect(sys.argv[2])
with d: s.backup(d)
r = d.execute("PRAGMA integrity_check").fetchone()[0]; print("   backup", sys.argv[2], "integrity", r); assert r == "ok"
PY
echo "==> extract, link shared state, venv"; mkdir -p "$REL"; tar -xzf "$DIST/quant-hub-$V-linux.tar.gz" -C "$REL"
ln -sfn "$PROD/shared/.env" "$REL/.env"; for d in chroma_pit_kb raw runtime snapshots; do [ -e "$PROD/shared/$d" ] && ln -sfn "$PROD/shared/$d" "$REL/$d"; done
python3 -m venv "$REL/.venv"; "$REL/.venv/bin/pip" install --quiet --upgrade pip; "$REL/.venv/bin/pip" install --quiet -r "$REL/requirements.txt"; "$REL/.venv/bin/pip" check
"$REL/.venv/bin/python" "$REL/migrations/migrate.py" --db "$DB_PATH" | tail -1 || true
"$REL/.venv/bin/python" -m compileall -q "$REL/command_hub.py" "$REL/markets_hub.py" "$REL/markets_engine.py" "$REL/kb_ingest.py" "$REL/release" "$REL/migrations"
( cd "$REL" && "$REL/.venv/bin/python" -c "import markets_hub, command_hub, markets_engine; print('   imports ok')" )
[ "$MODE" = "--prepare-only" ] && { echo "prepared $REL (not activated)"; exit 0; }
echo "==> activate"; PREV="$(readlink -f "$PROD/current")"
python3 - "$PROD/shared/state/rollback_target.json" "$PREV" "$BAK" "$V" "$COMMIT" <<'PY'
import json, sys
f = sys.argv[1]; d = json.load(open(f)); d.update({"prev_release_dir": sys.argv[2], "db_backup": sys.argv[3], "target_version": sys.argv[4], "target_commit": sys.argv[5]}); json.dump(d, open(f, "w"), indent=2)
PY
H="$(systemctl show -p MainPID --value quant_hub.service)"; M="$(systemctl show -p MainPID --value quant_markets.service)"
ln -sfn "$REL" "$PROD/current"; kill -9 $H $M
ver() { curl -fsS -m 3 "$1" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('release_version'))" 2>/dev/null || true; }
for i in $(seq 1 30); do sleep 2; a="$(ver http://127.0.0.1:8090/health)"; b="$(ver http://127.0.0.1:8095/api/health)"; echo "   t+$((i*2))s hub=$a markets=$b"; [ "$a" = "$V" ] && [ "$b" = "$V" ] && { echo "==> $V healthy; current -> $(readlink -f "$PROD/current")"; exit 0; }; done
echo "health check failed: reverting symlink to $PREV (database untouched)" >&2
ln -sfn "$PREV" "$PROD/current"; kill -9 "$(systemctl show -p MainPID --value quant_hub.service)" "$(systemctl show -p MainPID --value quant_markets.service)" 2>/dev/null || true; exit 1
