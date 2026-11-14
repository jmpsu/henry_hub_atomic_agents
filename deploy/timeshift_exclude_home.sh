#!/usr/bin/env bash
# Stop Timeshift from copying /home/joey and /root into SYSTEM snapshots on the same disk it protects.
#
# Finding (2026-11-14): /etc/timeshift/timeshift.json "exclude" starts with "+ /home/joey/**" and "+ /root/**". In Timeshift's
# filter syntax a leading "+" means INCLUDE, so every system snapshot also carries the whole home directory: the configured
# snapshot size is ~163 GB and /timeshift holds 256 GB of the 468 GB disk, which is what filled the disk on 2026-11-13.
#
# What this script does:  backs up timeshift.json, removes ONLY those two include rules (Timeshift's default is to exclude
# home directories), validates the result as JSON, and restores the backup on any error. It deletes NO snapshots.
# Consequences:  future system snapshots shrink to the OS (typically single-digit GB). /home is then NOT in Timeshift; keep
# a separate home backup (e.g. Deja Dup / rsync to another disk). Existing large snapshots stay recoverable until normal
# retention (daily 2, weekly 2) rotates them out over the next ~2 weeks; to reclaim space sooner, list them with
# `sudo timeshift --list` and delete a specific one with `sudo timeshift --delete --snapshot '<name>'` only after you have
# confirmed a separate home backup exists.
# Run:  sudo bash deploy/timeshift_exclude_home.sh
set -euo pipefail
CFG=/etc/timeshift/timeshift.json
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
BAK="$CFG.bak.$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$CFG" "$BAK"
python3 - "$CFG" <<'PY' || { echo "edit failed; restoring $BAK"; cp -p "$BAK" "$CFG"; exit 1; }
import json, sys
p = sys.argv[1]
d = json.load(open(p))
before = list(d.get("exclude", []))
d["exclude"] = [e for e in before if e not in ("+ /home/joey/**", "+ /root/**")]
removed = [e for e in before if e not in d["exclude"]]
json.dump(d, open(p, "w"), indent=2)
json.load(open(p))                                       # validate
print("removed include rules:", removed or "none (already removed)")
print("exclude now:", d["exclude"])
PY
echo "backup: $BAK"
echo "snapshots (unchanged):"
timeshift --list | sed -n '/^Num/,$p'
