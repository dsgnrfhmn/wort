# Deploy (web dashboard, LAN only)

Same principle as <other-service>: rootless podman, nginx terminates TLS on the host's LAN IP,
the Python app listens on 127.0.0.1 inside nginx's network namespace and is never published.
Set the bind address before `podman compose up`: `export WORT_BIND_IP=<LAN-IP>` (the host's LAN address; compose refuses to start without it).
The maintainer runs this on the host; the dev machine does not deploy.

Accounts: login exists (argon2, invite-only, no signup). Create users on the host, see step 3a.
ufw below stays as the network gate.

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

## 3a. Users (no signup; the admin creates them)

    podman exec -it wort-web python scripts/adduser.py NAME      # prompts for the password (min. 12 characters)

The first user created adopts the history and favorites that existed before accounts. Sessions are
cookies (HttpOnly, SameSite=Strict, Secure); the app is meant to be reached over the TLS front only.
For plain-http local development set `WORT_INSECURE_COOKIES=1` (never on the server).

## 4. Firewall (ufw): allow the LAN to reach this socket only

    sudo ufw allow from <LAN-SUBNET> to <LAN-IP> port 8455 proto tcp comment 'wort https'
    sudo ufw status numbered

## 5. Verify

    ss -ltn | grep -E '8455|8000'      # only <LAN-IP>:8455, nothing on 8000
    curl -k https://<LAN-IP>:8455/            # 200
    curl -k --max-time 3 http://<LAN-IP>:8000/   # refused
    # from a second LAN host: https://<LAN-IP>:8455 loads; from outside the LAN it does not

## 6. AI calls (off; NOT applied until D0 is confirmed in DECISIONS.md)

Default: `WORT_AI_ENABLED` unset, no key anywhere, the app makes no outbound connections. To enable
later, the maintainer does all of this on the server; the dev machine never holds a key.

- **Key**: a separate Anthropic workspace with a spend limit; one key in an env file outside the repo
  (`~/.config/wort/ai.env`, mode 600, owned by the service user), passed with `env_file:`; never in git,
  never in the image, never in logs. Variables: `WORT_AI_ENABLED=1`, `ANTHROPIC_API_KEY`,
  `WORT_AI_MODEL` (default `claude-haiku-5-5`), `WORT_AI_CHECK_MODEL` (only if the 20-30 case test shows
  Haiku missing errors), `WORT_AI_DAILY_CAP` (default 50 calls per user per day).
- **Network**: today the stack has no egress rule beyond the host's. Enabling needs egress to
  `api.anthropic.com:443` only. IP allow-lists do not fit a hosted API; use an egress proxy that
  allows that one hostname, or firewall rules refreshed from DNS. Open question for the maintainer.
- **SDK**: `anthropic` is not a project dependency; install it into the image only when enabling, and
  check the request shape, model ids and error handling in `app/ai/anthropic_provider.py` against the
  official documentation (the file is a reviewed draft, it has never made a call).
- **Data sent**: only the learner's sentence or answer, the target forms and the task text. Never photos
  or Texte. The daily cap is enforced on the server before the request; failures count as calls.
- **Failure behaviour**: invalid or failed replies change no score; sentence checks fall back to the
  local check and say so.
