# Tasks: Package Publishing & Release Automation

## Relevant Files

- `pyproject.toml` - Package metadata, version, build system config — needs setuptools-scm integration
- `src/colonyos/__init__.py` - Hardcoded `__version__` to be replaced with dynamic version
- `.pre-commit-config.yaml` - Existing pre-commit hook (hardcodes `.venv/bin/pytest` path)
- `src/colonyos/cli.py` - CLI entry point, may reference `__version__`
- `src/colonyos/doctor.py` - Prerequisite checks — may need to expose version info
- `CHANGELOG.md` - Release notes source for GitHub Releases
- `tests/` - Full test suite (633 tests across 16 files)
- `.github/workflows/ci.yml` - New: CI pipeline workflow
- `.github/workflows/release.yml` - New: Release/publish workflow
- `install.sh` - New: Curl installer script
- `tests/test_install_script.sh` - New: Installer script tests
- `tests/test_version.py` - New: Version consistency tests

## Tasks

- [x] 1.0 Set Up GitHub Actions CI Pipeline
  - [x] 1.1 Write tests to verify CI workflow YAML is valid and contains required jobs (test matrix, pytest step)
  - [x] 1.2 Create `.github/workflows/ci.yml` with pytest job on push to `main` and on pull requests
  - [x] 1.3 Configure test matrix for Python 3.11 and 3.12
  - [x] 1.4 Install dependencies (`pip install -e ".[dev]"`) and run `pytest` in the workflow
  - [x] 1.5 Verify CI runs successfully by pushing to a test branch

- [x] 2.0 Implement Single-Source Versioning with setuptools-scm
  - [x] 2.1 Write `tests/test_version.py` to verify `colonyos.__version__` matches `importlib.metadata.version("colonyos")` and is a valid semver string
  - [x] 2.2 Add `setuptools-scm>=8.0` to `[build-system] requires` in `pyproject.toml`
  - [x] 2.3 Change `pyproject.toml` to use `dynamic = ["version"]` and add `[tool.setuptools_scm]` config
  - [x] 2.4 Replace `__version__ = "0.1.0"` in `src/colonyos/__init__.py` with dynamic version via `importlib.metadata.version("colonyos")` with a fallback for editable installs
  - [x] 2.5 Update any other references to `__version__` in the codebase (grep for `__version__`)
  - [x] 2.6 Tag the current commit as `v0.1.0` if not already tagged, to establish the version baseline
  - [x] 2.7 Verify `pip install -e .` and `python -c "import colonyos; print(colonyos.__version__)"` both produce the correct version

- [x] 3.0 Create Automated Release Workflow
  - [x] 3.1 Write tests to verify release workflow YAML structure (tag trigger, test gate, publish step, release creation)
  - [x] 3.2 Create `.github/workflows/release.yml` triggered on `v*` tag push
  - [x] 3.3 Add test job that runs `pytest` as a gate before publishing
  - [x] 3.4 Add build job that creates sdist and wheel using `python -m build`
  - [x] 3.5 Add publish job using `pypa/gh-action-pypi-publish` with Trusted Publisher (OIDC) — include `permissions: id-token: write`
  - [x] 3.6 Add SHA-256 checksum generation step (`sha256sum dist/*`)
  - [x] 3.7 Add GitHub Release creation step using `gh release create` with changelog extraction and checksum upload
  - [x] 3.8 Document Trusted Publisher setup steps for PyPI in a comment in the workflow file

- [x] 4.0 Build Changelog-Based Release Notes Extraction
  - [x] 4.1 Write tests for the changelog extraction logic (parsing latest section, handling missing sections, fallback behavior)
  - [x] 4.2 Create a shell script or inline workflow step that extracts the latest section from `CHANGELOG.md` between the two most recent `## ` headers
  - [x] 4.3 Integrate extraction into the release workflow's GitHub Release creation step
  - [x] 4.4 Add fallback to `--generate-notes` flag if CHANGELOG extraction yields empty content

- [x] 5.0 Create Curl Installer Script
  - [x] 5.1 Write `tests/test_install_script.sh` — a shellcheck lint pass and dry-run mode test for `install.sh`
  - [x] 5.2 Create `install.sh` at repo root with: OS detection, Python 3.11+ check, pipx detection/installation, `pipx install colonyos`, and post-install `colonyos doctor` hint
  - [x] 5.3 Add a `--dry-run` flag to `install.sh` for testing without side effects
  - [x] 5.4 Add SHA-256 checksum verification instructions to the script header comment
  - [x] 5.5 Update `README.md` installation section to include the curl one-liner alongside pip/pipx instructions
  - [x] 5.6 Add shellcheck to CI workflow for linting `install.sh`

- [x] 6.0 Create Homebrew Tap
  - [x] 6.1 Write tests for the Homebrew formula (formula audit, install test via `brew test`)
  - [x] 6.2 Create Homebrew formula file (`Formula/colonyos.rb`) that installs via pip into a virtualenv, declares `depends_on "python@3.11"`
  - [x] 6.3 Add a step to the release workflow that updates the formula with the new version and SHA-256 hash
  - [x] 6.4 Document Homebrew tap setup in README (e.g., `brew tap colonyos/tap && brew install colonyos`)
  - [x] 6.5 Decide on tap hosting: formula in this repo vs. separate `homebrew-colonyos` repo

- [x] 7.0 Update Documentation and README
  - [x] 7.1 Update README.md "Installation" section with all channels: pip, pipx, curl, brew
  - [x] 7.2 Add a "Releasing" section to README or a `CONTRIBUTING.md` explaining the tag-based release process
  - [x] 7.3 Add badges to README: CI status, PyPI version, Python versions supported
  - [x] 7.4 Update `colonyos doctor` output to show the installed version

- [x] 8.0 End-to-End Validation
  - [x] 8.1 Run full test suite locally and confirm all 633+ tests pass
  - [x] 8.2 Create a test tag (e.g., `v0.1.1-rc1`) on a feature branch to dry-run the release workflow
  - [x] 8.3 Verify PyPI Trusted Publisher is configured and a test publish succeeds
  - [x] 8.4 Test curl installer on a clean macOS and Linux environment
  - [x] 8.5 Test Homebrew formula install on macOS
  - [x] 8.6 Verify `colonyos doctor` runs correctly after each installation method
