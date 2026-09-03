# Releasing Reveille

The release path is short but it has three steps that cannot be undone, so it is
written down rather than remembered. Everything up to the tag is reversible.
**Pushing a tag is not**, and neither is a PyPI upload: a filename can never be
reused, even after deletion.

Prerequisites: Poetry ≥ 2.2 (see [CONTRIBUTING.md](CONTRIBUTING.md)), a clean
working tree, and push access.

---

## 1. Prepare, on a branch

```bash
git switch -c chore/release-vX.Y.Z
```

**Bump the version in both places.** `make check-version` asserts they agree, so
a mismatch fails the build rather than shipping:

- `pyproject.toml` → `version = "X.Y.Z"`
- `src/reveille/__init__.py` → `__version__ = "X.Y.Z"`

**Update `SECURITY.md`.** The policy is that only the current stable release is
supported, so the table becomes `X.Y.x ✓` / `< X.Y.0 ✗`.

**Promote the CHANGELOG.** Rename `## [Unreleased]` to
`## [X.Y.Z] — YYYY-MM-DD — Theme`, add a fresh empty `[Unreleased]`, and add the
two link definitions at the foot of the file:

```
[Unreleased]: https://github.com/varaprasadchilakanti/reveille/compare/vX.Y.Z...HEAD
[X.Y.Z]: https://github.com/varaprasadchilakanti/reveille/releases/tag/vX.Y.Z
```

Sections follow Keep a Changelog order: Added, Changed, Deprecated, Removed,
Fixed, Security.

**The theme is part of the heading, from 0.8.0 onward.** It is a short noun
phrase naming what the release is about — *"Security Hardening, Apache-2.0, and
a Rebuilt Report"* — and step 5 reuses it verbatim as the GitHub Release title.
Writing it here rather than at tag time is the point: the release title and the
changelog cannot then say different things. The date is the day the tag is
pushed, not the day the section was drafted.

## 2. Verify locally

```bash
make ci
```

That runs, in order: `check-lock`, `check-lock-sync`, `check-version`,
`check-licence`, `check-packaging`, `lint`, `typecheck`, `test`. All of it must
pass before the tag exists, because the tag is what triggers publication.

Worth doing by hand as well, since it exercises what a user actually gets:

```bash
poetry build
python3 -m venv /tmp/rel-check
/tmp/rel-check/bin/pip install dist/*.whl
/tmp/rel-check/bin/reveille --version
/tmp/rel-check/bin/reveille generate --repo . -o /tmp/rel-check.html
rm -rf dist /tmp/rel-check
```

## 3. Merge

Open the pull request and merge it. **CI must be green on `main` before you
tag** — the tag points at a commit, and a tag on a broken commit publishes a
broken release.

## 4. Tag and publish

**Tag the merge commit on `main`, not the branch.** A tag points at one
commit; tagging the branch tip publishes a tree that was never on `main`.

```bash
git switch main && git pull
git tag -s vX.Y.Z -m "Release X.Y.Z — <the theme from the CHANGELOG heading>"
git push origin vX.Y.Z
```

