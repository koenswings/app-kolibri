#!/usr/bin/env bash
# Static compose check for app-kolibri: renders compose.yaml with a test port and
# asserts the r40 runtime settings and the Engine port wiring. Exit 0 = pass.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${1:-18555}; ZIP=${2:-18556}
out=$(port=$PORT port_zip=$ZIP docker compose -f compose.yaml config 2>&1) || { echo "FAIL: compose config: $out"; exit 1; }
fail=0
chk(){ if grep -qE -- "$1" <<<"$out"; then echo "ok   $2"; else echo "FAIL $2"; fail=1; fi; }
chk "KOLIBRI_HTTP_PORT: \"?$PORT\"?" "KOLIBRI_HTTP_PORT=\${port}"
chk "KOLIBRI_LISTEN_PORT: \"?$PORT\"?" "KOLIBRI_LISTEN_PORT=\${port}"
chk -- "- --foreground" "start --foreground"
chk "restart: unless-stopped" "restart unless-stopped"
chk "KOLIBRI_ZIP_CONTENT_PORT: \"?$ZIP\"?" "KOLIBRI_ZIP_CONTENT_PORT=\${port_zip}"
chk "healthcheck:" "healthcheck present"
chk "network_mode: host" "host network"
chk "pull_policy: never" "pull_policy never"
# Digest rule (idea#322 / agent-engine-dev#296): a pin must be tag@digest and the digest
# must be the image's multi-platform INDEX digest, never a single-platform digest
# (platform pins fail after docker load with pull_policy: never).
KOLIBRI_INDEX_DIGEST=sha256:a5ae1caf3e31b5bb9f2df9c94d45c4cf6fdb8ce3cfe8730364bd6648cdbadc31
img=$(grep -oE "image: \S+" <<<"$out" | head -1 | cut -d' ' -f2)
if [[ "$img" == *@sha256:* ]]; then
  if [[ "$img" =~ ^koenswings/kolibri:[^@]+@(sha256:[0-9a-f]{64})$ ]] && [[ "${BASH_REMATCH[1]}" == "$KOLIBRI_INDEX_DIGEST" ]]; then echo "ok   image tag@index-digest"; else echo "FAIL image digest is not tag@INDEX digest: $img"; fail=1; fi
else chk "image: koenswings/kolibri:[^@[:space:]]+$" "image tag-only"; fi
if grep -q "8080\"\?$" <<<"$(grep -E 'KOLIBRI_(HTTP|LISTEN)_PORT' <<<"$out")"; then echo "FAIL port defaults to 8080"; fail=1; fi
exit $fail
