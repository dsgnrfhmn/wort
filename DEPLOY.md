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
For plain-http local development set `WORT_INSECURE_COOKIES=1` (never on the server). In that mode the app answers
loopback clients only (127.0.0.1 / ::1) and returns 403 to everyone else, so a run on a LAN address cannot send the
password or the session cookie in clear text; for the LAN use `scripts/dev.sh` (https).

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

## 6. AI calls (web backend only; off until the key is installed)

D0r is confirmed (2026-10-21). Default stays off: `WORT_AI_ENABLED` unset, no key, no outbound connection.
The maintainer does all of this on the server; the dev machine, the CLI machine and agent hosts never hold the key.

1. **Key**: a separate Anthropic workspace with a spend limit; one key in `~/.config/wort/ai.env`
   (`chmod 600`, outside the repo), passed to `wort-web` only (`env_file:`), never to `wort-sync`:

       WORT_AI_ENABLED=1
       ANTHROPIC_API_KEY=sk-ant-...
       WORT_AI_DAILY_CAP=50                 # calls per user per day (failed calls count)
       WORT_AI_FEATURES=check,explain       # start small; add tasks,recheck,rule,answer one by one
       # WORT_AI_MODEL=claude-haiku-5-5     # default; WORT_AI_CHECK_MODEL only if spikes/ai_eval.md says Haiku misses errors

2. **SDK**: `podman build --build-arg WITH_AI=1` (installs `anthropic`); on a plain venv `uv sync --group ai`.
3. **Prove it**: `PYTHONPATH=.:src python scripts/ai_smoke.py` (six real calls, fixed non-private examples);
   it must print `ALL PASS`. Then run the Haiku-vs-Sonnet test (`spikes/ai_eval.md`).
4. **Network (the part code cannot do)**: `wort-web` needs egress to `api.anthropic.com:443` and nothing else;
   in compose it shares nginx's network namespace, so decide where the rule lives. IP allow-lists do not fit a
   hosted API. Options: (a) an egress proxy that allows that one hostname, set as `HTTPS_PROXY` for `wort-web`
   only (the SDK honours it); (b) host firewall rules refreshed from DNS. `wort-sync` and the CLI get no egress.
   The base URL is fixed in code (`app/ai/anthropic_provider.py`), so `ANTHROPIC_BASE_URL` cannot redirect traffic.
5. **Data sent**: only the learner's sentence/answer, target forms, task, rule name, lemmas, glosses, and the
   objection (max 300 characters), each through `wort.sanitize.for_model`; never photos or Texte. Replies are
   schema-validated and must be plain text (no markup, links or hidden characters), else nothing is graded.
6. **Failure behaviour**: invalid, refused, failed or capped calls change no score; sentence checks fall back
   to the local check and say so. Logs hold only block name, model, token counts and request id (redacted).

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
