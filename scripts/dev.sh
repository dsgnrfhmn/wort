#!/usr/bin/env bash
# Dev server for the web app over https, reachable from the LAN, restarting on every Python change.
#
#   cp .env.dev.example .env.dev    # once; put this machine's LAN address and cert paths in it (.env.dev is gitignored)
#   scripts/dev.sh
#
# Templates and static files are read fresh on each request; .py changes under app/ and src/ restart uvicorn.
# The cert can be the self-signed one from DEPLOY.md §1 (its SAN must contain WORT_DEV_HOST).
# Open the port for the LAN only, e.g. sudo ufw allow from <LAN-SUBNET> to <LAN-IP> port <PORT> proto tcp.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$here/.env.dev"

if [ ! -f "$env_file" ]; then
  echo "dev.sh: $env_file missing; copy .env.dev.example and set WORT_DEV_HOST" >&2
  exit 1
fi
set -a
# shellcheck source=/dev/null
. "$env_file"
set +a

: "${WORT_DEV_HOST:?dev.sh: WORT_DEV_HOST is not set in .env.dev}"
: "${WORT_DEV_PORT:?dev.sh: WORT_DEV_PORT is not set in .env.dev}"
: "${WORT_DEV_TLS_CERT:?dev.sh: WORT_DEV_TLS_CERT is not set in .env.dev}"
: "${WORT_DEV_TLS_KEY:?dev.sh: WORT_DEV_TLS_KEY is not set in .env.dev}"
for f in "$WORT_DEV_TLS_CERT" "$WORT_DEV_TLS_KEY"; do
  [ -r "$f" ] || { echo "dev.sh: cannot read $f" >&2; exit 1; }
done

cd "$here"
exec env PYTHONPATH="$here:$here/src" uv run --group web uvicorn app.main:create_app --factory \
  --host "$WORT_DEV_HOST" --port "$WORT_DEV_PORT" \
  --ssl-certfile "$WORT_DEV_TLS_CERT" --ssl-keyfile "$WORT_DEV_TLS_KEY" \
  --reload --reload-dir app --reload-dir src
