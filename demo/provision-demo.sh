#!/usr/bin/env bash
# Optional IDEA demo seed for the Kolibri App (not run by default).
# Run only when an IDEA-DEMO disk is docked or the operator asks for demo mode:
#   demo/provision-demo.sh [CONTAINER]
# Device not yet provisioned -> provisions it as "IDEA Demo School" (admin / admin911!).
# Already provisioned -> adds the demo facility next to existing ones; changes nothing else.
set -euo pipefail
C="${1:-${CONTAINER:-kolibri}}"
K=./kolibri-0.15.5
HERE="$(cd "$(dirname "$0")" && pwd)"
if ! docker exec "$C" sh -c "$K manage shell -c 'from kolibri.core.device.utils import device_provisioned; import sys; sys.exit(0 if device_provisioned() else 1)'" >/dev/null 2>&1; then
  docker exec "$C" $K manage provisiondevice --facility "IDEA Demo School" \
    --superusername admin --superuserpassword 'admin911!' \
    --preset formal --language_id en --noinput
fi
docker exec -i "$C" $K shell < "$HERE/provision-demo.py"
