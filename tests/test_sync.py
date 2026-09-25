import subprocess

import pytest

from metapet import sync


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def test_sync_requires_repo(store):
    with pytest.raises(sync.SyncError, match="not a git repository"):
        sync.sync(store.home.path)


def test_sync_without_remote_only_commits(store):
    sync.init_repo(store.home.path)
    store.create("First")
    assert sync.sync(store.home.path)[-1].startswith("no remote")
    assert "ideas: sync" in git("-C", str(store.home.path), "log", "--format=%s")


def test_sync_round_trip_through_bare_remote(store, tmp_path):
    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", "-b", "main", str(remote))
    sync.init_repo(store.home.path, str(remote))
    store.create("First")
    steps = sync.sync(store.home.path, "add first")
    assert "pushed to origin/main" in steps

    clone = tmp_path / "clone"
    git("clone", "-q", str(remote), str(clone))
    (clone / "ideas" / "second.md").write_text("from elsewhere\n")
    git("-C", str(clone), "add", "-A")
    git("-C", str(clone), "commit", "-q", "-m", "second")
    git("-C", str(clone), "push", "-q")

    store.create("Third")
    steps = sync.sync(store.home.path)
    assert "pulled origin/main" in steps
    assert (store.home.ideas / "second.md").exists()
    assert "Third" in git("-C", str(clone), "pull", "-q") + git(
        "-C", str(clone), "show", "HEAD:ideas/third.md"
    )
