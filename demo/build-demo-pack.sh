#!/usr/bin/env bash
# Build the Kolibri demo pack (engine-dev#369 pack v1). See build-demo-pack.py.
# Does not publish a GitHub release or upload an asset.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/build-demo-pack.py" "$@"
