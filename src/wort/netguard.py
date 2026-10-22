"""Process-level network guard for the CLI/TUI.

The CLI makes no network connections except (a) loopback (a local LanguageTool) and (b) the one
configured sync endpoint (host:port). Everything else raises NetworkBlocked, including DNS lookups
for other names and unconnected UDP sends.

This is defence in depth, not a security boundary: code running in the same process can undo it.
The boundary is the OS-level rule in scripts/wort-offline (see DEPLOY.md, "CLI network").
"""

from __future__ import annotations

import ipaddress
import socket

_LOOPBACK_NAMES = {"localhost"}
_installed = False
_allowed: set[tuple[str, int]] = set()
_orig: dict[str, object] = {}


class NetworkBlocked(OSError):
    """The CLI tried to reach a destination that is not allowed."""


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _check(address, what: str) -> None:
    # AF_UNIX addresses are str/bytes paths: always fine (local IPC, asyncio's self-pipe).
    if not isinstance(address, tuple) or len(address) < 2:
        return
    host, port = str(address[0]), address[1]
    if _is_loopback(host) or (host, port) in _allowed:
        return
    raise NetworkBlocked(f"network blocked: the CLI may only reach loopback and the sync endpoint ({what} {host}:{port})")


def install(allowed: set[tuple[str, int]] | None = None) -> None:
    """Block all but loopback and `allowed` (host, port) pairs. Idempotent; a second call replaces `allowed`."""
    global _installed
    _allowed.clear()
    _allowed.update(allowed or set())
    if _installed:
        return
    _installed = True
    sock = socket.socket
    _orig.update(connect=sock.connect, connect_ex=sock.connect_ex, sendto=sock.sendto,
                 getaddrinfo=socket.getaddrinfo, create_connection=socket.create_connection)

    def connect(self, address):
        _check(address, "connect")
        return _orig["connect"](self, address)

    def connect_ex(self, address):
        _check(address, "connect")
        return _orig["connect_ex"](self, address)

    def sendto(self, data, *args):
        _check(args[-1] if args else None, "send to")
        return _orig["sendto"](self, data, *args)

    def getaddrinfo(host, port, *args, **kwargs):
        if host is not None and not _is_loopback(str(host)) and str(host) not in {h for h, _ in _allowed}:
            try:
                ipaddress.ip_address(str(host))  # numeric: no lookup happens; connect() is still checked
            except ValueError:
                raise NetworkBlocked(f"network blocked: DNS lookup for {host}") from None
        return _orig["getaddrinfo"](host, port, *args, **kwargs)

    sock.connect, sock.connect_ex, sock.sendto = connect, connect_ex, sendto
    socket.getaddrinfo = getaddrinfo


def uninstall() -> None:
    """Restore the real socket functions (tests only)."""
    global _installed
    if not _installed:
        return
    sock = socket.socket
    sock.connect, sock.connect_ex, sock.sendto = _orig["connect"], _orig["connect_ex"], _orig["sendto"]
    socket.getaddrinfo = _orig["getaddrinfo"]
    _allowed.clear()
    _installed = False
