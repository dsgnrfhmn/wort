#!/usr/bin/env bash
# Dev server for the web app over https, reachable from the LAN, restarting on every Python change.
#
#   cp .env.dev.example .env.dev    # once; put this machine's LAN address and cert paths in it (.env.dev is gitignored)
#   scripts/dev.sh
#
# Templates and static files are read fresh on each request; .py changes under app/ and src/ restart uvicorn.
# The cert can be the self-signed one from DEPLOY.md §1 (its SAN must contain WORT_DEV_HOST).
# Open the port for the LAN only, e.g. sudo ufw allow from <LAN-SUBNET> to <LAN-IP> port <PORT> proto tcp.
#
# LanguageTool (the grammar check) comes up with this server and goes down with it (scripts/languagetool.sh, a rootless
# podman container on 127.0.0.1 only). The app asks it from this machine, so a browser on the LAN gets the grammar
# results too; the LanguageTool port itself is never on the LAN. One that already answers is used and left running when
# this server stops. WORT_DEV_LT=0 in .env.dev leaves LanguageTool alone (a sentence is then "not checked": no score).
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

lt="$here/scripts/languagetool.sh"
lt_owned=0
if [ "${WORT_DEV_LT:-1}" != "0" ]; then
  if "$lt" ready; then
    echo "dev.sh: LanguageTool already answers; it stays up when this server stops"
  else
    lt_owned=1
    "$lt" ensure &   # in the background: the app is usable while Java warms up; a sentence is "not checked" until then
    lt_job=$!
  fi
fi
# The app's client (src/wort/exercises/grammar_check.py) defaults to port 8081, as the script does; follow WORT_LT_PORT.
export WORT_LT_URL="${WORT_LT_URL:-http://127.0.0.1:${WORT_LT_PORT:-8081}}"

child=
cleanup() {
  trap - EXIT INT TERM
  if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
  if [ "$lt_owned" = 1 ]; then
    kill "${lt_job:-}" 2>/dev/null || true
    "$lt" stop
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Not `exec`: this shell has to outlive the server to stop the LanguageTool it started.
env PYTHONPATH="$here:$here/src" uv run --group web uvicorn app.main:create_app --factory \
  --host "$WORT_DEV_HOST" --port "$WORT_DEV_PORT" \
  --ssl-certfile "$WORT_DEV_TLS_CERT" --ssl-keyfile "$WORT_DEV_TLS_KEY" \
  --reload --reload-dir app --reload-dir src &
child=$!
wait "$child"
