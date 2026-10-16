#!/usr/bin/env bash
# Integration test: runs demo/provision-demo.sh against throwaway Kolibri 0.15.5
# data dirs (no Pi app data), in two scenarios:
#   A. empty device
#   B. device already provisioned with "Other School" (otheradmin, learner other1)
# and checks idempotency, the live-server guard, real logins, that demo users land
# only in IDEA Demo School, and (B) that Other School and its users are untouched.
# Needs docker and the koenswings/kolibri:1.0-0.15.5-dev image. PORT default 18877.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-koenswings/kolibri:1.0-0.15.5-dev}"; PORT="${PORT:-18877}"
NAME="kolibri-demo-it-$$"; DIRS=()
wipe() { docker run --rm -v "$1:/d" "$IMAGE" sh -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true; rm -rf "$1" "$1".*; }
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; for d in "${DIRS[@]}"; do wipe "$d"; done; rm -f /tmp/it-$$-*.log; }
trap cleanup EXIT
fail() { echo "FAIL[$SC]: $*"; exit 1; }
report() { grep -o "Users report: {[^}]*}" "$1"; }
one() { docker run --rm --network none -e KOLIBRI_RUN_MODE=docker -v "$D:/root/.kolibri" -v "$PWD/tests:/t:ro" "$IMAGE" ./kolibri-0.15.5 manage "$@"; }
snap() { docker run --rm --network none -v "$D:/root/.kolibri" -v "$PWD/tests:/t:ro" --entrypoint python3 "$IMAGE" /t/snapshot_other.py /root/.kolibri; }

