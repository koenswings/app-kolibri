#!/bin/sh
# kolibri-start.sh: start step for the Kolibri App (app-kolibri, idea#351 / agent-app-dev#23).
# Usage (compose command): sh /idea/kolibri-start.sh <kolibri-binary> start --foreground
#
# Before an updated Kolibri starts on older data, move the old task queue aside.
# Kolibri 0.15.5 -> 0.19.5 with the old job_storage.sqlite3 in place migrated the main
# database and then crash-looped (kolibritasks.0001 "index queue__scheduled_time already
# exists"; 17 restarts on idea04). With the file moved aside the update finished in ~380 s.
#
# Rules: never delete (rename to job_storage.sqlite3[-wal|-shm].pre-<dataver>-<UTC stamp>);
# only on an update (KOLIBRI_HOME/.data_version differs from the image's Kolibri version);
# idempotent (no file or same version = no-op; Kolibri rewrites .data_version after it
# migrates, and a failed attempt keeps the renamed file so a retry does nothing new);
# always logs one "kolibri-start:" line to stdout (docker logs).
set -eu
HOME_DIR=${KOLIBRI_HOME:-/root/.kolibri}
log(){ echo "kolibri-start: $*"; }

[ "$#" -ge 1 ] || { log "usage: kolibri-start.sh <kolibri-binary> [args...]"; exit 64; }
BIN=$1

image_version=${KOLIBRI_IMAGE_VERSION:-}
if [ -z "$image_version" ]; then
  image_version=$("$BIN" --version 2>/dev/null | tail -n 1 | tr -d '[:space:]') || image_version=
fi
data_version=
[ -f "$HOME_DIR/.data_version" ] && data_version=$(tr -d '[:space:]' < "$HOME_DIR/.data_version")

if [ -z "$data_version" ]; then
  log "no recorded data version (new install); nothing to move"
elif [ -z "$image_version" ]; then
  log "could not read image Kolibri version; leaving job_storage as is"
elif [ "$data_version" = "$image_version" ]; then
  log "data version $data_version = image version; plain restart"
elif [ ! -e "$HOME_DIR/job_storage.sqlite3" ]; then
  log "update $data_version -> $image_version; no job_storage.sqlite3 to move"
else
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  for f in job_storage.sqlite3 job_storage.sqlite3-wal job_storage.sqlite3-shm; do
    [ -e "$HOME_DIR/$f" ] || continue
    dest="$HOME_DIR/$f.pre-$data_version-$stamp"
    n=1; while [ -e "$dest" ]; do dest="$HOME_DIR/$f.pre-$data_version-$stamp.$n"; n=$((n+1)); done
    mv "$HOME_DIR/$f" "$dest"
    log "update $data_version -> $image_version: moved $f aside to $(basename "$dest")"
  done
fi
[ -n "${KOLIBRI_START_DRY_RUN:-}" ] && exit 0
exec "$@"
