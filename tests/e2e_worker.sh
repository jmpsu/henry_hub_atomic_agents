#!/usr/bin/env bash
# Positive + negative end-to-end test through Worker -> Access -> tunnel -> hub. Never prints secrets.
# NOTE: a successful /execute call creates one private GitHub gist and one vector node.
set -u
source ~/.config/joey-secrets/joey-secrets.sh && js_load >/dev/null 2>&1
W=https://quant-gateway.joe-metz-psu.workers.dev
fail=0
chk(){ [ "$2" = "$3" ] && echo "PASS $1 ($2)" || { echo "FAIL $1 expected $3 got $2"; fail=1; }; }
chk "no bearer" "$(curl -s -m 20 -o /dev/null -w %{http_code} -X POST $W -d '{}')" 401
chk "bad bearer" "$(curl -s -m 20 -o /dev/null -w %{http_code} -X POST $W -H 'Authorization: Bearer wrong' -d '{}')" 401
chk "origin without Access token" "$(curl -s -m 20 -o /dev/null -w %{http_code} https://quant.joeysvault.app/execute)" 403
resp=$(curl -s -m 150 -w '\n%{http_code}' -X POST $W -H "Authorization: Bearer $MOBILE_COMMAND_SECRET_HENRY_HUB" -H 'content-type: application/json' -d "{\"query\":\"e2e: pipeline freeze during high winter demand\",\"as_of_timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}")
chk "authenticated /execute" "$(printf '%s' "$resp" | tail -n1)" 200
# The response body stays in memory (piped to python); nothing is written to disk.
printf '%s' "$resp" | sed '$d' | python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in ("analysis", "db_rows", "audit_gist_url", "new_vector_node_id"): assert k in d, k
a = d["analysis"]; assert all(x in a for x in ("sql_query", "scenario_delta_bcf", "alpha_thesis"))
assert a["sql_query"].strip().upper().startswith("SELECT"); print("PASS payload shape")'
[ $? -eq 0 ] || fail=1
exit $fail
