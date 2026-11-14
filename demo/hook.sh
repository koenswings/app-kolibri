#!/usr/bin/env bash
# Engine demo seed hook (agent-engine-dev#369).
#
# The Engine runs this as:  <apps>/<appId>/demo/hook.sh <seed|classwork>
# with cwd = the instance folder and:
#   IDEA_DEMO=1, IDEA_DEMO_INSTANCE_ID, IDEA_DEMO_INSTANCE_DIR, IDEA_DEMO_DATA_DIR,
#   IDEA_DEMO_PACK_DIR, IDEA_DEMO_PORT, IDEA_DEMO_COMPOSE_PROJECT
#
# The Engine owns install, stop and start. This hook only seeds. It never calls
# engine-cmd, the command queue, installApp, startInstance, stopInstance or
# docker compose. It never extracts under mktemp or /tmp: a pack tar is unpacked
# only under ${IDEA_DEMO_PACK_DIR} (demo-pack/x/).
#
# Steps (Kolibri):
#   seed      — while the instance is stopped: provision-demo.sh + import_channels
#   classwork — against the running port: seed_classwork.py (idempotent; does not
#               reset learner progress on a re-press)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=install-demo.sh
source "$HERE/install-demo.sh"

die() { local c=$1; shift; echo "ERROR: $*" >&2; exit "$c"; }

# Refuse a pack dir on /tmp (the contract is instance/demo-pack/x/).
assert_pack_dir() {
  local d="${IDEA_DEMO_PACK_DIR:-}"
  [ -n "$d" ] || die 2 "IDEA_DEMO_PACK_DIR is required"
  local resolved
  if [ -d "$d" ]; then
    resolved="$(cd "$d" && pwd)"
  else
    local parent; parent="$(cd "$(dirname "$d")" && pwd)" || die 2 "IDEA_DEMO_PACK_DIR parent does not exist: $d"
    resolved="$parent/$(basename "$d")"
  fi
  case "$resolved" in
    /tmp|/tmp/*) die 2 "IDEA_DEMO_PACK_DIR must not be under /tmp: $resolved" ;;
  esac
  IDEA_DEMO_PACK_DIR="$resolved"
}

# If the Engine left the verified tar beside x/ and x/ is not yet extracted, unpack it here.
extract_pack_if_needed() {
  [ -d "$IDEA_DEMO_PACK_DIR/KOLIBRI_DATA/content/databases" ] && return 0
  local inst="${IDEA_DEMO_INSTANCE_DIR:-}" tar="" cand
  if [ -n "${IDEA_DEMO_PACK_TAR:-}" ] && [ -f "$IDEA_DEMO_PACK_TAR" ]; then
    tar="$IDEA_DEMO_PACK_TAR"
  elif [ -n "$inst" ]; then
    for cand in "$inst"/demo-pack/idea-demo-kolibri-v*.tar; do
      [ -f "$cand" ] && tar="$cand" && break
    done
  fi
  [ -n "$tar" ] || die 2 "no KOLIBRI_DATA in $IDEA_DEMO_PACK_DIR and no pack tar to extract"
  pack_root_or_extract "$tar" >/dev/null
}

data_dir() {
  if [ -n "${IDEA_DEMO_DATA_DIR:-}" ]; then
    printf '%s\n' "$IDEA_DEMO_DATA_DIR"
    return 0
  fi
  [ -n "${IDEA_DEMO_INSTANCE_DIR:-}" ] || die 2 "IDEA_DEMO_DATA_DIR or IDEA_DEMO_INSTANCE_DIR is required"
  printf '%s\n' "$IDEA_DEMO_INSTANCE_DIR/data/kolibri"
}

step_seed() {
  assert_pack_dir
  mkdir -p "$IDEA_DEMO_PACK_DIR"
  extract_pack_if_needed
  local data; data="$(data_dir)"
  mkdir -p "$data"
  echo "+ provision-demo.sh --demo-instance $data" >&2
  ${PROVISION:-"$HERE/provision-demo.sh"} --demo-instance $([ "${DRY:-0}" = 1 ] && echo --dry-run) "$data"
  # import_channels reads IDEA_DEMO_PACK_DIR (CHANNELS unset)
  unset CHANNELS || true
  import_channels "$data"
}

step_classwork() {
  local port="${IDEA_DEMO_PORT:-}"
  [ -n "$port" ] || die 2 "IDEA_DEMO_PORT is required for classwork"
  echo "+ seed_classwork.py --url http://127.0.0.1:$port" >&2
  if [ "${DRY:-0}" = 1 ]; then
    return 0
  fi
  # Idempotent: updates lessons/quiz in place; writes progress only when Coach
  # does not already show the item as Completed. Does not reset learner progress.
  ${CLASSWORK:-python3 "$HERE/seed_classwork.py"} --url "http://127.0.0.1:$port"
}

usage() {
  sed -n '2,24p' "$0"
  exit 2
}

if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0 2>/dev/null || true
fi

case "${1:-}" in
  seed) step_seed ;;
  classwork) step_classwork ;;
  -h|--help|"") usage ;;
  *) die 2 "unknown step '${1:-}': use seed or classwork" ;;
esac
