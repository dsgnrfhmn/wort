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
    return TestClient(app, follow_redirects=False)


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
    c = TestClient(app, follow_redirects=False)
    for _ in range(2):
        assert login(c, "anna", "wrong password here").status_code == 401
    assert login(c, "anna", PASSWORD).status_code == 429


def test_logout_ends_the_session(client, users):
    login(client)
    r = client.post("/logout", data={"csrf": client.cookies.get("wort_csrf")})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/").status_code == 303


def test_users_do_not_see_each_others_history(app, store, users):
    ana, ben = TestClient(app, follow_redirects=False), TestClient(app, follow_redirects=False)
    login(ana, "anna"); login(ben, "ben")
    from datetime import datetime
    store.add_history(store.user_by_name("anna")[0].id, [("Geheimwort", True, datetime(2026, 10, 1))])
    assert "Geheimwort" in ana.get("/history").text
    assert "Geheimwort" not in ben.get("/history").text
