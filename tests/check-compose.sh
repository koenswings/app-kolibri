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
if grep -q "8080\"\?$" <<<"$(grep -E 'KOLIBRI_(HTTP|LISTEN)_PORT' <<<"$out")"; then echo "FAIL port defaults to 8080"; fail=1; fi
exit $fail
