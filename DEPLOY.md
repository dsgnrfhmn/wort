# Deploy (web dashboard, LAN only)

Same principle as <other-service>: rootless podman, nginx terminates TLS on the host's LAN IP,
the Python app listens on 127.0.0.1 inside nginx's network namespace and is never published.
Set the bind address before `podman compose up`: `export WORT_BIND_IP=<LAN-IP>` (the host's LAN address; compose refuses to start without it).
The maintainer runs this on the host; the dev machine does not deploy.

Open: no authentication yet (decided 2026-10-18). Anyone on <LAN-SUBNET> can import and
change favorites. ufw below is the only gate until login lands (PLAN.md Step 1).

## 1. TLS cert (once, outside the repo)

    mkdir -p ~/.config/wort/certs && chmod 700 ~/.config/wort/certs
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -keyout ~/.config/wort/certs/wort.key -out ~/.config/wort/certs/wort.crt \
      -subj "/CN=wort.local" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:<LAN-IP>"
    chmod 600 ~/.config/wort/certs/wort.key

Regenerate if the host's LAN IP changes (also edit `ports:` in `compose.yaml`).

## 2. Dictionary

`~/.local/share/wort/dictionary.db` must exist (built by the CLI importer); it is mounted
read-only.

## 3. Start

    podman-compose up -d --build

## 4. Firewall (ufw): allow the LAN to reach this socket only

    sudo ufw allow from <LAN-SUBNET> to <LAN-IP> port 8455 proto tcp comment 'wort https'
    sudo ufw status numbered

## 5. Verify

    ss -ltn | grep -E '8455|8000'      # only <LAN-IP>:8455, nothing on 8000
    curl -k https://<LAN-IP>:8455/            # 200
    curl -k --max-time 3 http://<LAN-IP>:8000/   # refused
    # from a second LAN host: https://<LAN-IP>:8455 loads; from outside the LAN it does not
