#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import sys; sys.path.insert(0, "release"); import version; print(version.VERSION)')}"
GIT_COMMIT="${2:-$(git -C "$ROOT" rev-parse HEAD)}"
OUT_DIR="${3:-$ROOT/dist/$VERSION}"
TAG="v$VERSION"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

TMP_STAGE="$(mktemp -d)"
trap 'rm -rf "$TMP_STAGE"' EXIT

LINUX_STAGE="$TMP_STAGE/linux"
WORKER_STAGE="$TMP_STAGE/worker"
mkdir -p "$LINUX_STAGE" "$WORKER_STAGE"

tar -C "$ROOT" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.wrangler' \
  --exclude='chroma_pit_kb' \
  --exclude='raw' \
  --exclude='runtime' \
  --exclude='snapshots' \
  --exclude='backups' \
  --exclude='audit' \
  --exclude='artifacts' \
  --exclude='dist' \
  --exclude='*.db' \
  --exclude='*.db-*' \
  --exclude='*.sqlite3' \
  --exclude='.env' \
  -cf - . | tar -C "$LINUX_STAGE" -xf -

python3 - "$LINUX_STAGE" "$VERSION" "$GIT_COMMIT" "$TAG" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

stage, ver, commit, tag = sys.argv[1:]
meta = {
    "version": ver,
    "commit": commit,
    "tag": tag,
    "built_at": datetime.now(timezone.utc).isoformat(),
}
Path(stage, "release_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
PY

LINUX_TAR="quant-hub-${VERSION}-linux.tar.gz"
tar -C "$LINUX_STAGE" --sort=name --numeric-owner -czf "$OUT_DIR/$LINUX_TAR" .

cp "$ROOT/worker.js" "$WORKER_STAGE/worker.js"
cp "$ROOT/wrangler.toml" "$WORKER_STAGE/wrangler.toml"
for f in package.json package-lock.json; do
  [[ -f "$ROOT/$f" ]] && cp "$ROOT/$f" "$WORKER_STAGE/$f"
done

python3 - "$WORKER_STAGE/wrangler.toml" "$WORKER_STAGE/release_metadata.json" "$VERSION" "$GIT_COMMIT" "$TAG" <<'PY'
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path

toml_path, meta_path, ver, commit, tag = sys.argv[1:]
txt = Path(toml_path).read_text(encoding="utf-8")
if re.search(r'(?m)^RELEASE_VERSION\s*=', txt):
    txt = re.sub(r'(?m)^RELEASE_VERSION\s*=.*$', f'RELEASE_VERSION = "{ver}"', txt)
else:
    txt = txt.replace("[vars]\n", f'[vars]\nRELEASE_VERSION = "{ver}"\n', 1)

if re.search(r'(?m)^RELEASE_COMMIT\s*=', txt):
    txt = re.sub(r'(?m)^RELEASE_COMMIT\s*=.*$', f'RELEASE_COMMIT = "{commit}"', txt)
else:
    txt = txt.replace("[vars]\n", f'[vars]\nRELEASE_COMMIT = "{commit}"\n', 1)

Path(toml_path).write_text(txt, encoding="utf-8")
Path(meta_path).write_text(json.dumps({
    "version": ver,
    "commit": commit,
    "tag": tag,
    "built_at": datetime.now(timezone.utc).isoformat(),
}, indent=2) + "\n", encoding="utf-8")
PY

WORKER_TAR="quant-gateway-${VERSION}-worker.tar.gz"
tar -C "$WORKER_STAGE" --sort=name --numeric-owner -czf "$OUT_DIR/$WORKER_TAR" .

MANIFEST_FILE="release-manifest-${VERSION}.json"
python3 - "$ROOT" "$OUT_DIR" "$LINUX_TAR" "$WORKER_TAR" "$MANIFEST_FILE" "$VERSION" "$GIT_COMMIT" "$TAG" <<'PY'
import hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

root, out_dir, linux_tar, worker_tar, manifest_name, ver, commit, tag = sys.argv[1:]
out = Path(out_dir)

def file_meta(name: str) -> dict:
    p = out / name
    data = p.read_bytes()
    return {
        "filename": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }

wtoml = Path(root, "wrangler.toml").read_text(encoding="utf-8")
wname = re.search(r'(?m)^name\s*=\s*"([^"]+)"', wtoml).group(1)
compat = re.search(r'(?m)^compatibility_date\s*=\s*"([^"]+)"', wtoml).group(1)
queues = sorted(set(re.findall(r'(?m)^(?:queue|dead_letter_queue)\s*=\s*"([^"]+)"', wtoml)))
crons_match = re.search(r'(?m)^crons\s*=\s*(\[[^\]]+\])', wtoml)
crons = json.loads(crons_match.group(1)) if crons_match else []

migs = sorted(p.name for p in Path(root, "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
latest_mig = migs[-1].split("_", 1)[0] if migs else "0000"

manifest = {
    "schema_version": "1.0",
    "version": ver,
    "tag": tag,
    "git_commit": commit,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "repository": "jmpsu/henry_hub_atomic_agents",
    "artifacts": {
        "linux": file_meta(linux_tar),
        "worker": file_meta(worker_tar),
    },
    "worker": {
        "name": wname,
        "compatibility_date": compat,
        "queues": queues,
        "crons": crons,
    },
    "migrations": {
        "latest_version": latest_mig,
        "files": migs,
    },
}
(out / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

cat > "$OUT_DIR/RELEASE_NOTES.md" <<MD
# Coordinated Production Release $TAG

- **Version:** \`$VERSION\`
- **Git Commit:** \`$GIT_COMMIT\`
- **Linux Target:** \`quant_hub.service\` (127.0.0.1:8090) & \`quant_markets.service\` (127.0.0.1:8095)
- **Cloudflare Target:** \`quant-gateway\` Worker
- **Artifacts:** \`$LINUX_TAR\`, \`$WORKER_TAR\`, \`$MANIFEST_FILE\`, \`SHA256SUMS\`
MD

(cd "$OUT_DIR" && sha256sum "$LINUX_TAR" "$WORKER_TAR" "$MANIFEST_FILE" "RELEASE_NOTES.md" > SHA256SUMS)
echo "Built release artifacts in $OUT_DIR"
