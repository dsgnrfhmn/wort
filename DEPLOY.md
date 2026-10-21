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

## 3b. CLI sync (port 8456, write-only token)

The CLI pushes its words/history to `POST https://<LAN-IP>:8456/sync` (compose publishes the port on the
same LAN IP as 8455; nginx serves only that route there). Per user:

    podman exec -it wort-web python scripts/synctoken.py create NAME "laptop"   # prints the token ONCE
    podman exec -it wort-web python scripts/synctoken.py list NAME
    podman exec -it wort-web python scripts/synctoken.py revoke NAME TOKEN_ID

On the CLI machine: put the token in a file (`chmod 600`), copy the server certificate (`wort.crt`) next to
it, and create `~/.config/wort/sync.json`:

    {"url": "https://<LAN-IP>:8456/sync", "token_file": "/home/me/.config/wort/sync.token",
     "ca_file": "/home/me/.config/wort/wort.crt"}

The url must use the IP address and an explicit port. Then `wort sync`. The token can only add words and
history to that one user; it cannot read data or sign in.

## 4. Firewall (ufw): allow the LAN to reach this socket only

    sudo ufw allow from <LAN-SUBNET> to <LAN-IP> port 8455 proto tcp comment 'wort https'
    sudo ufw allow from <CLI-MACHINE-IP> to <LAN-IP> port 8456 proto tcp comment 'wort cli sync'  # only the CLI machine
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

## 7. CLI network (the CLI has no network except the sync port)

The CLI never downloads. Fetch big files separately, on a machine where that is fine:

    python scripts/fetch_data.py dictionary downloads/      # ~1 GB; then: wort import --file downloads/kaikki.org-dictionary-German.jsonl
    python scripts/fetch_data.py models downloads/          # needs `uv sync --group mt`; then: wort install-translation downloads/*.argosmodel

Cut the CLI's network at the OS level and prove it:

    scripts/wort-offline --check        # PASS: a public address is not reachable
    alias wort=/path/to/wort/scripts/wort-offline

- Linux: `systemd-run --user` with `IPAddressDeny=any`, allowing loopback and the sync server's IP (by IP,
  not port). For a port-level rule use `deploy/cli/wort-cli.nft` with a dedicated user (root, once).
- macOS: `sandbox-exec` with `deploy/cli/wort.sb`: loopback and `IP:port` only.
- The in-process guard (`src/wort/netguard.py`) blocks everything else inside the CLI as a second layer;
  it does not replace the OS rule. Neither was run in the development container: run `--check` on the real
  machine and read its result.
- Web side: the sync service has no outbound access; the web app's only outbound destination is the AI API,
  once D0r is confirmed (section 6).
