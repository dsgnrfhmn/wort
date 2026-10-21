"""Push the word list and history to the web app: the CLI's only network use.

One HTTPS POST to the configured endpoint (an IP address and a port on the LAN), carrying the same JSON
as `wort export`, with a write-only token. The token file must be private (mode 600); the server's
certificate is checked against the CA/certificate file in the config (self-signed is fine, pinned).
Nothing is read back except the small JSON result. See DEPLOY.md, "CLI network".
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import ssl
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from wort import paths

CONFIG_NAME = "sync.json"
MAX_RESPONSE = 64 * 1024
TIMEOUT = 15.0


class SyncError(RuntimeError):
    """Misconfiguration or a failed push; the message says what to fix."""


@dataclass(frozen=True)
class SyncConfig:
    host: str
    port: int
    path: str
    token_file: Path
    ca_file: Path

    @property
    def endpoint(self) -> tuple[str, int]:
        return self.host, self.port


def config_path() -> Path:
    return paths.config_dir() / CONFIG_NAME


def load_config(path: Path | None = None) -> SyncConfig | None:
    """The sync settings, or None when sync is not configured. Raises SyncError when they are invalid."""
    path = path or config_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        url = urlsplit(str(raw["url"]))
        token_file, ca_file = Path(raw["token_file"]).expanduser(), Path(raw["ca_file"]).expanduser()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SyncError(f"{path}: needs JSON with url, token_file and ca_file") from exc
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise SyncError(f"{path}: url must be https://IP:PORT/PATH with no credentials")
    try:
        ipaddress.ip_address(url.hostname)
    except ValueError as exc:  # no DNS: the network guard and the OS rule both name an address
        raise SyncError(f"{path}: use the server's IP address, not a name ({url.hostname})") from exc
    if url.port is None:
        raise SyncError(f"{path}: the url needs an explicit port")
    return SyncConfig(url.hostname, url.port, url.path or "/sync", token_file, ca_file)


def read_token(token_file: Path) -> str:
    """The token, only if the file is a private regular file (a group/world-readable token is refused)."""
    try:
        st = os.stat(token_file)
    except OSError as exc:
        raise SyncError(f"token file not found: {token_file}") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_size > 512:
        raise SyncError(f"token file {token_file} must be a small regular file")
    if os.name == "posix" and st.st_mode & 0o077:
        raise SyncError(f"token file {token_file} must not be readable by others: chmod 600")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise SyncError(f"token file {token_file} is empty")
    return token


def push(payload: bytes, config: SyncConfig, token: str, connection=None) -> dict:
    """POST the export JSON. `connection` is a test seam; by default a verified HTTPS connection."""
    if connection is None:
        try:
            context = ssl.create_default_context(cafile=str(config.ca_file))
        except (OSError, ssl.SSLError) as exc:
            raise SyncError(f"cannot read the certificate file {config.ca_file}") from exc
        connection = http.client.HTTPSConnection(config.host, config.port, timeout=TIMEOUT, context=context)
    try:
        connection.request("POST", config.path, body=payload,
                           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        resp = connection.getresponse()  # redirects are not followed
        body = resp.read(MAX_RESPONSE)
        status = resp.status
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise SyncError(f"could not reach {config.host}:{config.port}: {type(exc).__name__}") from exc
    finally:
        connection.close()
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if status == 401:
        raise SyncError("the server rejected the token (revoked or wrong)")
    if status != 200:
        raise SyncError(f"the server refused the upload ({status}): {str(data.get('error', ''))[:120]}")
    return data