**On signing.** `-s` uses whatever `gpg.format` names. SSH is the least
setup, since the key you already push with can also sign:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519_github.pub
git config --global tag.gpgsign true
```

Then add that **same public key a second time** on GitHub, under Settings
→ SSH and GPG keys → New SSH key, with **Key type: Signing Key**. GitHub
keeps authentication and signing keys in separate registers, so a key
present only as an authentication key verifies nothing. Its own
documentation says so: *"If you already use an SSH key to authenticate
with GitHub, you can also upload that same key again for use as a signing
key."*

Two failure modes worth knowing before they cost you a version number:

- `gpg: skipped ... No secret key` means `gpg.format` is still `openpgp`
  and no GPG key exists. Set the format, or drop to `-a` for an annotated
  unsigned tag, which is what releases before 0.8.0 used.
- A signature verifies only when the **tagger email is a verified email on
  the account**. This repository sets `user.email` locally; a global
  fallback address will produce an Unverified tag that cannot be fixed
  afterwards.

**If release immutability is enabled** (Settings → General → *Disallow
assets and tags from being modified once a release is published*), a
published tag is final. An unsigned tag stays unsigned, and a tag on the
wrong commit stays on the wrong commit. Get both right before pushing.

The tag push triggers `.github/workflows/publish.yml`, which:

1. scans `poetry.lock` for known vulnerabilities and **stops the release** if any
   are found — this is the last gate before PyPI;
2. builds and uploads to PyPI via Trusted Publisher over OIDC, with PEP 740
   attestations. **There are no stored credentials**; nothing to rotate or leak;
3. generates and attests a CycloneDX SBOM, and uploads it as a workflow artifact.

**If the SBOM job fails, publication has already happened.** It runs after the
upload, so a failure there costs the attestation, not the release. Re-running
the job from the tag re-runs the workflow file *as it was at that tag*, which
will fail the same way. Fix the workflow on `main`, then use the manual
trigger: Actions → Publish → Run workflow → enter the tag. Only the SBOM jobs
run that way; publication is guarded off, since a version number is spent on
first upload.

Watch the run. If it fails before the upload step, delete the tag
(`git push --delete origin vX.Y.Z && git tag -d vX.Y.Z`), fix, and re-tag.
This works only while no Release has been published for that tag: with
release immutability enabled, publishing a Release freezes the tag, and
the recovery becomes X.Y.Z+1 rather than a re-tag.
**Once the upload succeeds, that version number is spent** — see step 6.

## 5. Publish the GitHub Release

**The workflow has already drafted it.** After the tag push, the `release`
job creates a **draft** Release with the SBOM attached, the title taken from
the CHANGELOG heading and the body taken from that version's section. Nothing
is retyped, so the Release and the changelog cannot disagree.

All that is left is to read it and press **Publish**.

The draft matters. A draft accepts assets; a published release does not, once
release immutability is enabled. Creating it with the SBOM already attached
removes the step a human previously had to remember, and the only window in
which it could be done.

If a Release already exists for the tag when the job runs — because you
drafted one by hand first — the job attaches the SBOM to it instead. If that
release is already published and immutable, the job says so and does not fail:
the attestation has already succeeded, and the SBOM stays downloadable as the
run's `sbom` artifact.

Should you need the notes outside the workflow:

```bash
python3 .github/scripts/release_notes.py vX.Y.Z --title
python3 .github/scripts/release_notes.py vX.Y.Z --body
```

## 6. Verify from the published artefact

Not from the source tree. The published file is the thing users get:

```bash
curl -s https://pypi.org/pypi/reveille/X.Y.Z/json | python3 -c "
import json,sys; i=json.load(sys.stdin)['info']
print('version   :', i['version'])
print('license   :', i['license'])
print('classifiers:', [c for c in i['classifiers'] if c.startswith('License')])
print('yanked    :', i['yanked'])"

pipx upgrade reveille || pipx install reveille
reveille --version
reveille capabilities --format json | head -5
```

Also confirm the previous version still shows its own metadata — releases are
per-version and a licence change never rewrites history:

```bash
curl -s https://pypi.org/pypi/reveille/<previous>/json | python3 -c "
import json,sys; print(json.load(sys.stdin)['info']['license'])"
```

## 7. If a release is wrong

**Metadata cannot be edited after upload, and a filename can never be reused**,
even after deletion. So:

- **Yank it** (PyPI → Manage → Releases → Options → Yank, with a reason). Yanking
  leaves the file downloadable for anyone who pinned it exactly, while steering
  new resolutions away. That is the transparent option and it keeps the record.
- **Fix, and publish X.Y.Z+1.**
- **Do not delete.** Deletion frees nothing, removes the audit trail, and the
  filename stays permanently reserved regardless.

---

## Environment notes

**Keyring on a fresh Linux machine.** Poetry may hang or fail trying to reach a
system keyring that is not running. This repository's config already disables it;
if you publish from a new machine:

```bash
poetry config keyring.enabled false
```

**Publishing is done by CI, not by you.** `make publish` exists but the release
path is the tagged workflow, which is what the Trusted Publisher on PyPI is
configured to trust. Publishing by hand would need credentials that deliberately
do not exist.

## Repository settings this depends on

These live on GitHub, not in the repository, and are easy to lose:

- A **`main` ruleset** requiring the CI status checks, blocking force pushes and
  restricting deletions. Without it a red build can merge — which is how an
  unreadable `poetry.lock` once reached `main` and stayed for seven merges.

  The checks to require, by the name GitHub shows them under:

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

  A job that is configured but not *required* is advisory: it reports, and the
  merge button stays green anyway. Requiring them is the whole point.
- A **PyPI Trusted Publisher** pointing at `publish.yml` with environment `pypi`.
- A **`pypi` environment** in repository settings.
