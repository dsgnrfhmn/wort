import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from wort import cli, paths, syncing
from wort.store import Store

ROOT = Path(__file__).resolve().parent.parent


def write_config(tmp_path, url="https://127.0.0.1:8456/sync", token="wsync_x" * 5, mode=0o600, ca=None):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    tok = tmp_path / "token"
    tok.write_text(token)
    tok.chmod(mode)
    (cfg / "sync.json").write_text(json.dumps({"url": url, "token_file": str(tok), "ca_file": str(ca or tmp_path / "ca.pem")}))
    return tok


def test_not_configured_is_none_and_invalid_configs_are_refused(tmp_path):
    assert syncing.load_config() is None
    cfg = tmp_path / "config"
    cfg.mkdir()
    for bad in ["not json", "{}", json.dumps({"url": "http://10.0.0.5:8456/sync", "token_file": "t", "ca_file": "c"}),
                json.dumps({"url": "https://user:pw@10.0.0.5:8456/sync", "token_file": "t", "ca_file": "c"}),
                json.dumps({"url": "https://sync.example.com:8456/sync", "token_file": "t", "ca_file": "c"}),
                json.dumps({"url": "https://10.0.0.5/sync", "token_file": "t", "ca_file": "c"})]:
        (cfg / "sync.json").write_text(bad)
        with pytest.raises(syncing.SyncError):
            syncing.load_config()
    (cfg / "sync.json").write_text(json.dumps({"url": "https://10.0.0.5:8456/sync", "token_file": "t", "ca_file": "c"}))
    c = syncing.load_config()
    assert c.endpoint == ("10.0.0.5", 8456) and c.path == "/sync"


@pytest.mark.skipif(os.name != "posix", reason="file modes")
def test_token_file_must_be_private(tmp_path):
    tok = write_config(tmp_path, mode=0o644)
    with pytest.raises(syncing.SyncError, match="chmod 600"):
        syncing.read_token(tok)
    tok.chmod(0o600)
    assert syncing.read_token(tok).startswith("wsync_")
    tok.write_text("")
    with pytest.raises(syncing.SyncError):
        syncing.read_token(tok)
    with pytest.raises(syncing.SyncError):
        syncing.read_token(tmp_path / "missing")


class FakeConn:
    def __init__(self, status=200, body=b'{"words_new": 1}', error=None):
        self.status, self.body, self.error, self.sent = status, body, error, None

    def request(self, method, path, body=None, headers=None):
        if self.error:
            raise self.error
        self.sent = (method, path, body, headers)

    def getresponse(self):
        outer = self
        return type("R", (), {"status": outer.status, "read": lambda s, n=None: outer.body})()

    def close(self):
        pass


def cfg_obj(tmp_path):
    return syncing.SyncConfig("10.0.0.5", 8456, "/sync", tmp_path / "t", tmp_path / "ca")


def test_push_sends_bearer_token_and_json_and_returns_counts(tmp_path):
    conn = FakeConn()
    out = syncing.push(b'{"a": 1}', cfg_obj(tmp_path), "wsync_tok", connection=conn)
    method, path, body, headers = conn.sent
    assert (method, path, body) == ("POST", "/sync", b'{"a": 1}')
    assert headers["Authorization"] == "Bearer wsync_tok" and out == {"words_new": 1}


@pytest.mark.parametrize("conn,msg", [
    (FakeConn(401, b'{"error": "unauthorized"}'), "rejected the token"),
    (FakeConn(400, b'{"error": "bad file"}'), "bad file"),
    (FakeConn(500, b"<html>"), r"refused the upload \(500\)"),
    (FakeConn(error=ConnectionRefusedError()), "could not reach"),
    (FakeConn(error=ssl.SSLError("bad cert")), "could not reach"),
])
def test_push_errors_are_readable_and_never_include_the_token(tmp_path, conn, msg):
    with pytest.raises(syncing.SyncError, match=msg) as e:
        syncing.push(b"{}", cfg_obj(tmp_path), "wsync_SECRET", connection=conn)
    assert "wsync_SECRET" not in str(e.value)


