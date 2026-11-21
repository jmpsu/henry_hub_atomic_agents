#!/usr/bin/env bash
set -euo pipefail

RELEASE_DIR="${1:?Usage: verify_release.sh <release_dir> [expected_tag]}"
EXPECTED_TAG="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_FILE="$ROOT/release/manifest.schema.json"

cd "$RELEASE_DIR"
[[ -f SHA256SUMS ]] || { echo "Missing SHA256SUMS in $RELEASE_DIR" >&2; exit 1; }
sha256sum -c SHA256SUMS

MANIFEST_FILE="$(ls release-manifest-*.json | head -n1)"
[[ -n "$MANIFEST_FILE" && -f "$MANIFEST_FILE" ]] || { echo "Missing release-manifest-*.json" >&2; exit 1; }

python3 - "$MANIFEST_FILE" "$SCHEMA_FILE" "$EXPECTED_TAG" <<'PY'
import hashlib, json, re, sys
from pathlib import Path

manifest_path, schema_path, expected_tag = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))

try:
    import jsonschema
    jsonschema.validate(instance=manifest, schema=schema)
except ImportError:
    for req in schema["required"]:
        assert req in manifest, f"Missing key {req}"
    assert re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", manifest["version"])
    assert re.match(r"^v[0-9]+\.[0-9]+\.[0-9]+$", manifest["tag"])
    assert re.match(r"^[0-9a-f]{40}$", manifest["git_commit"])

if expected_tag and manifest["tag"] != expected_tag:
    raise SystemExit(f"Release identity mismatch: expected {expected_tag}, got {manifest['tag']}")

for key in ("linux", "worker"):
    art = manifest["artifacts"][key]
    p = Path(art["filename"])
    if not p.is_file():
        raise SystemExit(f"Missing artifact declared in manifest: {p}")
    data = p.read_bytes()
    if len(data) != art["size_bytes"]:
        raise SystemExit(f"Size mismatch for {p}")
    if hashlib.sha256(data).hexdigest() != art["sha256"]:
        raise SystemExit(f"SHA256 mismatch for {p}")

print(f"Release manifest and artifacts verified: {manifest['tag']} ({manifest['git_commit'][:12]})")
PY
