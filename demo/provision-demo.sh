#!/usr/bin/env bash
# Optional IDEA demo seed for the Kolibri App (not run by default).
#
# Uses only supported Kolibri 0.15.5 management commands, run in a ONE-SHOT
# container against the instance's data dir while the Kolibri server is STOPPED:
#   0. facility_info.py (read-only SQLite open, mode=ro): provisioned? IDEA Demo School id?
#   1. kolibri manage provisiondevice --noinput   (only on an EMPTY device: creates
#      IDEA Demo School with admin/admin911! and {"learner_can_login_with_no_password": true})
#   2. kolibri manage bulkimportusers --facility <IDEA Demo School id> users.csv
#      (class Grade 5, teacher1, teacher2, learner1..3;
#      learners sign in with their username only; their stored fallback is <account>911!)
# It never execs into a running server and never uses `kolibri manage shell`.
#
# DEMO INSTANCES ONLY (Koen, 2026-10-16): the demo is always its own Kolibri
# instance with "demo" in its name, never a school inside an existing Kolibri.
# It refuses (exit 5, nothing changed) unless the instance is marked as a demo:
#   the instance folder (DATA_DIR/../.. for <instance>/data/kolibri) or its .env
#   COMPOSE_PROJECT_NAME contains "demo" (case-insensitive), or --demo-instance;
# and refuses (exit 6, nothing changed) unless the device is empty/unprovisioned
# or its ONLY facility is "IDEA Demo School" (rerun).
#
# Usage: demo/provision-demo.sh [--dry-run] [--force-passwords] [--demo-instance] DATA_DIR
#   DATA_DIR  host path mounted at /root/.kolibri (the instance's data/kolibri)
# Env: IMAGE (default koenswings/kolibri:1.0-0.15.5-dev), DOCKER (default docker)
#
# Idempotent: re-running reuses the facility, keeps the existing superuser, and
# (via bulkexportusers + build_users_csv.py) updates existing users by UUID with
# PASSWORD "*" (unchanged) unless --force-passwords resets teacher1/teacher2 and the
# learners to <account>911! (learners' stored fallback; they sign in username-only).
# It never deletes users (no --delete).
set -euo pipefail

IMAGE="${IMAGE:-koenswings/kolibri:1.0-0.15.5-dev}"
DOCKER="${DOCKER:-docker}"
K=./kolibri-0.15.5
FACILITY="IDEA Demo School"
HERE="$(cd "$(dirname "$0")" && pwd)"
DRY=0; FORCE=0; DEMOFLAG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --force-passwords) FORCE=1; shift ;;
    --demo-instance|--i-am-demo-instance) DEMOFLAG=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
DATA="${1:?usage: provision-demo.sh [--dry-run] [--force-passwords] [--demo-instance] DATA_DIR}"
DATA="$(cd "$DATA" && pwd)"

# Guard 1: demo marker (checked before anything runs).
demo_marker() {
  [ "$DEMOFLAG" = 1 ] && { echo "--demo-instance"; return 0; }
  case "$DATA" in */data/kolibri) ;; *) return 1 ;; esac
  local inst; inst="$(dirname "$(dirname "$DATA")")"
  if basename "$inst" | grep -qi demo; then echo "instance folder $(basename "$inst")"; return 0; fi
  if [ -f "$inst/.env" ] && grep -iE '^COMPOSE_PROJECT_NAME=.*demo' "$inst/.env" >/dev/null; then
    echo "COMPOSE_PROJECT_NAME in $inst/.env"; return 0; fi
  return 1
}
if ! MARK=$(demo_marker); then
  echo "REFUSED: $DATA is not marked as a demo instance. The IDEA demo is always a separate" >&2
  echo "Kolibri instance with 'demo' in its name (instance folder or COMPOSE_PROJECT_NAME), or" >&2
  echo "pass --demo-instance (the Engine hook does this for its demo instance). Nothing changed." >&2
  exit 5
fi
echo "Demo instance marker: $MARK"

run() { if [ "$DRY" = 1 ]; then printf 'DRY:'; printf ' %q' "$@"; echo; else "$@"; fi; }

