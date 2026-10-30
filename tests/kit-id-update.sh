#!/usr/bin/env bash
# Update test for a kit-style Kolibri ID (idea#374 precondition; idea PR #373 kit-kolibri-morango.sh).
# Runs the real compose.yaml + kolibri-start.sh in a scratch project dir (no Pi app data):
#   1. start OLD_IMAGE (default 0.15.5-dev) with MORANGO_SYSTEM_ID=idea-<hostname>-<port>
#   2. record the env value seen by the Kolibri processes and the current morango_instanceidmodel row
#   3. update to NEW_IMAGE the way updateApp does: stop, same ./data, new image, start
#      (kolibri-start.sh moves job_storage.sqlite3 aside on the update)
#   4. restart once
#   5. assert: env value unchanged at every step, job_storage moved exactly once, server healthy;
#      report whether instance_id / system_id stayed the same (asserted unless ALLOW_ID_CHANGE=1).
# Needs docker (compose v2), curl, both images local (pull_policy: never).
# Env: WORK (default ./kitid-<pid>), PORT (18901), PORT_ZIP (18902), KIT_HOST (default `hostname`),
#      OLD_IMAGE, NEW_IMAGE, HEALTH_WAIT (s, default 900), LOG (default WORK/../kolibri-kitid-<stamp>.log).
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
OLD_IMAGE="${OLD_IMAGE:-koenswings/kolibri:1.0-0.15.5-dev}"
NEW_IMAGE="${NEW_IMAGE:-koenswings/kolibri:1.1-0.19.5}"
PORT="${PORT:-18901}"; PORT_ZIP="${PORT_ZIP:-18902}"; KIT_HOST="${KIT_HOST:-$(hostname)}"
HEALTH_WAIT="${HEALTH_WAIT:-900}"
WORK="${WORK:-$PWD/kitid-$$}"; P="kitid$$"
LOG="${LOG:-$(dirname "$WORK")/kolibri-kitid-$(date -u +%Y%m%dT%H%M%SZ).log}"
EXPECT="idea-$KIT_HOST-$PORT"
log() { echo "$(date -u +%H:%M:%S) $*" | tee -a "$LOG"; }
fail() { log "FAIL: $*"; exit 1; }
mkdir -p "$WORK/data"
cp "$SRC/compose.yaml" "$SRC/kolibri-start.sh" "$WORK/"
printf 'port=%s\nport_zip=%s\nhostname=%s\n' "$PORT" "$PORT_ZIP" "$KIT_HOST" > "$WORK/.env"
dc() { docker compose -p "$P" --project-directory "$WORK" -f "$WORK/compose.yaml" -f "$WORK/override.yaml" "$@"; }
use() { printf 'services:\n  kolibri:\n    image: %s\n' "$1" > "$WORK/override.yaml"; }
cleanup() {
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  docker run --rm --network none -v "$WORK:/w" --entrypoint sh "$OLD_IMAGE" -c 'rm -rf /w/data' >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
[ "${KEEP:-0}" = 1 ] || trap cleanup EXIT

healthy() {  # wait for /api/public/info/ -> seconds
  local t0=$SECONDS
  while [ $((SECONDS - t0)) -lt "$HEALTH_WAIT" ]; do
    curl -fsS -m 3 "http://127.0.0.1:$PORT/api/public/info/" 2>/dev/null | grep -q '"application": *"kolibri"' && { echo $((SECONDS - t0)); return 0; }
    [ "$(docker inspect -f '{{.State.Status}}' "$(dc ps -aq kolibri)")" = running ] || { dc logs --tail 40 kolibri >>"$LOG" 2>&1; return 1; }
    sleep 3
  done; return 1
}
# Distinct MORANGO_SYSTEM_ID values in the environ of every process in the container (catches an
# entrypoint that exports its own value).
envval() { dc exec -T kolibri python3 -c '
import glob
v=set()
for f in glob.glob("/proc/[0-9]*/environ"):
    try:
        for kv in open(f,"rb").read().split(b"\0"):
            if kv.startswith(b"MORANGO_SYSTEM_ID="): v.add(kv.split(b"=",1)[1].decode())
    except OSError: pass
print(",".join(sorted(v)))'; }
ids() { dc exec -T kolibri python3 -c '
import sqlite3
c=sqlite3.connect("/root/.kolibri/db.sqlite3")
r=c.execute("select id, system_id, counter from morango_instanceidmodel where current=1").fetchall()
print(" ".join("%s|%s|%s"%x for x in r))'; }
nodeid() { [ -e "$WORK/data/kolibri/.node_id" ] && echo present || echo absent; }
step() {  # step NAME
  local s e i; s=$(healthy) || fail "$1: not healthy within ${HEALTH_WAIT}s"
  e=$(envval); i=$(ids)
  log "$1: healthy ${s}s env=[$e] instance|system|counter=[$i] .node_id=$(nodeid)"
  [ "$e" = "$EXPECT" ] || fail "$1: MORANGO_SYSTEM_ID in processes is [$e], expected [$EXPECT]"
  [ -n "$i" ] && [ "${i#* }" = "$i" ] || fail "$1: expected exactly one current morango_instanceidmodel row, got [$i]"
  eval "ENV_$1=\$e; IDS_$1=\$i"
}
log "kit-id update test: $OLD_IMAGE -> $NEW_IMAGE, port $PORT, expect $EXPECT, work $WORK"
for img in "$OLD_IMAGE" "$NEW_IMAGE"; do docker image inspect "$img" >/dev/null 2>&1 || fail "image not local: $img"; done

use "$OLD_IMAGE"; dc up -d >/dev/null 2>&1 || fail "up old"; step old
dc stop >/dev/null 2>&1                         # updateApp: stop, keep ./data, new image, start
use "$NEW_IMAGE"; dc up -d >/dev/null 2>&1 || fail "up new"; step updated
dc restart >/dev/null 2>&1; step restarted

moves=$(find "$WORK/data/kolibri" -maxdepth 1 -name 'job_storage.sqlite3.pre-*' | wc -l)
log "job_storage moved aside: $moves file(s)"
dc logs kolibri 2>/dev/null | grep -i 'job_storage\|restart' | tail -5 | sed 's/^/  start: /' | tee -a "$LOG"
[ "$moves" -le 1 ] || fail "job_storage moved $moves times"

# shellcheck disable=SC2154  # ENV_*/IDS_* are set via eval in step()
for s in updated restarted; do eval "e=\$ENV_$s"; [ "$e" = "$ENV_old" ] || fail "env changed at $s: $ENV_old -> $e"; done
log "PASS env MORANGO_SYSTEM_ID unchanged: $ENV_old"
# shellcheck disable=SC2154
id_old=${IDS_old%%|*}; ok=1
for s in updated restarted; do eval "i=\$IDS_$s"
  if [ "$i" = "$IDS_old" ]; then log "ids unchanged at $s ($i)"
  else log "ids CHANGED at $s: $IDS_old -> $i"; ok=0; fi
done
if [ $ok = 1 ]; then log "PASS instance_id stable: $id_old"
elif [ "${ALLOW_ID_CHANGE:-0}" = 1 ]; then log "NOTE instance_id/system_id changed (ALLOW_ID_CHANGE=1)"
else fail "instance_id/system_id changed across the update"; fi
log "PASS kit-id update test"
