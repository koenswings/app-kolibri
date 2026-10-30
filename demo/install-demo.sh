#!/usr/bin/env bash
# Install (or re-seed) the separate "Kolibri Demo" instance through the IDEA Engine.
#
# Koen, 2026-10-16: the demo is always its OWN Kolibri instance named "Kolibri Demo",
# installed alongside any real Kolibri. Existing instances are never touched.
#
# The Engine is driven ONLY through its store command queue, exactly like the Console:
# the command is pushed onto engineDB[<this engine>].commands and the matching
# command-log trace is followed to ok (Done) or error (Failed). No docker compose, no
# raw container lifecycle. Helper: demo/engine-cmd.mjs (list | disks | send "<cmd>").
#
# Flow:
#   1. list instances on disks docked to this Engine; pick the one whose display name is
#      exactly "Kolibri Demo" (the technical id, e.g. kolibri-demo, does not matter).
#      More than one -> refuse (exit 10).
#   2. none -> installApp <app> <disk> --source <disk> --name "Kolibri Demo" --fresh
#      (--fresh: start from the app bundle, never a copy of a school's data; without the
#      bundle on <source> the Engine falls back to its clean GitHub build), then look it up again.
#   3. stopInstance <id> <disk>
#   4. demo/provision-demo.sh --demo-instance <data dir>  (IDEA Demo School, users; it also
#      refuses a device that holds any other facility -> fail closed)
#   5. one-shot importchannel/importcontent disk for every IDEA-DEMO channel in the export
#   6. startInstance <id> <disk>   (also attempted after a failure in 4/5)
#   7. demo/seed_classwork.py against the running demo as teacher1 (Kolibri REST API, what
#      Coach > Plan does): one lesson per channel + "Grade 5 Practice Quiz" from the
#      channels' exercises, assigned to Grade 5 and started. Skipped with --no-channels
#      or --no-classwork. Exit 19 if it fails (the instance stays running).
# A rerun finds the existing "Kolibri Demo" and re-seeds it: no second instance.
#
# Usage: demo/install-demo.sh [options]
#   --engine-dir DIR    Engine checkout (config.yaml, store-identity/, node_modules)  [$ENGINE_DIR]
#   --disk ID           target disk for a NEW install (default: the only docked disk)   [$DEMO_DISK]
#   --source ID         disk holding apps/<app> (default: the target disk)              [$DEMO_SOURCE]
#                       installApp always gets --fresh: never a copy of a school's data
#   --instance ID       re-seed this instance; refused unless its name is exactly the demo name
#   --channels DIR|TAR  IDEA-DEMO export (holds KOLIBRI_DATA/)                          [$DEMO_CHANNELS]
#   --no-channels       skip the channel import
#   --no-classwork      skip step 7 (lessons + quiz through the Kolibri API)
#   --app ID            app to install (default kolibri-1.0)                            [$DEMO_APP]
#   --force-passwords   passed to provision-demo.sh
#   --dry-run           print the Engine commands, change nothing
# Env for hooks/tests: ENGINE_CMD (command prefix replacing "node engine-cmd.mjs DIR"),
#   PROVISION (default demo/provision-demo.sh), DISKS_ROOT (default /disks), IMAGE, DOCKER.
# Last stdout line is JSON: {"result":"installed|reseeded","id":..,"name":..,"disk":..,"port":..}
#
# Exit codes: 0 ok | 2 usage | 3 Engine/store unreachable | 10 more than one demo instance |
#   11 target refused (not the demo instance) | 12 installApp Failed/timeout |
#   13 install reported Done but no instance with the demo name (Engine dropped --name) |
#   14 stopInstance Failed | 15 provision-demo.sh failed | 16 channel import failed |
#   17 startInstance Failed | 18 no/ambiguous target disk | 19 lessons/quiz seed failed
set -uo pipefail

# Instance folder (idea#247 kit Engines): a data disk keeps instances in
# $DISKS_ROOT/<device>/instances/<id>; the Engine's system disk keeps them in /instances/<id>.
instance_dir() {  # $1 device, $2 instance id
  local d="${DISKS_ROOT:-/disks}/$1/instances/$2" sys="${SYSTEM_INSTANCES_ROOT:-/instances}/$2"
  if [ ! -d "$d" ] && [ -d "$sys" ]; then d="$sys"; fi
  printf '%s\n' "$d"
}


DEMO_NAME="Kolibri Demo"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { local c=$1; shift; echo "ERROR: $*" >&2; exit "$c"; }

engine() {  # engine list|disks|send "<command>"
  if [ -n "${ENGINE_CMD:-}" ]; then $ENGINE_CMD "$@"; return; fi
  # engine-cmd.mjs needs the Engine's node_modules: run it from a temp dir that links them.
  if [ -z "${EC_DIR:-}" ]; then
    EC_DIR="$(mktemp -d)"; trap 'rm -rf "$EC_DIR"' EXIT
    cp "$HERE/engine-cmd.mjs" "$EC_DIR/"; ln -s "$ENGINE_DIR/node_modules" "$EC_DIR/node_modules"
  fi
  (cd "$EC_DIR" && node engine-cmd.mjs "$ENGINE_DIR" "$@")
}

