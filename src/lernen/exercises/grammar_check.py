"""Optional grammar checking through a LanguageTool server running on this machine.

Only loopback URLs are used unless LERNEN_LT_ALLOW_REMOTE=1, so sentences never
leave the computer by accident (the public api.languagetool.org is not used).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = "http://127.0.0.1:8081"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass
class Issue:
    message: str
    offset: int
    length: int
    replacements: list[str]


def server_url() -> str | None:
    url = os.environ.get("LERNEN_LT_URL", DEFAULT_URL).rstrip("/")
    host = urllib.parse.urlparse(url).hostname
    if host not in _LOCAL_HOSTS and os.environ.get("LERNEN_LT_ALLOW_REMOTE") != "1":
        return None
    return url


def check(text: str, timeout: float = 5.0) -> list[Issue] | None:
    """Grammar issues in `text`, or None if no local LanguageTool is reachable."""
    url = server_url()
    if url is None or os.environ.get("LERNEN_LT_DISABLE") == "1":
        return None
    data = urllib.parse.urlencode({"language": "de-DE", "text": text}).encode()
    try:
        with urllib.request.urlopen(f"{url}/v2/check", data=data, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return [
        Issue(
            message=m.get("message", ""),
            offset=m.get("offset", 0),
            length=m.get("length", 0),
            replacements=[r.get("value", "") for r in m.get("replacements", [])[:3]],
        )
        for m in payload.get("matches", [])
    ]
