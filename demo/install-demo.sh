#!/usr/bin/env bash
# Install (or reuse) the separate IDEA demo Kolibri instance through the Engine,
# seed it and import the IDEA-DEMO channels. Callable from an Engine hook (idea#235).
#
#   1. find the Engine instance named exactly $NAME (default Kolibri-Demo) on this Engine;
#      none -> `installApp <APP_ID> <disk> --name <NAME>` (Engine command queue, like the Console)
#   2. verify the target: exactly one instance with that name, its compose.yaml
#      x-app.instanceName is exactly NAME, its data dir exists; anything else is refused
#   3. `stopInstance <id> <disk>` (Engine)
#   4. demo/provision-demo.sh --demo-instance <instance>/data/kolibri (IDEA Demo School,
#      admin/teacher1/teacher2 <account>911!, learners username-only; its guards apply)
#   5. one-shot `kolibri manage importchannel disk` + `importcontent disk` for every channel
#      in the IDEA-DEMO export (Kolibri stopped; only this instance's data dir is mounted)
#   6. `startInstance <id> <disk>` (Engine), wait for HTTP 200
# A rerun reuses the instance (no second install) and re-seeds idempotently.
#
# Usage: demo/install-demo.sh --channels <export.tar|dir with KOLIBRI_DATA> [--disk <diskId>] [--name NAME]
#   --disk is required when the instance does not exist yet (the install target).
# Env: ENGINE_DIR (default /home/pi/idea/agents/agent-engine-dev), APP_ID (default kolibri-latest),
#      DISKS_ROOT (default /disks), HTTP_WAIT (2s steps, default 120), IMAGE, DOCKER, ENGINE_CMD (override, tests), PROVISION (override, tests)
# Exit codes: 0 ok | 2 usage | 3 Engine unreachable | 11 install failed | 12 ambiguous name
#   | 13 target check failed | 14 stop failed | 15 seed failed | 16 channel import failed | 17 start failed
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="Kolibri-Demo"; DISK=""; CHANNELS=""
ENGINE_DIR="${ENGINE_DIR:-/home/pi/idea/agents/agent-engine-dev}"
APP_ID="${APP_ID:-kolibri-latest}"; DISKS_ROOT="${DISKS_ROOT:-/disks}"
IMAGE="${IMAGE:-koenswings/kolibri:1.0-0.15.5-dev}"; DOCKER="${DOCKER:-docker}"
PROVISION="${PROVISION:-$HERE/provision-demo.sh}"
die() { local c=$1; shift; echo "install-demo: $*" >&2; exit "$c"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --disk) DISK="${2:-}"; shift 2 ;;
    --channels) CHANNELS="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) die 2 "unknown argument $1" ;;
  esac
