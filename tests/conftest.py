from pathlib import Path

import pytest

from lernen.dictionary.importer import import_file
from lernen.dictionary.lookup import Dictionary
from lernen.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "german_sample.jsonl"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LERNEN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LERNEN_LT_DISABLE", "1")


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