# x-app.instanceName of an instance folder (quotes stripped)
compose_name() { sed -n 's/^  instanceName:[[:space:]]*//p' "$1/compose.yaml" 2>/dev/null | head -1 | sed -e "s/^[\"']//" -e "s/[\"']\$//"; }

wait_stopped() {  # $1 data dir: no running container may mount it
  [ "$DRY" = 1 ] && return 0
  local live c
  for _ in $(seq "${STOP_WAIT:-60}"); do
    live=0
    for c in $(${DOCKER:-docker} ps -q); do
      ${DOCKER:-docker} inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$c" | grep -qxF "$1" && live=1
    done
    [ "$live" = 0 ] && return 0; sleep 2
  done
  return 1
}

wait_http() {  # $1 port
  [ "$DRY" = 1 ] || [ -z "$1" ] && return 0
  for _ in $(seq "${HTTP_WAIT:-120}"); do ${CURL:-curl} -sf -o /dev/null "http://127.0.0.1:$1/" && return 0; sleep 2; done
  return 1
}

# Instances whose display name is exactly DEMO_NAME: prints "id<TAB>storedOn<TAB>device<TAB>port"
demo_instances() {  # $1 = JSON from `engine list`
  printf '%s' "$1" | node -e '
    const name = process.argv[1]; let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
      for (const i of JSON.parse(s || "[]")) if (i && i.name === name)
        console.log([i.id, i.storedOn, i.device ?? "", i.port ?? ""].join("\t")) })' "$DEMO_NAME"
}
instance_by_id() {  # $1 JSON, $2 id: prints "name<TAB>storedOn<TAB>device<TAB>port"
  printf '%s' "$1" | node -e '
    const id = process.argv[1]; let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
      const i = JSON.parse(s || "[]").find(i => i && i.id === id)
      if (i) console.log([i.name, i.storedOn, i.device ?? "", i.port ?? ""].join("\t")) })' "$2"
}

send() {  # send "<command>" -> 0 Done, 1 Failed, 2 timeout, 3 unreachable
  echo "engine: $1" >&2
  [ "$DRY" = 1 ] && return 0
  local out rc; out="$(engine send "$1")"; rc=$?
  [ -n "$out" ] && echo "$out" >&2
  return $rc
}

