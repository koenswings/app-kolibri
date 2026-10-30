#!/usr/bin/env bash
# Integration test: runs demo/provision-demo.sh against throwaway Kolibri (default the pinned 0.19.5 image; IMAGE=koenswings/kolibri:1.0-0.15.5-dev also works)
# data dirs (no Pi app data), in two scenarios:
#   A. empty demo instance (<tmp>/kolibri-demo/data/kolibri): seed, rerun, logins
#   B. device provisioned with "Other School" (otheradmin, learner other1): REFUSED
#      (exit 6) and every file in the data dir byte-for-byte unchanged (sha256)
#   C. empty dir without any demo marker: REFUSED (exit 5), nothing created
# Needs docker and $IMAGE. PORT default 18877.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-koenswings/kolibri:1.1-0.19.5}"; export IMAGE; PORT="${PORT:-18877}"
NAME="kolibri-demo-it-$$"; DIRS=()
wipe() { docker run --rm --network none -v "$1:/d" --entrypoint sh "$IMAGE" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true; rm -rf "$1" "$1".*; }
sums() { docker run --rm --network none -v "$1:/d:ro" --entrypoint sh "$IMAGE" -c 'cd /d && find . -type f | sort | xargs -r sha256sum'; }
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; for d in "${DIRS[@]}"; do wipe "$d"; done; rm -f /tmp/it-$$-*.log; }
trap cleanup EXIT
fail() { echo "FAIL[$SC]: $*"; exit 1; }
report() { grep -o "Users report: {[^}]*}" "$1"; }
# Find the Kolibri binary like kolibri-start.sh: KOLIBRI_BIN, then `kolibri` on PATH, then ./kolibri-*
# (0.15.5 image: ./kolibri-0.15.5; official 0.19.5: kolibri). --entrypoint sh bypasses the official
# image's /entrypoint.sh, as compose.yaml does.
# shellcheck disable=SC2016  # expanded inside the container
KRUN='B=${KOLIBRI_BIN:-}; if [ -z "$B" ]; then if command -v kolibri >/dev/null 2>&1; then B=kolibri; else for f in ./kolibri-*; do [ -x "$f" ] && B=$f; done; fi; fi; [ -n "$B" ] || { echo "no Kolibri binary (set KOLIBRI_BIN)" >&2; exit 78; }; "$B" "$@"'
one() { docker run --rm --network none -e KOLIBRI_RUN_MODE=docker -e KOLIBRI_HOME=/root/.kolibri -v "$D:/root/.kolibri" -v "$PWD/tests:/t:ro" --entrypoint sh "$IMAGE" -c "$KRUN" kolibri manage "$@"; }
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

refused() {  # B: another facility -> refused, unchanged
  SC=B; D="$(mktemp -d)"; DIRS+=("$D")
  printf '{"learner_can_login_with_no_password": false}\n' > "$D/fs.json"
  one provisiondevice --facility "Other School" --superusername otheradmin --superuserpassword 'otheradmin911!' \
    --preset nonformal --language_id fr-fr --facility_settings /root/.kolibri/fs.json --noinput > "$D.pre" 2>&1 || { tail -5 "$D.pre"; fail "pre-provision"; }
  printf 'UUID,USERNAME,PASSWORD,FULL_NAME,USER_TYPE,IDENTIFIER,BIRTH_YEAR,GENDER,ENROLLED_IN,ASSIGNED_TO\n,other1,otherpw1,Other One,LEARNER,,,,Class X,\n' > "$D/o.csv"
  one bulkimportusers /root/.kolibri/o.csv > "$D.pre" 2>&1 || { tail -5 "$D.pre"; fail "pre-import other1"; }
  snap | grep -q '"Other School"' || fail "pre-provision missing Other School"
  local before after rc
  before=$(sums "$D"); echo "$before" | grep -q ' ./db.sqlite3$' || fail "no db.sqlite3 to checksum"
  set +e; demo/provision-demo.sh --demo-instance "$D" > "$D.log" 2>&1; rc=$?; set -e
  [ "$rc" = 6 ] || { cat "$D.log"; fail "Other School device not refused (rc=$rc, want 6)"; }
  grep -q "REFUSED: .* not a dedicated demo instance" "$D.log" || fail "no clear refusal message"
  ! grep -qE "manage (provisiondevice|bulk)" "$D.log" || fail "a write command ran"
  after=$(sums "$D")
  [ "$before" = "$after" ] || { diff <(echo "$before") <(echo "$after"); fail "data dir changed"; }
  echo "PASS[B] device with Other School REFUSED (exit 6); all $(echo "$after" | wc -l) files byte-for-byte unchanged (sha256, incl. db.sqlite3)"
}