done
[ -n "$CHANNELS" ] || die 2 "--channels is required"
[ -e "$CHANNELS" ] || die 2 "--channels $CHANNELS not found"
# The Engine splits installApp on whitespace, so the name must be one token.
[[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die 2 "instance name '$NAME' must be one word (letters, digits, . _ -)"
grep -qi demo <<<"$NAME" || die 2 "instance name '$NAME' must contain 'demo'"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
ecmd() {
  if [ -n "${ENGINE_CMD:-}" ]; then "$ENGINE_CMD" "$@"; return; fi
  [ -d "$WORK/ec" ] || { mkdir -p "$WORK/ec"; cp "$HERE/engine-cmd.mjs" "$WORK/ec/"; ln -s "$ENGINE_DIR/node_modules" "$WORK/ec/node_modules"; }
  (cd "$WORK/ec" && node engine-cmd.mjs "$ENGINE_DIR" "$@")
}
# matches NAME -> lines "id<TAB>storedOn<TAB>device<TAB>status<TAB>port"
find_named() {
  local js; js=$(ecmd list) || die 3 "Engine not reachable"
  python3 -c 'import json,sys
for i in json.loads(sys.argv[1]):
    if i["name"] == sys.argv[2]:
        print("\t".join(str(i.get(k) or "") for k in ("id","storedOn","device","status","port")))' "$js" "$NAME"
}
status_of() { find_named | awk -F'\t' -v id="$1" '$1==id{print $4}'; }

M=$(find_named); N=$(printf '%s' "$M" | grep -c . || true)
[ "$N" -le 1 ] || die 12 "REFUSED: $N Engine instances are named '$NAME'; resolve by hand"
if [ "$N" = 0 ]; then
  [ -n "$DISK" ] || die 2 "no instance '$NAME' yet: --disk <diskId> is required to install it"
  echo "Installing a new '$NAME' ($APP_ID) on disk $DISK via the Engine"
  ecmd send "installApp $APP_ID $DISK --name $NAME" || die 11 "installApp failed"
  M=$(find_named); N=$(printf '%s' "$M" | grep -c . || true)
  [ "$N" = 1 ] || die 11 "after installApp: $N instances named '$NAME'"
else
  echo "Reusing the existing '$NAME' instance (no new install)"
fi
IFS=$'\t' read -r ID ON DEV _ _ <<<"$M"
[ -z "$DISK" ] || [ "$DISK" = "$ON" ] || die 13 "REFUSED: '$NAME' ($ID) is on disk $ON, not $DISK"
INST="$DISKS_ROOT/$DEV/instances/$ID"; DATA="$INST/data/kolibri"
[ -f "$INST/compose.yaml" ] || die 13 "REFUSED: $INST/compose.yaml missing"
XN=$(sed -n 's/^  instanceName:[[:space:]]*//p' "$INST/compose.yaml" | head -1 | tr -d "\"'")
[ "$XN" = "$NAME" ] || die 13 "REFUSED: $INST is instance '$XN', not '$NAME'"
[ -d "$DATA" ] || die 13 "REFUSED: $DATA missing"
echo "Target: $ID on $ON ($INST)"

ecmd send "stopInstance $ID $ON" || die 14 "stopInstance failed"
for _ in $(seq 60); do
  live=0; for c in $($DOCKER ps -q); do
    $DOCKER inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$c" | grep -qxF "$DATA" && live=1; done
  [ "$live" = 0 ] && break; sleep 2
done
[ "$live" = 0 ] || die 14 "Kolibri of $ID still running after stopInstance"

"$PROVISION" --demo-instance "$DATA" || die 15 "provision-demo.sh failed (exit $?)"

if [ -d "$CHANNELS" ]; then SRC="$(cd "$CHANNELS" && pwd)"; else SRC="$WORK/ch"; mkdir -p "$SRC"; tar -xf "$CHANNELS" -C "$SRC"; fi
[ -d "$SRC/KOLIBRI_DATA/content/databases" ] || die 16 "no KOLIBRI_DATA/content/databases in $CHANNELS"
for db in "$SRC"/KOLIBRI_DATA/content/databases/*.sqlite3; do
  cid=$(basename "$db" .sqlite3)
  for c in importchannel importcontent; do
    $DOCKER run --rm --network none -e KOLIBRI_RUN_MODE=docker -v "$DATA:/root/.kolibri" \
      -v "$SRC:/channels:ro" "$IMAGE" ./kolibri-0.15.5 manage $c disk "$cid" /channels/KOLIBRI_DATA \
      || die 16 "$c $cid failed"
  done
done

ecmd send "startInstance $ID $ON" || die 17 "startInstance failed"
PORT=$(sed -n 's/^port=//p' "$INST/.env" | head -1); HOST=$(sed -n 's/^hostname=//p' "$INST/.env" | head -1)
IP=$(sed -n 's/^ip=//p' "$INST/.env" | head -1)
for _ in $(seq "${HTTP_WAIT:-120}"); do curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 2; done
curl -sf -o /dev/null "http://127.0.0.1:$PORT/" || die 17 "Kolibri did not answer on port $PORT"
echo "DONE: '$NAME' ($ID) http://$HOST:$PORT/ (http://$IP:$PORT/)"
