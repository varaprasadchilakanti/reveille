# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The release path, executed.

`.github/workflows/publish.yml` had no tests. Its failure mode is a broken
release, which is not hypothetical: v0.8.0 shipped without its SBOM because a
glob that looked right matched nothing. PR #179 then added an attestation
step, a bundle copy and an asset array to the same untested workflow.

The scripts are extracted from the workflow and run here, so what is tested is
what ships rather than a copy of it -- the approach `test_cla_gate.py` and
`test_dco_gate.py` already take. Three steps are covered: the one that decides
which release is being described, the one that copies the Sigstore bundle, and
the one that attaches assets to the Release. `gh` is stubbed, so nothing here
touches the network or any remote.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import ClassVar

import pytest

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "publish.yml"


def _step_script(step_name: str) -> str:
    """Return a step's `run:` body as the workflow ships it.

    Args:
        step_name: The step's `name:`, matched exactly.

    Returns:
        The shell script, dedented.
    """
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    marker = f"      - name: {step_name}\n"
    assert marker in workflow, f"no step named {step_name!r} in publish.yml"
    rest = workflow[workflow.index(marker) + len(marker) :]
    assert "        run: |\n" in rest, f"step {step_name!r} no longer has a run: block"
    body = rest[rest.index("        run: |\n") + len("        run: |\n") :]

    lines: list[str] = []
    for line in body.splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    script = textwrap.dedent("\n".join(lines))
    assert script.strip(), f"step {step_name!r} yielded an empty script"
    return script