# Find the Kolibri binary like kolibri-start.sh: KOLIBRI_BIN, then `kolibri` on PATH, then ./kolibri-*
# (0.15.5 image: ./kolibri-0.15.5; official 0.19.5: kolibri). --entrypoint sh bypasses the official
# image's /entrypoint.sh, as compose.yaml does.
# shellcheck disable=SC2016  # expanded inside the container
KRUN='B=${KOLIBRI_BIN:-}; if [ -z "$B" ]; then if command -v kolibri >/dev/null 2>&1; then B=kolibri; else for f in ./kolibri-*; do [ -x "$f" ] && B=$f; done; fi; fi; [ -n "$B" ] || { echo "no Kolibri binary (set KOLIBRI_BIN)" >&2; exit 78; }; "$B" "$@"'
import_channels() {  # $1 data dir
  local src="$CHANNELS" tmp=""
  if [ -f "$src" ]; then tmp="$(mktemp -d)"; tar -xf "$src" -C "$tmp" || return 1; src="$tmp"; fi
  [ -d "$src/KOLIBRI_DATA/content/databases" ] || { echo "no KOLIBRI_DATA/content/databases in $CHANNELS" >&2; return 1; }
  local db cid rc=0
  for db in "$src"/KOLIBRI_DATA/content/databases/*.sqlite3; do
    cid="$(basename "$db" .sqlite3)"
    for verb in importchannel importcontent; do
      echo "+ kolibri manage $verb disk $cid /export" >&2
      [ "$DRY" = 1 ] && continue
      ${DOCKER:-docker} run --rm --network none -e KOLIBRI_RUN_MODE=docker -e KOLIBRI_HOME=/root/.kolibri \
        -v "$1:/root/.kolibri" -v "$src/KOLIBRI_DATA:/export:ro" \
        --entrypoint sh "${IMAGE:-koenswings/kolibri:1.1-0.19.5}" -c "$KRUN" kolibri manage "$verb" disk "$cid" /export || rc=1
    done
  done
  [ -n "$tmp" ] && rm -rf "$tmp"
  return $rc
}

main() {
  ENGINE_DIR="${ENGINE_DIR:-}"; DISK="${DEMO_DISK:-}"; TARGET=""; CHANNELS="${DEMO_CHANNELS:-}"
  SRC="${DEMO_SOURCE:-}"; APP="${DEMO_APP:-kolibri-1.0}"; NOCH=0; NOCW=0; DRY=0; FORCE=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --engine-dir) ENGINE_DIR="${2:?}"; shift 2 ;;
      --disk) DISK="${2:?}"; shift 2 ;;
      --source) SRC="${2:?}"; shift 2 ;;
      --instance) TARGET="${2:?}"; shift 2 ;;
      --channels) CHANNELS="${2:?}"; shift 2 ;;
      --no-channels) NOCH=1; shift ;;
      --no-classwork) NOCW=1; shift ;;
      --app) APP="${2:?}"; shift 2 ;;
      --force-passwords) FORCE=(--force-passwords); shift ;;
      --dry-run) DRY=1; shift ;;
      -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
      *) die 2 "unknown argument $1" ;;
    esac
  done
  [ -n "${ENGINE_CMD:-}" ] || [ -n "$ENGINE_DIR" ] || die 2 "--engine-dir (or ENGINE_DIR) is required"
  [ "$NOCH" = 1 ] || [ -n "$CHANNELS" ] || die 2 "--channels <IDEA-DEMO export> is required (or --no-channels)"

  local list; list="$(engine list)" || die 3 "Engine store not reachable"
  local id disk dev port result
  if [ -n "$TARGET" ]; then
    local row; row="$(instance_by_id "$list" "$TARGET")"
    [ -n "$row" ] || die 11 "instance $TARGET is not on a disk docked here"
    [ "$(cut -f1 <<<"$row")" = "$DEMO_NAME" ] || die 11 "refusing $TARGET: its name is '$(cut -f1 <<<"$row")', not '$DEMO_NAME'"
    id="$TARGET"; IFS=$'\t' read -r _ disk dev port <<<"$row"
  else
    local rows n; rows="$(demo_instances "$list")"; n=$(grep -c . <<<"$rows")
    [ "$n" -gt 1 ] && die 10 "$n instances are named '$DEMO_NAME'; pass --instance <id>"
    if [ "$n" = 1 ]; then IFS=$'\t' read -r id disk dev port <<<"$rows"; fi
  fi

  if [ -z "${id:-}" ]; then
    if [ -z "$DISK" ]; then
      local disks; disks="$(engine disks)" || die 3 "Engine store not reachable"
      DISK="$(printf '%s' "$disks" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const d=JSON.parse(s||"[]");if(d.length===1)console.log(d[0].id)})')"
      [ -n "$DISK" ] || die 18 "pass --disk <id>: not exactly one disk is docked"
    fi
    send "installApp $APP $DISK --source ${SRC:-$DISK} --name \"$DEMO_NAME\" --fresh" || die 12 "installApp Failed (see the Engine command log)"
    if [ "$DRY" = 1 ]; then echo '{"result":"dry-run"}'; return 0; fi
    list="$(engine list)" || die 3 "Engine store not reachable"
    local rows; rows="$(demo_instances "$list")"
    [ "$(grep -c . <<<"$rows")" = 1 ] || die 13 "installApp reported Done but no single instance is named '$DEMO_NAME'"
    IFS=$'\t' read -r id disk dev port <<<"$rows"; result=installed
  else
    result=reseeded
  fi

  local inst data; inst="$(instance_dir "$dev" "$id")"
  data="$inst/data/kolibri"
  if [ "$DRY" != 1 ]; then
    [ -f "$inst/compose.yaml" ] || die 11 "refusing $id: $inst/compose.yaml missing"
    [ "$(compose_name "$inst")" = "$DEMO_NAME" ] || die 11 "refusing $id: compose x-app.instanceName is '$(compose_name "$inst")', not '$DEMO_NAME'"
  fi
  send "stopInstance $id $disk" || die 14 "stopInstance Failed"
  wait_stopped "$data" || die 14 "Kolibri of $id still running after stopInstance"
  local rc=0
  ${PROVISION:-"$HERE/provision-demo.sh"} --demo-instance "${FORCE[@]}" $([ "$DRY" = 1 ] && echo --dry-run) "$data" || rc=15
  if [ $rc = 0 ] && [ "$NOCH" = 0 ]; then import_channels "$data" || rc=16; fi
  send "startInstance $id $disk" || { [ $rc = 0 ] && rc=17; echo "ERROR: startInstance Failed" >&2; }
  if [ $rc = 0 ]; then
    port="$(sed -n 's/^port=//p' "$inst/.env" 2>/dev/null | head -1)"; port="${port:-$port}"
    wait_http "$port" || rc=17
  fi
  if [ $rc = 0 ] && [ "$NOCH" = 0 ] && [ "$NOCW" = 0 ]; then
    echo "+ seed_classwork.py --url http://127.0.0.1:$port" >&2
    if [ "$DRY" != 1 ]; then
      ${CLASSWORK:-python3 "$HERE/seed_classwork.py"} --url "http://127.0.0.1:$port" >&2 || rc=19
    fi
  fi
  [ $rc = 0 ] || die $rc "demo seed failed (exit $rc); the instance was started again if possible"
  printf '{"result":"%s","id":"%s","name":"%s","disk":"%s","port":"%s"}\n' "$result" "$id" "$DEMO_NAME" "$disk" "$port"
}

# Sourcing (e.g. from an Engine hook, idea#235) defines the functions without running.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
