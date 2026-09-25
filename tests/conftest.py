import pytest

from metapet.paths import DataHome
from metapet.store import Store


@pytest.fixture
def home(tmp_path) -> DataHome:
    return DataHome(tmp_path / "home", "test")


@pytest.fixture
def store(home) -> Store:
    store = Store(home)
    store.init()
    return store


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Keep tests away from the real data home and git identity."""
    monkeypatch.delenv("METAPET_HOME", raising=False)
    for key, value in {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(key, value)
