# Tasks: Homebrew Global Installation & VM-Ready Deployment

**PRD**: `cOS_prds/20260330_182656_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Relevant Files

- `Formula/colonyos.rb` - Existing in-repo formula (development reference)
- `.github/workflows/release.yml` - Release pipeline, needs new `update-homebrew` job
- `src/colonyos/doctor.py` - Health check, needs install-method detection
- `tests/test_doctor.py` - Tests for doctor module
- `src/colonyos/init.py` - Init flow, needs non-git-repo guard
- `tests/test_init.py` - Tests for init module (if exists, else `tests/test_cli.py`)
- `install.sh` - Curl installer (reference, no changes needed)
- `deploy/README.md` - VM deployment guide, needs update
- `deploy/colonyos-daemon.service` - Existing systemd unit (reference)
- `deploy/provision.sh` - NEW: VM provisioning script
- `README.md` - Needs Homebrew install instructions
- `pyproject.toml` - Package metadata (reference)
- `scripts/generate-homebrew-formula.sh` - NEW: Formula generation script for release workflow

## Tasks

- [x] 1.0 Create Homebrew tap repository and formula generation script
  depends_on: []
  - [x] 1.1 Create `rangelak/homebrew-colonyos` GitHub repo with README (manual/gh CLI — document the steps)
  - [x] 1.2 Write `scripts/generate-homebrew-formula.sh` that:
    - Takes a version and sdist SHA-256 as arguments
    - Installs the package in a temp venv
    - Runs `homebrew-pypi-poet colonyos` to generate all resource blocks
    - Outputs a complete `Formula/colonyos.rb` with correct URL, SHA-256, resources, caveats, and test block
  - [x] 1.3 Test the generation script locally: run it, verify the output formula has resource blocks for all transitive deps (click, pyyaml, rich, claude-agent-sdk, etc.)
  - [x] 1.4 Update in-repo `Formula/colonyos.rb` with a comment redirecting to the tap repo as the canonical source

- [x] 2.0 Add `update-homebrew` job to release workflow
  depends_on: [1.0]
  - [x] 2.1 Write tests/validation: add a CI check that `scripts/generate-homebrew-formula.sh --dry-run` succeeds (formula generation without push)
  - [x] 2.2 Add `update-homebrew` job to `.github/workflows/release.yml`:
    - Runs after `publish` job succeeds
    - Sets up Python, installs `homebrew-pypi-poet`
    - Runs `scripts/generate-homebrew-formula.sh` with the tagged version and SHA-256 from build artifacts
    - Clones `rangelak/homebrew-colonyos`, copies generated formula, commits and pushes
    - Uses `HOMEBREW_TAP_TOKEN` secret (fine-grained PAT scoped to tap repo)
  - [x] 2.3 Document the one-time setup steps: creating the PAT, adding it as a repo secret, creating the tap repo
  - [x] 2.4 Add the Homebrew install command to the GitHub Release notes template in the `release` job

- [x] 3.0 Add install-method detection to `colonyos doctor`
  depends_on: []
  - [x] 3.1 Write tests for install-method detection: mock Homebrew Cellar path, pipx metadata, pip scenarios; verify correct upgrade instructions are returned
  - [x] 3.2 Implement install-method detection in `src/colonyos/doctor.py`:
    - Check if `colonyos` binary is under Homebrew Cellar → "Installed via Homebrew"
    - Check if installed in a pipx venv → "Installed via pipx"
    - Fallback → "Installed via pip"
  - [x] 3.3 Update doctor output to show install-specific upgrade instructions:
    - Homebrew: `brew upgrade colonyos`
    - pipx: `pipx upgrade colonyos`
    - pip: `pip install --upgrade colonyos`

- [x] 4.0 Add non-git-repo guard to `colonyos init`
  depends_on: []
  - [x] 4.1 Write tests: verify init warns when cwd is not a git repo, verify init proceeds normally in a git repo
  - [x] 4.2 Add guard to `src/colonyos/init.py`: when cwd has no `.git` directory (walking up), print a warning like "Warning: Not inside a git repository. ColonyOS works per-project — please cd into a git repo." and prompt for confirmation before proceeding

- [x] 5.0 Create VM provisioning script
  depends_on: []
  - [x] 5.1 Write `deploy/provision.sh` that:
    - Detects Ubuntu version (22.04+ required)
    - Installs Python 3.11+, Node.js LTS, Git, GitHub CLI via apt/nodesource
    - Installs pipx, then `pipx install colonyos` (with optional `[slack]` extra)
    - Creates `colonyos` system user and `/opt/colonyos/repo` directory
    - Copies `colonyos-daemon.service` to `/etc/systemd/system/`
    - Prompts for `ANTHROPIC_API_KEY` and `GITHUB_TOKEN`, writes to `/opt/colonyos/env` with `chmod 600`
    - Enables and starts the systemd service
    - Runs `colonyos doctor` as verification
  - [x] 5.2 Add `--dry-run` flag to `deploy/provision.sh` for testing without side effects
  - [x] 5.3 Update `deploy/README.md` to reference `provision.sh` as the primary setup method
  - [x] 5.4 Add shellcheck linting for `deploy/provision.sh` to CI workflow (`.github/workflows/ci.yml`)

- [ ] 6.0 Update README and documentation
  depends_on: [1.0, 3.0]
  - [ ] 6.1 Add Homebrew as first install option in README (macOS section):
    ```
    brew install rangelak/colonyos/colonyos
    ```
  - [ ] 6.2 Keep curl installer as cross-platform option
  - [ ] 6.3 Add VM deployment quickstart section pointing to `deploy/provision.sh`
  - [ ] 6.4 Remove stale references to `colonyos/tap` (update to `rangelak/colonyos`)

- [ ] 7.0 End-to-end validation
  depends_on: [2.0, 3.0, 4.0, 5.0, 6.0]
  - [ ] 7.1 Verify `scripts/generate-homebrew-formula.sh` produces a valid formula with all resource blocks
  - [ ] 7.2 Verify `brew install --build-from-source Formula/colonyos.rb` succeeds locally (or in CI)
  - [ ] 7.3 Verify `colonyos doctor` shows correct install method and upgrade instructions for each install type
  - [ ] 7.4 Verify `colonyos init` warns when run outside a git repo
  - [ ] 7.5 Verify `deploy/provision.sh --dry-run` completes without errors on Ubuntu
  - [ ] 7.6 Verify release workflow dry-run: simulate a tag push and confirm the `update-homebrew` job logic is correct