nomarker() {  # C: no demo marker -> refused before anything runs
  SC=C; D="$(mktemp -d)"; DIRS+=("$D"); local rc
  set +e; demo/provision-demo.sh "$D" > "$D.log" 2>&1; rc=$?; set -e
  [ "$rc" = 5 ] || { cat "$D.log"; fail "unmarked dir not refused (rc=$rc, want 5)"; }
  [ -z "$(ls -A "$D")" ] || fail "unmarked dir changed"
  echo "PASS[C] no demo marker REFUSED (exit 5), nothing created"
}

scenario() {  # A: empty demo instance, marked by its folder name
  SC=A; local R; R="$(mktemp -d)"; DIRS+=("$R"); D="$R/kolibri-demo/data/kolibri"; mkdir -p "$D"
  local L1=/tmp/it-$$-$SC-1.log L2=/tmp/it-$$-$SC-2.log
  demo/provision-demo.sh "$D" > "$L1" 2>&1 || { cat "$L1"; fail "first run"; }
  report "$L1" | grep -q "'created': 5" || fail "first run did not create 5 users: $(report "$L1")"
  demo/provision-demo.sh "$D" > "$L2" 2>&1 || { cat "$L2"; fail "second run"; }
  grep -q "Demo instance marker: instance folder kolibri-demo" "$L1" || fail "folder marker not used"
  grep -q "not running provisiondevice" "$L2" || fail "rerun ran provisiondevice"
  # key order differs per Kolibri version (0.15.5: updated, created; 0.19.5: created, updated, deleted)
  R2=$(report "$L2"); { grep -q "'created': 0" <<<"$R2" && grep -q "'updated': 0" <<<"$R2"; } || fail "rerun not idempotent: $(report "$L2")"
  grep -q "Data errors: \[\]" "$L2" || fail "rerun data errors"
  echo "PASS[$SC] idempotent rerun (provisiondevice skipped once IDEA Demo School exists)"

  AFTER=$(snap) || fail "snapshot after"
  python3 - "$SC" "$AFTER" <<'PY' || fail "data check"
import json, sys
sc, after = sys.argv[1], json.loads(sys.argv[2])
demo = {"admin", "teacher1", "teacher2", "learner1", "learner2", "learner3"}
inn = {u[1] for u in after["users"] if u[0] == "IDEA Demo School"}
assert inn == demo, ("IDEA Demo School users", inn)
for u in after["users"]:
    if u[1] in demo:
        assert u[0] == "IDEA Demo School", ("demo user outside IDEA Demo School", u)
assert after["facilities"] == ["IDEA Demo School"], after["facilities"]
print("ok")
PY
  echo "PASS[$SC] demo users only in IDEA Demo School"

  docker run -d --name "$NAME" --network host -e KOLIBRI_RUN_MODE=docker -e KOLIBRI_HOME=/root/.kolibri \
    -e KOLIBRI_HTTP_PORT="$PORT" -e KOLIBRI_ZIP_CONTENT_PORT="$((PORT+1))" \
    -v "$D:/root/.kolibri" --entrypoint sh "$IMAGE" -c "$KRUN" kolibri start --foreground >/dev/null
  set +e; demo/provision-demo.sh "$D" >/dev/null 2>&1; rc=$?; set -e
  [ "$rc" = 3 ] || fail "live guard rc=$rc"; echo "PASS[$SC] refuses live server"
  for _ in $(seq 90); do curl -sf "localhost:$PORT/" >/dev/null && break; sleep 2; done
  local F
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
  docker rm -f "$NAME" >/dev/null
}

nomarker
refused
scenario
echo "ALL PASS"
