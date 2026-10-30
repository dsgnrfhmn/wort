#!/usr/bin/env bash
# Local LanguageTool server for the web app's grammar check, as a rootless podman container.
#
#   scripts/languagetool.sh start | ensure | ready | stop | status | check
#
#   start   (re)creates the container and waits until it answers
#   ensure  leaves a running one alone, starts a stopped one, creates a missing one (what scripts/dev.sh uses)
#   ready   exit 0 when it answers, 1 when not; prints nothing
#
# It listens on 127.0.0.1 only (CLAUDE.md: LanguageTool on loopback; the app's client refuses other hosts). The web
# app on the same machine reaches it at its default WORT_LT_URL (http://127.0.0.1:8081), so anyone who opens the app
# from the LAN (scripts/dev.sh) sees the grammar results; the LanguageTool port itself is never on the LAN.
# scripts/dev.sh calls `ensure` when it starts and `stop` when it ends; compose.yaml has its own service (wort-lt) for
# the deployed stack. Never run both on one host: each takes about 1 GB of RAM.
# The image is pinned by digest; bump both together (compose.yaml too) and record it in DECISIONS.md (D4).
set -euo pipefail

IMAGE="docker.io/erikvl87/languagetool:6.5@sha256:9bc387f54513615648898ad60dd91bad7ba3c3b018cb2abe9f0ba61ec70681c4"  # 6.6 ships Java 11 for a Java 17 build (does not start)
NAME="wort-languagetool"
PORT="${WORT_LT_PORT:-8081}"
URL="http://127.0.0.1:${PORT}"

ready() { curl -fsS -m 2 "${URL}/v2/languages" >/dev/null 2>&1; }

launch() {
  podman run -d --replace --name "$NAME" \
    -p "127.0.0.1:${PORT}:8010" \
    --memory 1500m -e Java_Xms=256m -e Java_Xmx=1g \
    --cap-drop ALL --security-opt no-new-privileges \
    --restart unless-stopped \
    "$IMAGE" >/dev/null
}

wait_ready() {
  for _ in $(seq 1 90); do
    if ready; then echo "LanguageTool is up at ${URL}"; return 0; fi
    sleep 1
  done
  echo "languagetool.sh: no answer from ${URL} after 90 s; see: podman logs ${NAME}" >&2
  return 1
}

case "${1:-status}" in
  start)
    launch
    wait_ready
    ;;
  ensure)
    if ready; then echo "LanguageTool already answers at ${URL}"; exit 0; fi
    if podman container exists "$NAME" 2>/dev/null; then
      podman start "$NAME" >/dev/null   # a stopped one keeps its image; `start` is the way to a new image
    else
      launch
    fi
    wait_ready
    ;;
  ready)
    ready
    ;;
  stop)
    podman rm -f "$NAME" >/dev/null 2>&1 || true
    echo "LanguageTool stopped"
    ;;
  status)
    podman ps -a --filter "name=^${NAME}$" --format '{{.Names}}  {{.Status}}  {{.Ports}}'
    if ready; then echo "answers at ${URL}"; else echo "no answer at ${URL}"; exit 1; fi
    ;;
  check)
    # One known mistake: expect DE_AGREEMENT suggesting "das Haus" / "dem Haus".
    curl -fsS -m 10 "${URL}/v2/check" --data-urlencode "language=de-DE" --data-urlencode "text=Ich sehe den Haus." \
      | python3 -c 'import json, sys; m = json.load(sys.stdin)["matches"]; print(len(m), "match(es):", [(x["rule"]["id"], [r["value"] for r in x["replacements"][:3]]) for x in m])'
    ;;
  *)
    echo "usage: $0 start | ensure | ready | stop | status | check" >&2
    exit 2
    ;;
esac
