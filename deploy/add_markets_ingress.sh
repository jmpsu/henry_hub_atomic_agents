#!/usr/bin/env bash
# Adds markets.joeysvault.app and ngl.joeysvault.app -> http://127.0.0.1:8095 (read-only markets_hub) to the cloudflared
# ingress, ahead of the catch-all 404. Idempotent: does nothing if both hostnames are already present.
# Backs up the current config, validates the new one with cloudflared, restores the backup if validation fails,
# then restarts cloudflared. Run as root:   sudo bash deploy/add_markets_ingress.sh
set -euo pipefail
CFG=/etc/cloudflared/config.yml
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
if grep -q "hostname: markets.joeysvault.app" "$CFG" && grep -q "hostname: ngl.joeysvault.app" "$CFG"; then
  echo "already present; nothing to do"; exit 0
fi
BAK="$CFG.bak.$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$CFG" "$BAK"
python3 - "$CFG" <<'PY'
import sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
entry = []
for h in ("markets.joeysvault.app", "ngl.joeysvault.app"):
    if f"hostname: {h}" not in "".join(lines):
        entry += [f"  - hostname: {h}\n", "    service: http://127.0.0.1:8095\n"]
# insert just before the catch-all rule (the first "- service:" line with no hostname above it in the ingress list)
for i, l in enumerate(lines):
    if l.strip().startswith("- service:") and "http_status" in l:
        lines[i:i] = entry
        break
else:
    sys.exit("catch-all ingress rule not found; refusing to edit")
open(p, "w").write("".join(lines))
PY
if ! cloudflared --config "$CFG" tunnel ingress validate; then
  echo "validation failed; restoring $BAK"; cp -p "$BAK" "$CFG"; exit 1
fi
cloudflared --config "$CFG" tunnel ingress rule https://markets.joeysvault.app/api/health
cloudflared --config "$CFG" tunnel ingress rule https://ngl.joeysvault.app/api/state.json
systemctl restart cloudflared
sleep 3
systemctl is-active cloudflared
echo "backup: $BAK"