def _run(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run an extracted script with a controlled environment."""
    environment = {"PATH": os.environ["PATH"], "HOME": str(cwd)}
    environment.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
class TestTheReleaseBeingDescribedIsValidated:
    """The tag reaches `GITHUB_OUTPUT` and then `gh`. It is checked twice."""

    @staticmethod
    def _resolve(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
        output = tmp_path / "gh-output"
        output.write_text("", encoding="utf-8")
        result = _run(
            _step_script("Resolve the release being described"),
            tmp_path,
            {"GITHUB_OUTPUT": str(output), "REQUESTED_TAG": "", "GITHUB_REF_NAME": "", **env},
        )
        return result, output.read_text(encoding="utf-8")

    def test_a_release_tag_yields_the_tag_and_the_sbom_filename(self, tmp_path: Path) -> None:
        result, written = self._resolve(tmp_path, GITHUB_REF_NAME="v0.9.0")
        assert result.returncode == 0, result.stderr
        assert "tag=v0.9.0" in written
        assert "file=reveille-0.9.0-sbom.cdx.json" in written

    def test_a_dispatched_tag_overrides_the_ref(self, tmp_path: Path) -> None:
        """`workflow_dispatch` exists to re-run the SBOM for an earlier tag."""
        result, written = self._resolve(tmp_path, GITHUB_REF_NAME="v9.9.9", REQUESTED_TAG="v0.8.1")
        assert result.returncode == 0, result.stderr
        assert "tag=v0.8.1" in written
        assert "file=reveille-0.8.1-sbom.cdx.json" in written

    def test_only_the_leading_v_is_stripped(self, tmp_path: Path) -> None:
        """`${tag#v}` removes one prefix, not every `v` in the string."""
        _, written = self._resolve(tmp_path, GITHUB_REF_NAME="v1.0.0-preview")
        assert "file=reveille-1.0.0-preview-sbom.cdx.json" in written

    @pytest.mark.parametrize(
        "tag",
        ["0.9.0", "main", "release-0.9.0", "", "va.b.c"],
        ids=["no-v", "branch", "prefixed", "empty", "not-numeric"],
    )
    def test_a_value_that_is_not_a_release_tag_is_refused(self, tmp_path: Path, tag: str) -> None:
        result, written = self._resolve(tmp_path, GITHUB_REF_NAME=tag)
        assert result.returncode != 0, f"{tag!r} was accepted as a release tag"
        assert "not a release tag" in result.stdout
        assert written == "", "a refused tag still wrote an output"

    @pytest.mark.parametrize(
        "tag",
        ["v1.0.0\nfile=evil.json", "v1.0.0;whoami", "v1.0.0 --draft", "v1.0.0$(id)", "v1.0.0`id`"],
        ids=["newline", "semicolon", "space", "substitution", "backtick"],
    )
    def test_a_tag_carrying_shell_or_output_syntax_is_refused(
        self, tmp_path: Path, tag: str
    ) -> None:
        """The second check, and the reason the workflow gives for it.

        The prefix test alone accepts `v1.0.0\\nfile=evil.json`, which is
        written to `GITHUB_OUTPUT` and would forge a second output naming a
        file the later steps then copy and attach.
        """
        result, written = self._resolve(tmp_path, GITHUB_REF_NAME=tag)
        assert result.returncode != 0, f"{tag!r} was accepted"
        assert "characters a tag cannot have" in result.stdout
        assert "file=evil.json" not in written


@pytest.mark.unit
class TestTheAttestationBundleIsCheckedBeforeItIsAttached:
    """A file that looks like a signature and verifies nothing is worse than none."""

    @staticmethod
    def _copy_bundle(tmp_path: Path, bundle: str | None) -> subprocess.CompletedProcess[str]:
        sbom = tmp_path / "reveille-0.9.0-sbom.cdx.json"
        sbom.write_text('{"bomFormat": "CycloneDX"}', encoding="utf-8")
        bundle_path = tmp_path / "attestation.jsonl"
        if bundle is not None:
            bundle_path.write_text(bundle, encoding="utf-8")
        return _run(
            _step_script("Keep the attestation bundle beside the SBOM"),
            tmp_path,
            {"BUNDLE_PATH": str(bundle_path), "SBOM_FILE": sbom.name},
        )

    def test_a_real_bundle_lands_beside_the_sbom(self, tmp_path: Path) -> None:
        bundle = json.dumps(
            {
                "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                "verificationMaterial": {"certificate": {"rawBytes": "..."}},
            }
        )
        result = self._copy_bundle(tmp_path, bundle)
        assert result.returncode == 0, result.stderr
        copied = tmp_path / "reveille-0.9.0-sbom.cdx.json.sigstore.json"
        assert copied.is_file()
        assert json.loads(copied.read_text(encoding="utf-8"))["verificationMaterial"]
        assert "media type:" in result.stdout

    def test_an_empty_bundle_is_refused_before_it_is_copied(self, tmp_path: Path) -> None:
        """`test -s`, and the assertion that isolates it.

        Checking only the exit code proves nothing here: with `test -s`
        removed the step still fails, because `json.load` chokes on an empty
        file. What the size check uniquely provides is that no copy is made --
        without it, `cp` first writes a zero-byte
        `<sbom>.sigstore.json`, which is precisely the file that looks like a
        signature and verifies nothing.

        Found by deleting `test -s` and watching this test pass anyway.
        """
        result = self._copy_bundle(tmp_path, "")
        assert result.returncode != 0
        assert not (tmp_path / "reveille-0.9.0-sbom.cdx.json.sigstore.json").exists(), (
            "an empty bundle was copied into place before being rejected"
        )

    def test_a_missing_bundle_is_refused(self, tmp_path: Path) -> None:
        assert self._copy_bundle(tmp_path, None).returncode != 0

    def test_json_without_verification_material_is_refused(self, tmp_path: Path) -> None:
        """The certificate chain is what makes it a bundle rather than a file."""
        result = self._copy_bundle(tmp_path, json.dumps({"mediaType": "something"}))
        assert result.returncode != 0
        assert "not a Sigstore bundle" in result.stderr

    def test_something_that_is_not_json_is_refused(self, tmp_path: Path) -> None:
        assert self._copy_bundle(tmp_path, "not json at all").returncode != 0


@pytest.mark.unit
class TestTheTwoAssetGlobsAreDisjoint:
    """The defect class that cost v0.8.0 its SBOM, asserted rather than assumed."""

    def test_the_sbom_glob_does_not_swallow_the_bundle(self, tmp_path: Path) -> None:
        (tmp_path / "reveille-0.9.0-sbom.cdx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "reveille-0.9.0-sbom.cdx.json.sigstore.json").write_text("{}", encoding="utf-8")
        result = _run(
            'for a in reveille-*-sbom.cdx.json; do echo "SBOM:$a"; done\n'
            'for b in reveille-*-sbom.cdx.json.sigstore.json; do echo "BUNDLE:$b"; done\n',
            tmp_path,
            {},
        )
        assert result.stdout.count("SBOM:") == 1, result.stdout
        assert result.stdout.count("BUNDLE:") == 1, result.stdout
        assert "SBOM:reveille-0.9.0-sbom.cdx.json.sigstore.json" not in result.stdout

    def test_an_unmatched_glob_stays_literal(self, tmp_path: Path) -> None:
        """Which is why the workflow tests each asset for size rather than trusting it."""
        result = _run('for a in reveille-*-sbom.cdx.json; do echo "$a"; done', tmp_path, {})
        assert result.stdout.strip() == "reveille-*-sbom.cdx.json"


@pytest.mark.unit
class TestBothReleaseAssetsMustExist:
    """`gh` is stubbed. Nothing here reaches the network."""

    @staticmethod
    def _stub_gh(tmp_path: Path, view_rc: int, upload_rc: int) -> dict[str, str]:
        binaries = tmp_path / "bin"
        binaries.mkdir(exist_ok=True)
        gh = binaries / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
            f'case "$2" in\n  view) exit {view_rc} ;;\n  upload) exit {upload_rc} ;;\n'
            "  *) exit 0 ;;\nesac\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        return {
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "GH_CALLS": str(tmp_path / "gh-calls.txt"),
        }

    @classmethod
    def _release(
        cls, tmp_path: Path, *, assets: list[str], view_rc: int = 1, upload_rc: int = 0
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        (tmp_path / "release-title.txt").write_text("0.9.0 — A Theme", encoding="utf-8")
        (tmp_path / "release-body.md").write_text("notes", encoding="utf-8")
        for name in assets:
            (tmp_path / name).write_text("{}", encoding="utf-8")
        env = cls._stub_gh(tmp_path, view_rc, upload_rc)
        env.update({"TAG": "v0.9.0", "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "x"})
        result = _run(
            _step_script("Create the draft Release, or attach to one that exists"), tmp_path, env
        )
        calls = Path(env["GH_CALLS"])
        return result, calls.read_text(encoding="utf-8") if calls.exists() else ""

    _BOTH: ClassVar[list[str]] = [
        "reveille-0.9.0-sbom.cdx.json",
        "reveille-0.9.0-sbom.cdx.json.sigstore.json",
    ]

    def test_a_missing_bundle_stops_the_release(self, tmp_path: Path) -> None:
        """The attestation is the security-relevant asset. Shipping without it silently is the defect."""
        result, calls = self._release(tmp_path, assets=self._BOTH[:1])
        assert result.returncode != 0
        assert "expected release asset is missing" in result.stdout
        assert "sigstore.json" in result.stdout
        assert calls == "", "gh was called despite a missing asset"

    def test_a_missing_sbom_stops_the_release(self, tmp_path: Path) -> None:
        result, calls = self._release(tmp_path, assets=self._BOTH[1:])
        assert result.returncode != 0
        assert "expected release asset is missing" in result.stdout
        assert calls == ""

    def test_an_empty_asset_stops_the_release(self, tmp_path: Path) -> None:
        """`-s`, not `-f`: a zero-byte SBOM is a failure that looks like success."""
        (tmp_path / "reveille-0.9.0-sbom.cdx.json.sigstore.json").write_text("", encoding="utf-8")
        result, _ = self._release(tmp_path, assets=self._BOTH[:1])
        assert result.returncode != 0
        assert "expected release asset is missing" in result.stdout

    def test_both_assets_present_creates_a_draft_when_no_release_exists(
        self, tmp_path: Path
    ) -> None:
        result, calls = self._release(tmp_path, assets=self._BOTH, view_rc=1)
        assert result.returncode == 0, result.stderr
        assert "release create v0.9.0" in calls
        assert "--draft" in calls
        for asset in self._BOTH:
            assert asset in calls, f"{asset} was not attached"

    def test_an_existing_release_is_uploaded_to_rather_than_recreated(self, tmp_path: Path) -> None:
        result, calls = self._release(tmp_path, assets=self._BOTH, view_rc=0)
        assert result.returncode == 0, result.stderr
        assert "release upload v0.9.0" in calls
        assert "--clobber" in calls
        assert "release create" not in calls

    def test_an_immutable_release_warns_rather_than_failing(self, tmp_path: Path) -> None:
        """Documented behaviour: the attestation has already succeeded by then.

        A published release accepts no new assets once immutability is on.
        Failing the job there would report a security-relevant step as broken
        when it is not.
        """
        result, _ = self._release(tmp_path, assets=self._BOTH, view_rc=0, upload_rc=1)
        assert result.returncode == 0
        assert "::warning::could not attach the SBOM" in result.stdout
        assert "make sbom" in result.stdout
