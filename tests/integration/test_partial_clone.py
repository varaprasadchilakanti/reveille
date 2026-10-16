"""A partial clone is refused, so Git is never made to fetch.

`git clone --filter=blob:none` leaves file contents on the server, and Git
fetches a missing object the moment a read needs one. Before 0.9.0,
`reveille generate` on such a clone exited 0 having run `git fetch origin`
and written twelve objects into `.git/objects`: a network call and a change
to Git data, the two things the README promises never happen.

The clones here are made from a local repository over `file://`, so the
tests themselves reach no network.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


def _objects(repo: Path) -> list[str]:
    return sorted(
        str(p.relative_to(repo)) for p in (repo / ".git" / "objects").rglob("*") if p.is_file()
    )


@pytest.fixture(scope="module")
def origin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("partial") / "origin"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
    }
    for day in (1, 2, 3):
        (path / f"f{day}.txt").write_text(f"{day}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "uploadpack.allowFilter", "true"], cwd=path, check=True)
    subprocess.run(["git", "config", "uploadpack.allowAnySHA1InWant", "true"], cwd=path, check=True)
    return path


def _clone(origin: Path, target: Path, *options: str) -> Path:
    subprocess.run(
        ["git", "clone", "-q", "--no-checkout", *options, f"file://{origin}", str(target)],
        check=True,
    )
    return target


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.mark.integration
class TestAPartialCloneIsRefused:
    @pytest.mark.parametrize(
        "command",
        [
            ["generate", "--output", "-"],
            ["summary"],
            ["who-changed", "f1.txt"],
            ["validate"],
        ],
        ids=["generate", "summary", "who-changed", "validate"],
    )
    def test_every_command_refuses_and_nothing_is_fetched(
        self, origin: Path, tmp_path: Path, command: list[str]
    ) -> None:
        repo = _clone(origin, tmp_path / "part", "--filter=blob:none")
        before = _objects(repo)
        assert before, "guard the guard: the clone holds some objects"

        result = CliRunner().invoke(app, [*command, "--repo", str(repo)])

        assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
        assert "is a partial clone" in result.stderr
        assert _objects(repo) == before, "Git fetched objects from the remote"

    def test_a_full_clone_of_the_same_origin_is_read(self, origin: Path, tmp_path: Path) -> None:
        repo = _clone(origin, tmp_path / "full")

        result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

        assert result.exit_code == ExitCode.SUCCESS, result.stderr
        assert "3 commits" in result.stdout


@pytest.mark.integration
@pytest.mark.parametrize("scope", ["worktree", "include"])
def test_a_promisor_set_outside_git_config_is_refused_too(tmp_path: Path, scope: str) -> None:
    """Before Git 2.44 nothing stops a lazy fetch, so the refusal must see every
    config scope Git reads: worktree config and included files as well."""
    repo = tmp_path / "r"
    repo.mkdir()
    run = {"cwd": repo, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q", "-b", "main"], **run)  # type: ignore[call-overload]
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], **run)  # type: ignore[call-overload]
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"], **run
    )  # type: ignore[call-overload]
    subprocess.run(["git", "remote", "add", "origin", "https://example.test/r.git"], **run)  # type: ignore[call-overload]
    if scope == "worktree":
        subprocess.run(["git", "config", "extensions.worktreeConfig", "true"], **run)  # type: ignore[call-overload]
        subprocess.run(["git", "config", "--worktree", "remote.origin.promisor", "true"], **run)  # type: ignore[call-overload]
    else:
        (tmp_path / "extra.cfg").write_text(
            '[remote "origin"]\n\tpromisor = true\n', encoding="utf-8"
        )
        subprocess.run(["git", "config", "include.path", str(tmp_path / "extra.cfg")], **run)  # type: ignore[call-overload]

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "partial clone" in result.stderr


@pytest.mark.integration
@pytest.mark.parametrize(
    ("key", "value", "refused"),
    [
        ("extensions.partialClone", "origin", True),
        ("extensions.partialClone", "", False),
        ("remote.origin.promisor", "false", False),
    ],
)
def test_worktree_config_is_read_for_what_it_says(
    tmp_path: Path, key: str, value: str, refused: bool
) -> None:
    """Worktree config is out of GitPython's sight, so Git's own answer decides:
    `extensions.partialClone` names a promisor remote, an empty one names none, and
    `promisor = false` is none."""
    repo = tmp_path / "r"
    repo.mkdir()
    run = {"cwd": repo, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q", "-b", "main"], **run)  # type: ignore[call-overload]
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], **run)  # type: ignore[call-overload]
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"], **run
    )  # type: ignore[call-overload]
    subprocess.run(["git", "remote", "add", "origin", "https://example.test/r.git"], **run)  # type: ignore[call-overload]
    subprocess.run(["git", "config", "extensions.worktreeConfig", "true"], **run)  # type: ignore[call-overload]
    subprocess.run(["git", "config", "--worktree", key, value], **run)  # type: ignore[call-overload]

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    if refused:
        assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
        assert "partial clone" in result.stderr
    else:
        assert result.exit_code == ExitCode.SUCCESS, result.stderr