def test_sync_command_reports_missing_config(capsys):
    with pytest.raises(SystemExit):
        cli.main(["sync"])
    assert "not configured" in capsys.readouterr().out


def test_removed_download_options_are_gone():
    for argv in (["import", "--download"], ["import"]):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(argv)
    assert not hasattr(__import__("wort.dictionary.importer", fromlist=["x"]), "download")


def test_install_translation_needs_local_model_files(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["install-translation"])


def run_py(code, env_extra=None, tmp=None):
    env = {**os.environ, "PYTHONPATH": f"{ROOT}/src", "WORT_CONFIG_HOME": str(tmp), **(env_extra or {})}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30)


def test_cli_process_cannot_reach_other_hosts_but_the_sync_endpoint(tmp_path):
    write_config(tmp_path, url="https://192.0.2.10:8456/sync")
    code = (
        "import socket\n"
        "from wort import cli, netguard\n"
        "cli._install_netguard()\n"
        "def try_(addr):\n"
        "    s = socket.socket(); s.settimeout(0.2)\n"
        "    try: s.connect(addr); return 'connected'\n"
        "    except netguard.NetworkBlocked: return 'blocked'\n"
        "    except OSError: return 'allowed-by-guard'\n"
        "print(try_(('93.184.216.34', 443)), try_(('192.0.2.10', 8456)), try_(('192.0.2.10', 22)))\n"
    )
    r = run_py(code, tmp=tmp_path / "config")
    assert r.stdout.split() == ["blocked", "allowed-by-guard", "blocked"], r.stderr


def test_without_config_even_the_sync_address_is_blocked(tmp_path):
    code = ("import socket\nfrom wort import cli, netguard\ncli._install_netguard()\n"
            "s = socket.socket()\n"
            "try: s.connect(('192.0.2.10', 8456)); print('no')\n"
            "except netguard.NetworkBlocked: print('blocked')\n")
    assert run_py(code, tmp=tmp_path / "nocfg").stdout.strip() == "blocked"


@pytest.mark.skipif(not Path("/usr/bin/openssl").exists(), reason="openssl needed to make a test certificate")
def test_end_to_end_cli_push_to_the_sync_app_over_verified_https(tmp_path, monkeypatch):
    import uvicorn

    from app import auth
    from app.db import WebStore
    from app.sync_app import TOKEN_PREFIX, create_sync_app, hash_token

    key, crt = tmp_path / "k.pem", tmp_path / "ca.pem"
    subprocess.run(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "2", "-keyout", str(key),
                    "-out", str(crt), "-subj", "/CN=wort.test", "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
    db = tmp_path / "web.db"
    store = WebStore(db)
    uid = store.create_user("anna", auth.hash_password("correct horse battery")).id
    token = TOKEN_PREFIX + "e2e" * 12
    store.create_sync_token(uid, hash_token(token), "test")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_sync_app(db), host="127.0.0.1", port=port, ssl_keyfile=str(key),
                                           ssl_certfile=str(crt), log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    try:
        write_config(tmp_path, url=f"https://127.0.0.1:{port}/sync", token=token, ca=crt)
        monkeypatch.setenv("WORT_CONFIG_HOME", str(tmp_path / "config"))
        local = Store(paths.user_db())
        local.add_word("Haus", "noun", None)
        local.log_query("Haus", True)
        cli.main(["sync"])
        assert store.history(uid) and store.history(uid)[0].query == "Haus"
        # a wrong certificate is refused, not trusted
        other = tmp_path / "other.pem"
        subprocess.run(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "2", "-keyout",
                        str(tmp_path / "k2.pem"), "-out", str(other), "-subj", "/CN=evil", "-addext",
                        "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
        write_config(tmp_path, url=f"https://127.0.0.1:{port}/sync", token=token, ca=other)
        with pytest.raises(SystemExit):
            cli.main(["sync"])
    finally:
        server.should_exit = True
