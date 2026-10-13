# Releasing Reveille

Everything up to the tag is reversible. Pushing a tag is not, and neither is a PyPI upload: a
filename can never be reused, even after deletion.

Prerequisites: Poetry 2.2 or newer (see [CONTRIBUTING.md](CONTRIBUTING.md)), a clean working tree,
and push access.

---

## 1. Prepare, on a branch

```bash
git switch -c chore/release-vX.Y.Z
```

- Bump the version in both places: `pyproject.toml` (`version = "X.Y.Z"`) and
  `src/reveille/__init__.py` (`__version__ = "X.Y.Z"`). `make check-version` fails on a mismatch.
- Update `SECURITY.md`: only the current stable release is supported, so the table becomes
  `X.Y.x Yes` / `< X.Y.0 No`.
- Promote the CHANGELOG. Rename `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD — Theme`, add a
  fresh empty `[Unreleased]`, and add the two link definitions at the foot of the file:

  ```
  [Unreleased]: https://github.com/varaprasadchilakanti/reveille/compare/vX.Y.Z...HEAD
  [X.Y.Z]: https://github.com/varaprasadchilakanti/reveille/releases/tag/vX.Y.Z
  ```

  Sections follow Keep a Changelog order: Added, Changed, Deprecated, Removed, Fixed, Security.
  The theme is a short noun phrase naming what the release is about, and step 5 reuses it verbatim
  as the GitHub Release title, so the two cannot disagree. The date is the day the tag is pushed.

## 2. Verify locally

```bash
make ci
```

This runs `check-lock`, `check-lock-sync`, `check-version`, `check-licence`, `check-packaging`,
`lint`, `typecheck` and `test`. All must pass before the tag exists, because the tag triggers
publication. Also exercise what a user gets:

```bash
poetry build
python3 -m venv /tmp/rel-check
/tmp/rel-check/bin/pip install dist/*.whl
/tmp/rel-check/bin/reveille --version
/tmp/rel-check/bin/reveille generate --repo . -o /tmp/rel-check.html
rm -rf dist /tmp/rel-check
```

## 3. Merge

Open the pull request and merge it. **CI must be green on `main` before you tag**: a tag on a
broken commit publishes a broken release.

## 4. Tag and publish

Tag the merge commit on `main`, not the branch.

```bash
git switch main && git pull
git tag -s vX.Y.Z -m "Release X.Y.Z — <the theme from the CHANGELOG heading>"
git push origin vX.Y.Z
```

On signing: `-s` uses whatever `gpg.format` names. SSH needs the least setup:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/<your-key>.pub
git config --global tag.gpgsign true
```

Then add that same public key a second time on GitHub (Settings, SSH and GPG keys) with Key type:
Signing Key. GitHub keeps authentication and signing keys in separate registers. Two failures to
know before they cost a version number:

- `gpg: skipped ... No secret key` means `gpg.format` is still `openpgp` and no GPG key exists. Set
  the format, or use `-a` for an annotated unsigned tag.
- A signature verifies only when the tagger email is a verified email on the account. A global
  fallback address produces an Unverified tag that cannot be fixed afterwards.

With release immutability enabled (Settings, General), a published tag is final: an unsigned
tag stays unsigned and a tag on the wrong commit stays there. Check both before pushing.

The tag push triggers `.github/workflows/publish.yml`, which:

1. scans `poetry.lock` for known vulnerabilities and stops the release if any are found, the
   last gate before PyPI;
2. builds and uploads to PyPI via Trusted Publisher over OIDC, with PEP 740 attestations and no
   stored credentials;
3. generates and attests a CycloneDX SBOM and uploads it as a workflow artifact.

If the SBOM job fails, publication has already happened. Re-running the job from the tag runs
the workflow file as it was at that tag and fails the same way. Fix the workflow on `main`, then
use the manual trigger (Actions, Publish, Run workflow, enter the tag). Only the SBOM jobs run that
way, because a version number is spent on first upload.

If the run fails before the upload, delete the tag (`git push --delete origin vX.Y.Z && git tag -d
vX.Y.Z`), fix, and re-tag. This works only while no Release is published for that tag; with
immutability enabled, publishing a Release freezes it and the recovery is X.Y.Z+1.

## 5. Publish the GitHub Release

The workflow has already drafted it, with the SBOM attached, the title from the CHANGELOG heading
and the body from that version's section. Read it and press Publish. It is a draft because a
published release accepts no assets under immutability. If a Release for the tag already exists,
the job attaches the SBOM to it; if that is published and immutable, the job says so and does not
fail, and the SBOM stays downloadable as the run's `sbom` artifact. The notes are also available
outside the workflow:

```bash
python3 .github/scripts/release_notes.py vX.Y.Z --title
python3 .github/scripts/release_notes.py vX.Y.Z --body
```

## 6. Verify from the published artefact

The published file is what users get, not the source tree:

```bash
curl -s https://pypi.org/pypi/reveille/X.Y.Z/json | python3 -c "
import json,sys; i=json.load(sys.stdin)['info']
print('version   :', i['version'])
print('license   :', i['license'])
print('yanked    :', i['yanked'])"

pipx upgrade reveille || pipx install reveille
reveille --version
reveille capabilities --format json | head -5
```

Also confirm the previous version still shows its own metadata: releases are per-version.

## 7. If a release is wrong

Metadata cannot be edited after upload, and a filename can never be reused.

- Yank it (PyPI, Manage, Releases, Options, Yank, with a reason). The file stays downloadable
  for anyone who pinned it exactly, while new resolutions steer away. This keeps the record.
- Fix, and publish X.Y.Z+1.
- Do not delete. It frees nothing and removes the audit trail.

---

## Environment notes

Keyring on a fresh Linux machine: Poetry may hang trying to reach a system keyring that is not
running: `poetry config keyring.enabled false`.

Publishing is done by CI. `make publish` exists, but the PyPI Trusted Publisher trusts only the
tagged workflow; publishing by hand would need credentials that deliberately do not exist.

## Repository settings this depends on

These live on GitHub, not in the repository:

- A `main` ruleset requiring these checks, blocking force pushes and restricting deletions. A
  job that is configured but not *required* is advisory: the merge button stays green anyway.

  | Workflow | Check |
  |---|---|
  | `ci.yml` | Lock file integrity |
  | `ci.yml` | Workflow correctness (actionlint) |
  | `ci.yml` | Lint (ruff) |
  | `ci.yml` | Type Check (mypy) |
  | `ci.yml` | Test (pytest) |
  | `ci.yml` | Known vulnerabilities (osv-scanner) |
  | `ci.yml` | Reproducible build |
  | `cla.yml` | contributor agreement |
  | `zizmor.yml` | Analyse workflows (zizmor) |
- A PyPI Trusted Publisher pointing at `publish.yml` with environment `pypi`.
- A `pypi` environment in repository settings.
