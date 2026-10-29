from pathlib import Path

import pytest

from wort.dictionary.importer import import_file
from wort.dictionary.lookup import Dictionary
from wort.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "german_sample.jsonl"


@pytest.fixture(autouse=True)
def _netguard_off_between_tests():
    yield
    from wort import netguard
    netguard.uninstall()  # cli.main() installs it process-wide; tests must not leak it


def pytest_configure(config):
    config.addinivalue_line("markers", "english_ui: run with the default (English) web interface")


@pytest.fixture(autouse=True)
def _german_interface(request, monkeypatch):
    """The web tests written before the English interface check its German texts: users they create get the
    German interface and direct calls run in German. Tests marked english_ui keep the default (English)."""
    if request.node.get_closest_marker("english_ui"):
        yield
        return
    try:
        from app import i18n
        from app.db import WebStore
    except ImportError:  # the CLI tests run without the web dependencies
        yield
        return
    create = WebStore.create_user

    def create_user(self, name, password_hash, now=None):
        user = create(self, name, password_hash, now)
        self.set_ui_lang(user.id, "de")
        user.ui_lang = "de"
        return user

    monkeypatch.setattr(WebStore, "create_user", create_user)
    token = i18n._lang.set("de")
    yield
    i18n._lang.reset(token)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORT_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("WORT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WORT_LT_DISABLE", "1")


@pytest.fixture(scope="session")
def dict_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("dict") / "dictionary.db"
    import_file(FIXTURE, path)
    return path


@pytest.fixture
def dictionary(dict_path) -> Dictionary:
    return Dictionary(dict_path)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "user.db")