# Refuse to touch a live server: no running container may mount this data dir.
if [ "$DRY" != 1 ]; then
  for id in $($DOCKER ps -q); do
    if $DOCKER inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$id" | grep -qxF "$DATA"; then
      echo "ERROR: container $id is running with $DATA mounted. Stop Kolibri first (docker compose stop kolibri)." >&2
      exit 3
    fi
  done
fi

WORK="$(mktemp -d)"; chmod 777 "$WORK"
trap 'rm -rf "$WORK"' EXIT

oneshot() {
  run $DOCKER run --rm --network none -e KOLIBRI_RUN_MODE=docker \
    -v "$DATA:/root/.kolibri" -v "$WORK:/seed" \
    "$IMAGE" "$K" manage "$@"
}

# Read-only probe (SQLite mode=ro; the dir is mounted rw only so SQLite can use
# the WAL index file of a stopped server): is the device provisioned, and does
# IDEA Demo School already exist? -> sets PROVISIONED and FID.
probe() {
  if [ "$DRY" = 1 ]; then
    run $DOCKER run --rm --network none -v "$DATA:/root/.kolibri" -v "$HERE:/demo:ro" \
      --entrypoint python3 "$IMAGE" /demo/facility_info.py /root/.kolibri "$FACILITY"
    # dry run: pretend an empty device first, then a created facility
    PROVISIONED=0; FACILITIES='[]'; FID="${FID+FACILITY_ID}"; return
  fi
  local out; out=$($DOCKER run --rm --network none -v "$DATA:/root/.kolibri" -v "$HERE:/demo:ro" \
      --entrypoint python3 "$IMAGE" /demo/facility_info.py /root/.kolibri "$FACILITY")
  PROVISIONED=$(printf '%s\n' "$out" | sed -n 's/^provisioned=//p')
  FACILITIES=$(printf '%s\n' "$out" | sed -n 's/^facilities=//p')
  FID=$(printf '%s\n' "$out" | sed -n 's/^facility_id=//p')
}

# Learners sign in with their username only (learner_can_login_with_no_password).
# The formal preset already turns it on in 0.15.5; the explicit --facility_settings
# keeps it on. Kolibri applies both only to a facility it CREATES, and only to that
# facility; an existing facility keeps its settings (see demo/README.md).
FS="$WORK/facility_settings.json"
[ "$DRY" = 1 ] || printf '{"learner_can_login_with_no_password": true}\n' > "$FS"
probe
# Guard 2: dedicated demo device only. Allowed: empty/unprovisioned (no facility),
# or a device whose ONLY facility is IDEA Demo School (rerun). Anything else is
# refused before any write.
if [ "$DRY" != 1 ]; then
  if [ "$FACILITIES" = '[]' ] && [ "$PROVISIONED" != 1 ]; then :
  elif [ "$FACILITIES" = '["IDEA Demo School"]' ] && [ -n "$FID" ]; then :
  else
    echo "REFUSED: $DATA is not a dedicated demo instance (provisioned=$PROVISIONED, facilities=$FACILITIES)." >&2
    echo "The demo is never added to an existing Kolibri. Use a separate instance with 'demo' in its name. Nothing changed." >&2
    exit 6
  fi
fi
if [ -n "$FID" ]; then
  echo "IDEA Demo School exists ($FID): not running provisiondevice."
else
  oneshot provisiondevice --facility "$FACILITY" \
    --superusername admin --superuserpassword 'admin911!' \
    --preset formal --language_id en \
    --facility_settings /seed/facility_settings.json --noinput
  probe
fi
[ -n "$FID" ] || { echo "ERROR: could not resolve the IDEA Demo School facility id" >&2; exit 4; }
# Always target IDEA Demo School explicitly by id (no --delete).
# bulkimportusers matches existing users by UUID only: export first, then merge.
oneshot bulkexportusers --facility "$FID" -O /seed/existing.csv -w
EXPORT="$WORK/existing.csv"; [ -s "$EXPORT" ] || EXPORT=""
FP=""; [ "$FORCE" = 1 ] && FP=--force-passwords
python3 "$HERE/build_users_csv.py" "$HERE/users.csv" $EXPORT "$WORK/users.csv" $FP
oneshot bulkimportusers --facility "$FID" /seed/users.csv
echo "IDEA demo seed done for $DATA. Start Kolibri again (docker compose start kolibri)."