login() {  # login FACILITY_ID USER [PASSWORD] -> HTTP status; no PASSWORD = username-only
  local body
  if [ $# -ge 3 ]; then body="{\"username\":\"$2\",\"password\":\"$3\",\"facility\":\"$1\"}"
  else body="{\"username\":\"$2\",\"facility\":\"$1\"}"; fi
  curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$body" "localhost:$PORT/api/auth/session/"
}
setting() {  # setting FACILITY_ID true|false -> HTTP status (admin of that facility, throwaway instance only)
  local cj="$D.cj"; curl -s -c "$cj" -o /dev/null -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"admin911!\",\"facility\":\"$1\"}" "localhost:$PORT/api/auth/session/"
  local tok ds; tok=$(awk '/csrftoken/{print $7}' "$cj")
  ds=$(curl -s -b "$cj" "localhost:$PORT/api/auth/facilitydataset/?facility_id=$1" | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
  curl -s -b "$cj" -o /dev/null -w '%{http_code}' -X PATCH -H 'Content-Type: application/json' -H "X-CSRFToken: $tok" \
    -H "Referer: http://localhost:$PORT/" -d "{\"learner_can_login_with_no_password\": $2}" \
    "localhost:$PORT/api/auth/facilitydataset/$ds/"; rm -f "$cj"
}
getsetting() {  # getsetting FACILITY_ID ADMINUSER ADMINPASS
  local cj="$D.cj2"; curl -s -c "$cj" -o /dev/null -H 'Content-Type: application/json' \
    -d "{\"username\":\"$2\",\"password\":\"$3\",\"facility\":\"$1\"}" "localhost:$PORT/api/auth/session/"
  curl -s -b "$cj" "localhost:$PORT/api/auth/facilitydataset/?facility_id=$1" | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["learner_can_login_with_no_password"])'
  rm -f "$cj"
}

scenario() {  # scenario A|B
  SC=$1; D="$(mktemp -d)"; DIRS+=("$D"); local L1=/tmp/it-$$-$SC-1.log L2=/tmp/it-$$-$SC-2.log
  if [ "$SC" = B ]; then
    printf '{"learner_can_login_with_no_password": false}\n' > "$D/fs.json"
    one provisiondevice --facility "Other School" --superusername otheradmin --superuserpassword 'otheradmin911!' \
      --preset nonformal --language_id fr-fr --facility_settings /root/.kolibri/fs.json --noinput > "$D.pre" 2>&1 || { tail -5 "$D.pre"; fail "pre-provision"; }
    printf 'UUID,USERNAME,PASSWORD,FULL_NAME,USER_TYPE,IDENTIFIER,BIRTH_YEAR,GENDER,ENROLLED_IN,ASSIGNED_TO\n,other1,otherpw1,Other One,LEARNER,,,,Class X,\n' > "$D/o.csv"
    one bulkimportusers /root/.kolibri/o.csv > "$D.pre" 2>&1 || { tail -5 "$D.pre"; fail "pre-import other1"; }
    BEFORE=$(snap) || fail "snapshot before"
    echo "$BEFORE" | grep -q '"Other School"' || fail "pre-provision missing Other School"
  fi
  demo/provision-demo.sh "$D" > "$L1" 2>&1 || { cat "$L1"; fail "first run"; }
  report "$L1" | grep -q "'created': 5" || fail "first run did not create 5 users: $(report "$L1")"
  demo/provision-demo.sh "$D" > "$L2" 2>&1 || { cat "$L2"; fail "second run"; }
  grep -q "not running provisiondevice" "$L2" || fail "rerun ran provisiondevice"
  report "$L2" | grep -q "'updated': 0, 'created': 0" || fail "rerun not idempotent: $(report "$L2")"
  grep -q "Data errors: \[\]" "$L2" || fail "rerun data errors"
  echo "PASS[$SC] idempotent rerun (provisiondevice skipped once IDEA Demo School exists)"

  AFTER=$(snap) || fail "snapshot after"
  python3 - "$SC" "$AFTER" "${BEFORE:-}" <<'PY' || fail "data check"
import json, sys
sc, after = sys.argv[1], json.loads(sys.argv[2])
demo = {"admin", "teacher1", "teacher2", "learner1", "learner2", "learner3"}
inn = {u[1] for u in after["users"] if u[0] == "IDEA Demo School"}
assert inn == demo, ("IDEA Demo School users", inn)
for u in after["users"]:
    if u[1] in demo:
        assert u[0] == "IDEA Demo School", ("demo user outside IDEA Demo School", u)
if sc == "A":
    assert after["facilities"] == ["IDEA Demo School"], after["facilities"]
else:
    before = json.loads(sys.argv[3])
    assert after["facilities"] == ["IDEA Demo School", "Other School"], after["facilities"]
    ob = [u for u in before["users"] if u[0] == "Other School"]
    oa = [u for u in after["users"] if u[0] == "Other School"]
    assert {u[1] for u in ob} == {"otheradmin", "other1"}, ob
    assert ob == oa, ("Other School users changed", ob, oa)  # same ids and password hashes
    for k in ("other_dataset", "other_collections", "other_memberships", "default_facility", "device"):
        assert before[k] == after[k], (k, before[k], after[k])
    assert after["default_facility"] == [["Other School"]], after["default_facility"]
print("ok")
PY
  if [ "$SC" = B ]; then echo "PASS[B] Other School, otheradmin, other1, their memberships, dataset and device settings unchanged"; fi
  echo "PASS[$SC] demo users only in IDEA Demo School"

  docker run -d --name "$NAME" --network host -e KOLIBRI_RUN_MODE=docker -e KOLIBRI_HTTP_PORT="$PORT" \
    -v "$D:/root/.kolibri" "$IMAGE" ./kolibri-0.15.5 start --foreground >/dev/null
  set +e; demo/provision-demo.sh "$D" >/dev/null 2>&1; rc=$?; set -e
  [ "$rc" = 3 ] || fail "live guard rc=$rc"; echo "PASS[$SC] refuses live server"
  for _ in $(seq 90); do curl -sf "localhost:$PORT/" >/dev/null && break; sleep 2; done
  local F O=""
  F=$(curl -s "localhost:$PORT/api/public/v1/facility/" | python3 -c 'import json,sys;print([f["id"] for f in json.load(sys.stdin) if f["name"]=="IDEA Demo School"][0])') || fail "facility"
  [ "$(getsetting "$F" admin 'admin911!')" = True ] || fail "learner_can_login_with_no_password not on in IDEA Demo School"
  echo "PASS[$SC] IDEA Demo School: learner_can_login_with_no_password on"
  for u in admin teacher1 teacher2; do
    c=$(login "$F" "$u" "${u}911!"); [ "$c" = 200 ] || fail "login $u with ${u}911! -> $c"
    c=$(login "$F" "$u" "wrong-pass"); [ "$c" = 401 ] || fail "login $u with a wrong password -> $c (want 401)"
    c=$(login "$F" "$u"); [ "$c" != 200 ] || fail "login $u without a password -> 200"
  done
  echo "PASS[$SC] admin/teacher1/teacher2 need <account>911!"
  for u in learner1 learner2 learner3; do
    c=$(login "$F" "$u"); [ "$c" = 200 ] || fail "learner $u username-only -> $c"
    c=$(login "$F" "$u" "anything-wrong"); [ "$c" = 200 ] || fail "learner $u with a random password -> $c"
  done
  echo "PASS[$SC] learners sign in with username only"
  c=$(setting "$F" false); [ "$c" = 200 ] || fail "switch setting off -> $c"
  for u in learner1 learner2 learner3; do
    c=$(login "$F" "$u" "${u}911!"); [ "$c" = 200 ] || fail "setting off: $u with ${u}911! -> $c"
    c=$(login "$F" "$u" "wrong-pass"); [ "$c" = 401 ] || fail "setting off: $u wrong -> $c"
  done
  c=$(setting "$F" true); [ "$c" = 200 ] || fail "switch setting back on -> $c"
  c=$(login "$F" learner1); [ "$c" = 200 ] || fail "setting back on: learner1 -> $c"
  echo "PASS[$SC] stored learner fallback learnerN911! (setting off), username-only after switching back"
  if [ "$SC" = B ]; then
    O=$(curl -s "localhost:$PORT/api/public/v1/facility/" | python3 -c 'import json,sys;print([f["id"] for f in json.load(sys.stdin) if f["name"]=="Other School"][0])') || fail "other facility"
    [ "$(getsetting "$O" otheradmin 'otheradmin911!')" = False ] || fail "Other School setting changed"
    c=$(login "$O" other1 otherpw1); [ "$c" = 200 ] || fail "other1 login -> $c"
    c=$(login "$O" other1); [ "$c" != 200 ] || fail "other1 username-only -> 200 (Other School must still need passwords)"
    c=$(login "$O" otheradmin 'otheradmin911!'); [ "$c" = 200 ] || fail "otheradmin login -> $c"
    for u in teacher1 learner1; do c=$(login "$O" "$u" "${u}911!"); [ "$c" != 200 ] || fail "$u exists in Other School"; done
    echo "PASS[B] Other School logins as before (other1 needs its password, setting still off); demo users absent there"
  fi
  docker rm -f "$NAME" >/dev/null
}

scenario A
scenario B
echo "ALL PASS"
