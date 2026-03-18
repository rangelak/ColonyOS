# Review by Staff Security Engineer (Round 1)

Here is my review from the **Staff Security Engineer** perspective:

---

## Security Review: Package Publishing & Release Automation

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-6)
- [x] All tasks in the task file are marked complete
- [~] Homebrew formula contains `PLACEHOLDER_SHA256` — not shippable as-is

### Quality
- [x] Tests added for workflows, versioning, and install script
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added (setuptools-scm is appropriate)
- [~] Shell test file (`test_install_script.sh`) is outside pytest, not integrated into CI

### Safety — **Critical Findings**

#### HIGH: GitHub Actions not pinned to commit SHAs
All workflow actions use mutable tags (`@v4`, `@v5`, `@release/v1`). A compromised upstream action tag can inject arbitrary code into the build and publish pipeline. This is an active, exploited supply chain vector (cf. the `tj-actions/changed-files` incident, March 2025). The `pypa/gh-action-pypi-publish@release/v1` action has **write access to PyPI** — a tag swap here means arbitrary package publication.

#### HIGH: `install.sh` interactive prompt silently auto-accepts when piped via `curl | sh`
The `read -r REPLY` on line 106 reads from stdin. When invoked as `curl ... | sh`, stdin is the pipe — not the terminal. `read` will get EOF/empty string, which falls through to the `*)` wildcard case, meaning **pipx is installed without user consent**. The PRD explicitly requires "with user confirmation." This is deceptive by default in the advertised usage pattern. The script should detect non-interactive stdin (`[ -t 0 ]`) and either abort or skip the auto-install.

#### MEDIUM: `install.sh` installs pipx via `pip install --user pipx` without `--require-hashes`
Line 114 runs `pip install --user pipx` with no integrity verification. In the context of a curl-pipe-sh installer, this is a second trust-on-first-use hop with no pinning.

#### MEDIUM: Homebrew formula has `PLACEHOLDER_SHA256`
`Formula/colonyos.rb` line 11 contains `sha256 "PLACEHOLDER_SHA256"`. This is a TODO in shipped code. Homebrew will reject this formula, and more importantly, it means integrity verification is completely absent. The release workflow also does not update this value (FR-5.4 claims auto-update but no step exists).

#### LOW: No workflow-level `permissions` block restricts default token scope
The CI workflow (`ci.yml`) has no top-level `permissions` key, which means jobs inherit the repo's default token permissions. Best practice is to set `permissions: {}` at the top level and grant per-job. The release workflow does this per-job for `publish` and `release`, which is good, but the `test` and `build` jobs inherit defaults unnecessarily.

#### LOW: Release notes extraction is injection-safe but fragile
The `awk` extraction from `CHANGELOG.md` (release.yml line 165) writes to a file, avoiding shell injection. However, the `NOTES` variable is constructed via string concatenation with backtick-escaped markdown, which could break in edge cases.

#### INFO: No audit trail of what the installer did
The install script has no `--log` option or transcript mechanism. When something goes wrong, users have no artifact to share. Not a blocker, but a gap for a tool that modifies the user's Python environment.

---

VERDICT: request-changes

FINDINGS:
- [.github/workflows/ci.yml]: Actions pinned to mutable tags (@v4, @v5) instead of commit SHAs — supply chain risk
- [.github/workflows/release.yml]: Actions pinned to mutable tags; `pypa/gh-action-pypi-publish@release/v1` has PyPI write access via a mutable ref
- [.github/workflows/release.yml]: No top-level `permissions: {}` — test and build jobs inherit overly broad default token scope
- [.github/workflows/release.yml]: No step to auto-update Homebrew formula SHA256 on release (FR-5.4 incomplete)
- [install.sh]: `read -r REPLY` silently auto-accepts pipx installation when script is piped via `curl | sh` (stdin is not a TTY) — violates "with user confirmation" requirement
- [install.sh]: `pip install --user pipx` has no hash pinning or version constraint
- [Formula/colonyos.rb]: Contains `PLACEHOLDER_SHA256` — TODO/placeholder code in shipped artifact
- [.github/workflows/ci.yml]: Missing top-level `permissions: {}` to enforce least privilege

SYNTHESIS:
The implementation covers the PRD's functional surface area well — CI, release automation, setuptools-scm versioning, curl installer, and Homebrew formula are all present. However, from a supply chain security perspective, there are two high-severity issues that must be addressed before merge. First, all GitHub Actions references use mutable tags rather than pinned commit SHAs; this is the single most impactful supply chain hardening step for any CI/CD pipeline, and it's especially critical for the PyPI publish action which has credential-equivalent access. Second, the curl-pipe-sh installer's interactive pipx prompt silently auto-accepts due to stdin not being a TTY — this turns an explicit user consent step into an implicit one, which is both a UX and security concern. The Homebrew formula placeholder SHA256 is a completeness gap that also has integrity implications. I'd recommend fixing the two HIGH items and the placeholder before merging; the MEDIUM and LOW items can be tracked as fast-follows.