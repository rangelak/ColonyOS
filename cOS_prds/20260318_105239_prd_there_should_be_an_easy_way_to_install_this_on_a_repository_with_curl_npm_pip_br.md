# PRD: Package Publishing & Release Automation

## Introduction/Overview

ColonyOS is currently published on PyPI as `colonyos` v0.1.0, installable via `pip install colonyos`. However, there is no CI/CD pipeline, no automated release workflow, no alternative installation channels (curl, Homebrew), and the version is hardcoded in two places (`pyproject.toml` line 7 and `src/colonyos/__init__.py` line 3). This feature request adds:

1. **A GitHub Actions CI pipeline** that runs the full test suite on every push/PR
2. **An automated release workflow** triggered by git tags that publishes to PyPI
3. **Single-source versioning** derived from git tags (eliminating version duplication)
4. **A curl one-liner installer** script for zero-friction installation
5. **A Homebrew tap** for macOS/Linux users who prefer managed package updates

## Goals

1. **Zero-friction installation**: Any developer can install ColonyOS with a single command — `pip install colonyos`, `curl ... | sh`, or `brew install colonyos/tap/colonyos`
2. **Automated, gated releases**: Pushing a git tag like `v0.2.0` triggers CI → tests → build → publish to PyPI, with no manual steps
3. **Single source of truth for versioning**: The git tag determines the version everywhere — `pyproject.toml`, `__init__.py`, PyPI, and GitHub Releases
4. **Confidence in releases**: Every published version has passed the full 633-test suite
5. **Release transparency**: Every GitHub Release includes auto-generated notes from `CHANGELOG.md`

## User Stories

1. **As a new user**, I want to run `curl -sSL https://install.colonyos.dev | sh` and have ColonyOS installed and ready to use, so I can try it without reading installation docs.
2. **As a macOS developer**, I want to run `brew install colonyos/tap/colonyos` so that ColonyOS is managed alongside my other CLI tools.
3. **As a maintainer**, I want to push a `v0.2.0` tag and have the package automatically tested, built, published to PyPI, and a GitHub Release created with notes, so I never manually run `twine upload`.
4. **As a contributor**, I want CI to run tests on my pull requests so I get fast feedback before merge.
5. **As a user upgrading**, I want to see clear release notes on GitHub so I know what changed.

## Functional Requirements

### FR-1: GitHub Actions CI Pipeline
1. Run `pytest` on every push to `main` and on every pull request
2. Test on Python 3.11 and 3.12
3. Install all dependencies including dev extras
4. Report test results as PR check status

### FR-2: Automated Release Workflow
1. Trigger on git tag push matching `v*` pattern
2. Gate on full test suite passing (same matrix as CI)
3. Build sdist and wheel using `python -m build`
4. Publish to PyPI using PyPI Trusted Publishers (OIDC, no API tokens stored)
5. Create a GitHub Release with the tag, attaching release notes and SHA-256 checksums
6. Upload sdist, wheel, and checksums as release assets

### FR-3: Single-Source Versioning
1. Adopt `setuptools-scm` to derive version from git tags
2. Remove hardcoded `version = "0.1.0"` from `pyproject.toml` (make it dynamic)
3. Remove hardcoded `__version__ = "0.1.0"` from `src/colonyos/__init__.py`
4. Generate `__version__` at build time via `setuptools-scm`
5. Ensure `colonyos --version` (if it exists) or `importlib.metadata.version("colonyos")` returns the correct version

### FR-4: Curl Installer Script
1. Create an `install.sh` script hosted in the repository
2. Script detects OS and checks for Python 3.11+
3. Installs `pipx` if not present (with user confirmation)
4. Runs `pipx install colonyos` (or `pip install --user colonyos` as fallback)
5. Prints post-install verification: `colonyos doctor`
6. Publishes SHA-256 checksum alongside the script

### FR-5: Homebrew Tap
1. Create a `homebrew-colonyos` tap repository (or a `Formula/` directory in this repo)
2. Formula declares `depends_on "python@3.11"`
3. Formula installs ColonyOS into a Homebrew-managed virtualenv via pip
4. Auto-update the formula on each release (via the release workflow)

### FR-6: Release Notes Generation
1. Extract the latest section from `CHANGELOG.md` for the GitHub Release body
2. Fall back to GitHub auto-generated notes if `CHANGELOG.md` section is not found
3. Include installation instructions in each release

## Non-Goals

