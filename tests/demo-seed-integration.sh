#!/usr/bin/env bash
# Integration test: runs demo/provision-demo.sh against a throwaway Kolibri 0.15.5
# data dir (no Pi), checks idempotency, the live-server guard and real logins.
# Needs docker and the koenswings/kolibri:1.0-0.15.5-dev image. PORT default 18877.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-koenswings/kolibri:1.0-0.15.5-dev}"; PORT="${PORT:-18877}"
D="$(mktemp -d)"; NAME="kolibri-demo-it-$$"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker run --rm -v "$D:/d" "$IMAGE" sh -c 'rm -rf /d/*' >/dev/null 2>&1 || true; rm -rf "$D"; }
trap cleanup EXIT
fail() { echo "FAIL: $*"; exit 1; }
report() { grep -o "Users report: {[^}]*}" "$1"; }

demo/provision-demo.sh "$D" > /tmp/it1.log 2>&1 || fail "first run"
report /tmp/it1.log | grep -q "'created': 4" || fail "first run did not create 4 users"
demo/provision-demo.sh "$D" > /tmp/it2.log 2>&1 || fail "second run"
report /tmp/it2.log | grep -q "'updated': 0, 'created': 0" || fail "rerun not idempotent: $(report /tmp/it2.log)"
grep -q "Data errors: \[\]" /tmp/it2.log || fail "rerun data errors"
echo "PASS idempotent rerun"

docker run -d --name "$NAME" --network host -e KOLIBRI_RUN_MODE=docker -e KOLIBRI_HTTP_PORT="$PORT" \
  -v "$D:/root/.kolibri" "$IMAGE" ./kolibri-0.15.5 start --foreground >/dev/null
set +e; demo/provision-demo.sh "$D" >/dev/null 2>&1; rc=$?; set -e
[ "$rc" = 3 ] || fail "live guard rc=$rc"; echo "PASS refuses live server"
for _ in $(seq 90); do curl -sf "localhost:$PORT/" >/dev/null && break; sleep 2; done
F=$(curl -s "localhost:$PORT/api/public/v1/facility/" | python3 -c 'import json,sys;f=json.load(sys.stdin);assert f[0]["name"]=="IDEA Demo School";print(f[0]["id"])') || fail "facility"
for u in admin teacher1 learner1 learner2 learner3; do
  c=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
      -d "{\"username\":\"$u\",\"password\":\"${u}911!\",\"facility\":\"$F\"}" "localhost:$PORT/api/auth/session/")
  [ "$c" = 200 ] || fail "login $u -> $c"
done
echo "PASS logins admin/teacher1/learner1-3 with <account>911!"
echo "ALL PASS"
