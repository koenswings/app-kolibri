#!/usr/bin/env bash
# Optional IDEA demo seed for the Kolibri App (not run by default).
#
# Uses only supported Kolibri 0.15.5 management commands, run in a ONE-SHOT
# container against the instance's data dir while the Kolibri server is STOPPED:
#   1. kolibri manage provisiondevice --noinput   (facility "IDEA Demo School", admin/admin911!)
#      with --facility_settings {"learner_can_login_with_no_password": true}
#   2. kolibri manage bulkimportusers users.csv   (class Grade 5, teacher1, learner1..3;
#      learners have no password and sign in with their username only)
# It never execs into a running server and never uses `kolibri manage shell`.
#
# Usage: demo/provision-demo.sh [--dry-run] [--force-passwords] DATA_DIR
#   DATA_DIR  host path mounted at /root/.kolibri (the instance's data/kolibri)
# Env: IMAGE (default koenswings/kolibri:1.0-0.15.5-dev), DOCKER (default docker)
#
# Idempotent: re-running reuses the facility, keeps the existing superuser, and
# (via bulkexportusers + build_users_csv.py) updates existing users by UUID with
# PASSWORD "*" (unchanged) unless --force-passwords resets teacher1 to <account>911!
# (learners never get a password).
# It never deletes users (no --delete).
set -euo pipefail

IMAGE="${IMAGE:-koenswings/kolibri:1.0-0.15.5-dev}"
DOCKER="${DOCKER:-docker}"
K=./kolibri-0.15.5
FACILITY="IDEA Demo School"
HERE="$(cd "$(dirname "$0")" && pwd)"
DRY=0; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --force-passwords) FORCE=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
DATA="${1:?usage: provision-demo.sh [--dry-run] [--force-passwords] DATA_DIR}"
DATA="$(cd "$DATA" && pwd)"

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

# Learners sign in with NO password (learner_can_login_with_no_password). The
# formal preset already turns it on in 0.15.5; the explicit --facility_settings
# keeps it on if a preset ever changes. Kolibri applies both only when it CREATES
# the facility; an existing facility keeps its settings (see demo/README.md).
# Teachers and the admin always need their password.
FS="$WORK/facility_settings.json"
[ "$DRY" = 1 ] || printf '{"learner_can_login_with_no_password": true}\n' > "$FS"
oneshot provisiondevice --facility "$FACILITY" \
  --superusername admin --superuserpassword 'admin911!' \
  --preset formal --language_id en \
  --facility_settings /seed/facility_settings.json --noinput
# bulkimportusers matches existing users by UUID only: export first, then merge.
oneshot bulkexportusers -O /seed/existing.csv -w
EXPORT="$WORK/existing.csv"; [ -s "$EXPORT" ] || EXPORT=""
FP=""; [ "$FORCE" = 1 ] && FP=--force-passwords
python3 "$HERE/build_users_csv.py" "$HERE/users.csv" $EXPORT "$WORK/users.csv" $FP
oneshot bulkimportusers /seed/users.csv
echo "IDEA demo seed done for $DATA. Start Kolibri again (docker compose start kolibri)."