- **npm wrapper package**: All personas unanimously agreed this adds maintenance burden for near-zero discoverability. ColonyOS is a Python tool; an npm shim is misleading.
- **Platform-specific binaries (PyInstaller/Nuitka)**: The dependency on `claude-agent-sdk` and Claude Code CLI means users already need a Python/Node dev environment. Binaries add a massive build matrix for no real benefit at v0.1.
- **GPG/Sigstore release signing**: Premature for a pre-1.0 project. SHA-256 checksums are sufficient for now. Revisit at v1.0.
- **Automated releases on every merge to main**: Too aggressive; would publish broken intermediate states.
- **homebrew-core formula**: Requires significant adoption and upstream review. A self-hosted tap is the right approach.

## Technical Considerations

### Existing Architecture
- **Build system**: `setuptools>=68.0` + `wheel` (defined in `pyproject.toml`)
- **Entry point**: `colonyos = "colonyos.cli:app"` (Click CLI)
- **Dependencies**: `click>=8.1`, `pyyaml>=6.0`, `claude-agent-sdk>=0.1.49`, `rich>=13.0`
- **Optional deps**: `slack-bolt[socket-mode]>=1.18` (slack extra), `pre-commit>=4.0`, `pytest>=8.0` (dev extra)
- **Test suite**: 633 tests across 16 files in `tests/`, configured via `[tool.pytest.ini_options]`
- **Pre-commit hook**: Currently hardcodes `.venv/bin/pytest` path which won't work in CI

### Version Duplication Problem
The version `"0.1.0"` appears in two places:
- `pyproject.toml` line 7: `version = "0.1.0"`
- `src/colonyos/__init__.py` line 3: `__version__ = "0.1.0"`

These will inevitably drift. `setuptools-scm` solves this by deriving the version from git tags.

### PyPI Trusted Publishers
GitHub Actions supports OIDC-based publishing to PyPI without storing API tokens. This is the recommended approach: configure the GitHub repo as a "Trusted Publisher" on PyPI, and the workflow uses `pypa/gh-action-pypi-publish` with no secrets needed.

### Files to Modify
- `pyproject.toml` — Add `setuptools-scm`, make version dynamic
- `src/colonyos/__init__.py` — Replace hardcoded version with `importlib.metadata`
- `.github/workflows/ci.yml` — New: CI pipeline
- `.github/workflows/release.yml` — New: Release workflow
- `install.sh` — New: Curl installer script
- `Formula/colonyos.rb` or separate tap repo — New: Homebrew formula

### Persona Consensus & Tensions

**Universal agreement (all 7 personas)**:
- CI with test gating is the #1 priority — higher than any distribution channel
- Git tag-triggered releases, not automated-on-merge
- `setuptools-scm` for single-source versioning
- Skip npm wrapper entirely
- Skip platform binaries for now
- Curl installer should wrap `pipx`, not be a self-contained binary

**Tension areas**:
- **Security engineer** wants Sigstore signing from day one; all others say defer to v1.0. **Resolution**: Ship SHA-256 checksums now, add Sigstore signing as a follow-up.
- **Security engineer** is wary of curl-pipe-sh as an attack vector; others see it as table stakes. **Resolution**: Ship it with checksums and clear documentation, but make pip/pipx the recommended path.
- **Release notes**: Some prefer extracting from `CHANGELOG.md`, others prefer GitHub auto-generated notes. **Resolution**: Extract from `CHANGELOG.md` (it's well-maintained) with GitHub auto-notes as fallback.

## Success Metrics

1. **CI coverage**: 100% of PRs and pushes to main trigger automated test runs
2. **Release automation**: Time from git tag push to PyPI availability < 10 minutes
3. **Installation channels**: ColonyOS installable via `pip`, `pipx`, `curl`, and `brew`
4. **Zero manual releases**: No more manual `python -m build && twine upload` workflows
5. **Version consistency**: `pip show colonyos | grep Version` matches the git tag exactly

## Open Questions

1. **PyPI Trusted Publisher setup**: Does the maintainer have admin access to the `colonyos` PyPI project to configure Trusted Publishers? If not, API token-based publishing is the fallback.
2. **Homebrew tap hosting**: Should the Homebrew formula live in this repo (e.g., `Formula/colonyos.rb`) or in a separate `homebrew-colonyos` repository? A separate repo is more conventional.
3. **Curl installer hosting**: Should `install.sh` be served from GitHub raw content, GitHub Pages, or a custom domain like `install.colonyos.dev`?
4. **CHANGELOG.md format**: Current entries use timestamps, not version numbers. Should we add version headers to correlate with git tags?
5. **Python 3.13 support**: Should CI test on Python 3.13 as well, or just 3.11 and 3.12?
