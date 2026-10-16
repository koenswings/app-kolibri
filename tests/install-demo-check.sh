#!/usr/bin/env bash
# Checks a running demo Kolibri (after demo/install-demo.sh): logins and the IDEA-DEMO resources.
# Usage: tests/install-demo-check.sh http://127.0.0.1:<port>   (exit 0 = all PASS)
set -euo pipefail
U="${1:?url}"; fail() { echo "FAIL: $*"; exit 1; }
F=$(curl -s "$U/api/public/v1/facility/" | python3 -c 'import json,sys;f=json.load(sys.stdin);assert [x["name"] for x in f]==["IDEA Demo School"],f;print(f[0]["id"])') || fail "facility list must be exactly IDEA Demo School"
echo "PASS only facility: IDEA Demo School"
login() { local b; if [ $# -ge 2 ]; then b="{\"username\":\"$1\",\"password\":\"$2\",\"facility\":\"$F\"}"; else b="{\"username\":\"$1\",\"facility\":\"$F\"}"; fi
  curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$b" "$U/api/auth/session/"; }
for u in admin teacher1 teacher2; do
  [ "$(login $u "${u}911!")" = 200 ] || fail "$u with ${u}911!"
  [ "$(login $u wrong-pass)" = 401 ] || fail "$u wrong password not refused"
done; echo "PASS admin/teacher1/teacher2 sign in with <account>911! (wrong password refused)"
for u in learner1 learner2 learner3; do [ "$(login $u)" = 200 ] || fail "$u username-only"; done
echo "PASS learner1-3 sign in with username only"
curl -s "$U/api/public/v1/channels" | python3 -c '
import json,sys
want={"54c4d96f29e751668f276109eebe68c6":6,"45fc46386f76517bb3e86fb3cb235ad9":12,"6dc027c8b780532a9a9d16fd7a3a008a":7}
ch={c["id"]:c for c in json.load(sys.stdin)}
tot=0
for cid,n in want.items():
    c=ch.get(cid); assert c, "missing channel "+cid
    have=c.get("total_resource_count"); assert have==n, (c["name"],have,n)
    print("  %s v%s: %d resources" % (c["name"], c.get("version"), have)); tot+=have
assert tot==25, tot
print("PASS 3 IDEA-DEMO channels, %d resources" % tot)' || fail "channels"
