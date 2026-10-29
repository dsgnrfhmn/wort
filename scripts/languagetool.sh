#!/usr/bin/env bash
# Local LanguageTool server for the web app's grammar check, as a rootless podman container.
#
#   scripts/languagetool.sh start | stop | status | check
#
# It listens on 127.0.0.1 only (CLAUDE.md: LanguageTool on loopback; the app's client refuses other hosts). The web
# app on the same machine reaches it at its default WORT_LT_URL (http://127.0.0.1:8081), so anyone who opens the app
# from the LAN (scripts/dev.sh) sees the grammar results; the LanguageTool port itself is never on the LAN.
# The image is pinned by digest; bump both together and record it in DECISIONS.md (D4).
set -euo pipefail

IMAGE="docker.io/erikvl87/languagetool:6.5@sha256:9bc387f54513615648898ad60dd91bad7ba3c3b018cb2abe9f0ba61ec70681c4"  # 6.6 ships Java 11 for a Java 17 build (does not start)
NAME="wort-languagetool"
PORT="${WORT_LT_PORT:-8081}"
URL="http://127.0.0.1:${PORT}"

ready() { curl -fsS -m 2 "${URL}/v2/languages" >/dev/null 2>&1; }

case "${1:-status}" in
  start)
    podman run -d --replace --name "$NAME" \
      -p "127.0.0.1:${PORT}:8010" \
      --memory 1500m -e Java_Xms=256m -e Java_Xmx=1g \
      --cap-drop ALL --security-opt no-new-privileges \
      --restart unless-stopped \
      "$IMAGE" >/dev/null
    for _ in $(seq 1 90); do
      if ready; then echo "LanguageTool is up at ${URL}"; exit 0; fi
      sleep 1
    done
    echo "languagetool.sh: no answer from ${URL} after 90 s; see: podman logs ${NAME}" >&2
    exit 1
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
    echo "usage: $0 start | stop | status | check" >&2
    exit 2
    ;;
esac
