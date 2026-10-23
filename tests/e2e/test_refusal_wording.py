# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Refusals name the actual problem, and say what to give instead."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.e2e


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["capabilities", "--format", "yaml"], "Error: --format must be text or json, not 'yaml'."),
        (["skill", "--format", "yaml"], "Error: --format must be markdown or skill, not 'yaml'."),
        (["summary", "--format", "yaml"], "Error: --format must be text, json or markdown"),
    ],
)
def test_an_unknown_format_is_refused_in_one_wording(args: list[str], message: str) -> None:
    result = CliRunner().invoke(app, args)

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert message in result.stderr


def test_skill_refuses_json_in_text_because_it_has_no_json() -> None:
    result = CliRunner().invoke(app, ["skill", "--format", "json"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert result.stderr.startswith("Error: --format must be markdown or skill, not 'json'.")


def test_who_changed_in_a_directory_that_is_not_a_repository_says_so(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    result = CliRunner().invoke(app, ["who-changed", "/etc/hosts", "--repo", str(plain)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "is not a valid Git repository" in result.stderr
    assert "outside the repository" not in result.stderr


def test_who_changed_outside_a_repository_still_names_the_repository(repo: Path) -> None:
    result = CliRunner().invoke(app, ["who-changed", "/etc/hosts", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, "positive control: " + result.stderr
    assert "outside the repository" in result.stderr


def test_an_output_with_dot_dot_is_refused_with_the_absolute_path_to_give(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(app, ["generate", "--output", "../report.html"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    expected = os.path.normpath(repo / "../report.html")
    assert f"Give the same place as an absolute path, '{expected}'" in result.stderr


def test_generate_given_a_git_directory_names_it_not_the_default_output(repo: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "-q", "--repo", str(repo / ".git")])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "is the Git directory of the working tree" in result.stderr
    assert "output path" not in result.stderr


def test_generate_given_a_file_as_the_repository_says_it_is_no_repository(repo: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "-q", "--repo", str(repo / "a.txt")])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "is not a valid Git repository" in result.stderr
    assert "output path" not in result.stderr


def test_a_refused_output_in_a_good_repository_is_still_named(repo: Path) -> None:
    """Positive control: the repository opens, so the output's own problem is said."""
    result = CliRunner().invoke(
        app, ["generate", "-q", "--repo", str(repo), "-o", str(repo / ".git" / "r.html")]
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert result.stderr.count("Error:") == 1
    assert "is inside a Git directory" in result.stderr


@pytest.mark.parametrize(
    ("flags", "hint"),
    [
        (["--exclude-path", "a.txt"], "Try removing an --exclude-path value."),
        (["--exclude-author", "a@e.test"], "Try removing an --exclude-author value."),
        (
            ["--since", "2001-01-01", "--until", "2001-02-01", "--exclude-path", "a.txt"],
            "Try widening the date range or removing an --exclude-path value.",
        ),
    ],
)
def test_an_empty_window_suggests_only_the_filters_given(
    repo: Path, flags: list[str], hint: str
) -> None:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), *flags])

    assert result.exit_code == ExitCode.NEGATIVE
    assert hint in result.stderr
    assert result.stderr.count("Try") == 1


@pytest.fixture
def superproject(tmp_path: Path, repo: Path) -> Path:
    """A repository holding `repo` as the submodule `sub`."""
    sup = tmp_path / "sup"
    sup.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=sup, check=True)
    (sup / "x").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=sup, check=True)
    identity = ["-c", "user.name=A", "-c", "user.email=a@e.test"]
    subprocess.run(["git", *identity, "commit", "-qm", "x"], cwd=sup, check=True)
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "-q", "add", str(repo), "sub"],
        cwd=sup,
        check=True,
    )
    subprocess.run(["git", *identity, "commit", "-qm", "sub"], cwd=sup, check=True)
    return sup


def test_a_path_inside_a_submodule_cannot_run_and_names_where_to_ask(superproject: Path) -> None:
    result = CliRunner().invoke(app, ["who-changed", "sub/a.txt", "--repo", str(superproject)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "is inside 'sub', another repository" in result.stderr
    assert f"--repo {superproject / 'sub'}" in result.stderr
    asked = CliRunner().invoke(app, ["who-changed", "a.txt", "--repo", str(superproject / "sub")])
    assert asked.exit_code == ExitCode.SUCCESS, "the command it names answers"


def test_a_path_no_commit_changed_is_still_a_negative_answer(superproject: Path) -> None:
    """Positive control: only a path in another repository is refused."""
    result = CliRunner().invoke(app, ["who-changed", "nope.txt", "--repo", str(superproject)])

    assert result.exit_code == ExitCode.NEGATIVE
    assert "another repository" not in result.stderr


def test_sigterm_raises_the_exit_a_terminated_process_has() -> None:
    import signal

    from reveille import cli

    with pytest.raises(SystemExit) as stopped:
        cli._stop(signal.SIGTERM, None)

    assert stopped.value.code == 143


def test_a_thread_other_than_the_main_one_installs_no_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import signal
    import threading

    from reveille import cli

    installed: list[object] = []
    monkeypatch.setattr(signal, "signal", lambda *args: installed.append(args))
    monkeypatch.setattr(signal, "getsignal", lambda _: signal.SIG_DFL)
    worker = threading.Thread(target=cli._exit_cleanly_on_sigterm)
    worker.start()
    worker.join()
    assert installed == []

    cli._exit_cleanly_on_sigterm()
    assert len(installed) == 1, "positive control: the main thread installs it"


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads any directory"
)
def test_an_unreadable_directory_above_the_output_is_passed_over(tmp_path: Path) -> None:
    from reveille import cli

    locked = tmp_path / "locked"
    (locked / "inner").mkdir(parents=True)
    locked.chmod(0o000)
    try:
        assert cli._in_a_git_directory(locked / "inner" / "r.html") is False
    finally:
        locked.chmod(0o700)


def test_a_path_below_a_directory_shaped_as_a_git_directory_is_inside_one(tmp_path: Path) -> None:
    from reveille import cli

    for name in ("objects", "refs/heads"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    assert cli._in_a_git_directory(tmp_path / "refs" / "heads" / "r.html") is True
    assert cli._in_a_git_directory(tmp_path.parent / "r.html") is False
