import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app

PASSWORD = "correct horse battery"


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=tmp_path / "web.db", dict_path=tmp_path / "none.db", secure_cookies=False)


@pytest.fixture
def store(app):
    # the app owns its store; reach it through a user created via the same DB file
    from app.db import WebStore
    return WebStore(app.state.db_path)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("wort_csrf")


def login(client, name="anna", password=PASSWORD):
    return client.post("/login", data={"csrf": csrf(client), "name": name, "password": password})


@pytest.fixture
def users(store):
    store.create_user("anna", auth.hash_password(PASSWORD))
    store.create_user("ben", auth.hash_password(PASSWORD))


@pytest.mark.parametrize("path", ["/", "/history", "/favorites", "/exercise/Haus", "/words/1", "/ueben", "/ueben/s/1", "/texte"])
def test_pages_redirect_to_login_when_anonymous(client, path):
    r = client.get(path)
    assert r.status_code == 303 and r.headers["location"] == "/login"


@pytest.mark.parametrize("path", ["/import", "/favorites/toggle", "/logout", "/ueben/saetze", "/ueben/s/1/answer", "/ueben/s/1/next", "/words/1/translation", "/words/1/delete"])
def test_post_routes_need_login(client, path):
    r = client.post(path, data={"csrf": "x"})
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_login_page_is_public_and_has_no_nav(client):
    r = client.get("/login")
    assert r.status_code == 200 and "ds-nav-bar" not in r.text and 'name="password"' in r.text
    assert 'type="password"' in r.text


def test_login_sets_httponly_samesite_cookie_and_opens_pages(client, users):
    r = login(client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client, users):
    a = login(client, "anna", "not the password!!")
    b = login(client, "nobody", PASSWORD)
    assert a.status_code == b.status_code == 401
    assert "Wrong name or password." in a.text and "Wrong name or password." in b.text
    assert client.get("/").status_code == 303


def test_login_requires_csrf(client, users):
    csrf(client)
    r = client.post("/login", data={"csrf": "forged", "name": "anna", "password": PASSWORD})
    assert r.status_code == 403


def test_login_is_throttled(tmp_path):
    app = create_app(db_path=tmp_path / "w.db", dict_path=tmp_path / "n.db", secure_cookies=False,
                     throttle=auth.LoginThrottle(limit=2, window=60))
    from app.db import WebStore
    WebStore(tmp_path / "w.db").create_user("anna", auth.hash_password(PASSWORD))
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    for _ in range(2):
        assert login(c, "anna", "wrong password here").status_code == 401
    assert login(c, "anna", PASSWORD).status_code == 429


def test_logout_ends_the_session(client, users):
    login(client)
    r = client.post("/logout", data={"csrf": client.cookies.get("wort_csrf")})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/").status_code == 303


def test_users_do_not_see_each_others_history(app, store, users):
    ana, ben = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000)), TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    login(ana, "anna"); login(ben, "ben")
    from datetime import datetime
    store.add_history(store.user_by_name("anna")[0].id, [("Geheimwort", True, datetime(2026, 10, 1))])
    assert "Geheimwort" in ana.get("/history").text
    assert "Geheimwort" not in ben.get("/history").text


@pytest.mark.parametrize("host", ["192.168.1.20", "10.0.0.5", "testclient", "::ffff:192.168.1.20"])
def test_insecure_cookies_serve_loopback_only(app, host):
    # Plain-http dev (no Secure cookies) must never answer a LAN client: the password would travel in clear.
    c = TestClient(app, follow_redirects=False, client=(host, 50000))
    for path in ("/login", "/", "/static/app.js"):
        r = c.get(path)
        assert r.status_code == 403 and "127.0.0.1" in r.text
        assert "set-cookie" not in r.headers


@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1"])
def test_insecure_cookies_allow_loopback(app, host):
    assert TestClient(app, follow_redirects=False, client=(host, 50000)).get("/login").status_code == 200


def test_secure_cookies_have_no_loopback_guard(tmp_path):
    # Behind the TLS front the app sees nginx (loopback) anyway; the guard is only for the plain-http mode.
    secure = create_app(db_path=tmp_path / "s.db", dict_path=tmp_path / "n.db", secure_cookies=True)
    assert TestClient(secure, follow_redirects=False, client=("192.168.1.20", 50000)).get("/login").status_code == 200


def test_is_loopback():
    assert auth.is_loopback("127.0.0.1") and auth.is_loopback("::1") and auth.is_loopback("::ffff:127.0.0.1")
    assert not any(auth.is_loopback(h) for h in ["0.0.0.0", "192.168.0.1", "::", "localhost", "", "testclient"])
