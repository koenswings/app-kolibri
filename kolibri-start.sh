#!/bin/sh
# kolibri-start.sh: entrypoint for the Kolibri App (app-kolibri#13, agent-app-dev#23).
# Compose: entrypoint ["sh", "/idea/kolibri-start.sh"], command ["start", "--foreground"].
# Works with koenswings/kolibri:1.0-0.15.5-dev (./kolibri-0.15.5) and the official
# learningequality/kolibri:0.19.5 image (kolibri on PATH), on the same data directory.
#
# It replaces the official image's /entrypoint.sh, which overwrote MORANGO_SYSTEM_ID with a
# random id from $KOLIBRI_HOME/.node_id (so every update changed the Kolibri instance_id).
# What we keep from it, what we drop and why: see docs/kolibri-start.md.
#
# Steps:
# 1. KOLIBRI_HOME defaults to /root/.kolibri (today's data path) and must be a mount.
# 2. KOLIBRI_ZIP_CONTENT_PORT must be set (Engine writes port_zip; no 8081 default,
#    which collides when two Kolibris share the host network).
# 3. Binary: $KOLIBRI_BIN, else kolibri on PATH, else ./kolibri-<version> in the workdir.
# 4. On an update (data version OLDER than image version) move job_storage.sqlite3
#    (+ -wal/-shm) aside: 0.15.5 -> 0.19.5 with the old queue crash-looped
#    (kolibritasks.0001 "index queue__scheduled_time already exists"). Never delete;
#    rename to <file>.pre-<dataver>-<UTC stamp>. Same, newer or unreadable version: no move.
# 5. exec Kolibri as PID1 (under compose init), as root like the 0.15.5 image.
set -eu
log(){ echo "kolibri-start: $*"; }

KOLIBRI_HOME=${KOLIBRI_HOME:-/root/.kolibri}; export KOLIBRI_HOME

# vnum <text>: the last dotted version number in text ("kolibri-0.15.5, version 0.15.5" -> 0.15.5)
vnum(){ printf '%s\n' "$1" | grep -oE '[0-9]+(\.[0-9]+)+' | tail -n 1 || true; }
# vlt <a> <b>: true when version a < b (numeric per component, missing components = 0)
vlt(){ awk -v a="$1" -v b="$2" 'BEGIN{na=split(a,x,".");nb=split(b,y,".");n=(na>nb?na:nb)
  for(i=1;i<=n;i++){p=x[i]+0;q=y[i]+0;if(p<q)exit 0;if(p>q)exit 1};exit 1}'; }

if [ -z "${KOLIBRI_START_NO_MOUNT_CHECK:-}" ] && command -v mountpoint >/dev/null 2>&1 \
   && ! mountpoint -q "$KOLIBRI_HOME"; then
  log "ERROR: KOLIBRI_HOME $KOLIBRI_HOME is not a mounted volume; refusing to start"; exit 78
fi
if [ -z "${KOLIBRI_ZIP_CONTENT_PORT:-}" ]; then
  log "ERROR: KOLIBRI_ZIP_CONTENT_PORT is empty (Engine .env port_zip missing); refusing to fall back to 8081"; exit 78
fi
if [ "$KOLIBRI_ZIP_CONTENT_PORT" = "${KOLIBRI_HTTP_PORT:-}" ]; then
  log "ERROR: KOLIBRI_ZIP_CONTENT_PORT equals KOLIBRI_HTTP_PORT ($KOLIBRI_HTTP_PORT)"; exit 78
fi
if [ -n "${MORANGO_SYSTEM_ID:-}" ]; then log "MORANGO_SYSTEM_ID=$MORANGO_SYSTEM_ID"
else log "warning: MORANGO_SYSTEM_ID not set; Morango derives the instance id from the host"; fi

BIN=${KOLIBRI_BIN:-}
if [ -z "$BIN" ]; then
  if command -v kolibri >/dev/null 2>&1; then BIN=kolibri
  else for f in ./kolibri-*; do [ -x "$f" ] && BIN=$f; done; fi
fi
[ -n "$BIN" ] || { log "ERROR: no Kolibri binary (set KOLIBRI_BIN)"; exit 78; }

raw=${KOLIBRI_IMAGE_VERSION:-${KOLIBRI_VERSION:-}}
[ -n "$raw" ] || raw=$("$BIN" --version 2>/dev/null | tail -n 1) || raw=
image_version=$(vnum "$raw")
data_raw=
[ -f "$KOLIBRI_HOME/.data_version" ] && data_raw=$(cat "$KOLIBRI_HOME/.data_version")
data_version=$(vnum "$data_raw")

if [ -z "$data_raw" ]; then
  log "no recorded data version (new install); nothing to move"
elif [ -z "$data_version" ]; then
  log "could not read data version from .data_version ('$data_raw'); leaving job_storage as is"
elif [ -z "$image_version" ]; then
  log "could not read image Kolibri version ('$raw'); leaving job_storage as is"
elif ! vlt "$data_version" "$image_version"; then
  log "data version $data_version, image version $image_version: plain restart, no move"
elif [ ! -e "$KOLIBRI_HOME/job_storage.sqlite3" ]; then
  log "update $data_version -> $image_version; no job_storage.sqlite3 to move"
else
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  for f in job_storage.sqlite3 job_storage.sqlite3-wal job_storage.sqlite3-shm; do
    [ -e "$KOLIBRI_HOME/$f" ] || continue
    dest="$KOLIBRI_HOME/$f.pre-$data_version-$stamp"
    n=1; while [ -e "$dest" ]; do dest="$KOLIBRI_HOME/$f.pre-$data_version-$stamp.$n"; n=$((n+1)); done
    mv "$KOLIBRI_HOME/$f" "$dest"
    log "update $data_version -> $image_version: moved $f aside to $(basename "$dest")"
  done
fi
[ -n "${KOLIBRI_START_DRY_RUN:-}" ] && exit 0
exec "$BIN" "$@"
