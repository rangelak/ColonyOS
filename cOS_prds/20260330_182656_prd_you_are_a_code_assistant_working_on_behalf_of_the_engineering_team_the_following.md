# PRD: Homebrew Global Installation & VM-Ready Deployment

**Date**: 2026-03-30
**Status**: Draft
**Prior Work**: Branch `colonyos/add_brew_installation_we_should_be_able_to_have_03f7764b3a` (failed), original install PRD at `cOS_prds/20260318_105239_prd_there_should_be_an_easy_way_to_install_this_on_a_repository_with_curl_npm_pip_br.md` (completed but Homebrew tap never wired up)

---

## 1. Introduction/Overview

ColonyOS should be installable as a proper global CLI tool via Homebrew, similar to `aws`, `gh`, or `terraform`. Users install once, then `cd` into any project and run `colonyos init`. The tool already works this way conceptually (cwd-based project discovery), but the Homebrew distribution channel is broken: the formula at `Formula/colonyos.rb` exists in-repo but has no backing tap repository, no dependency resource blocks, and the release workflow never updates it.

Additionally, the user wants to run ColonyOS on VMs. The `deploy/` directory already has systemd integration, but there's no single provisioning script that automates the full stack.

This PRD fixes the Homebrew distribution channel and adds a VM provisioning script.

## 2. Goals

1. **Working Homebrew install**: `brew install rangelak/colonyos/colonyos` works on a clean macOS machine (Apple Silicon and Intel)
2. **Auto-updating formula**: Every tagged release (`v*`) automatically updates the tap formula with the correct version URL and SHA-256 — zero manual intervention
3. **VM provisioning**: A single `deploy/provision.sh` script installs all dependencies and ColonyOS on a fresh Ubuntu 22.04+ VM
4. **Sub-60-second install**: A developer with Homebrew goes from zero to `colonyos doctor` passing in under 60 seconds

## 3. User Stories

**US-1: macOS Developer First Install**
> As a macOS developer, I run `brew install rangelak/colonyos/colonyos`, then `cd my-project && colonyos init`, and I'm up and running without reading documentation.

**US-2: Automatic Upgrade**
> As an existing user, I run `brew upgrade colonyos` after a new release and get the latest version immediately.

**US-3: VM Deployment**
> As a DevOps engineer, I run `deploy/provision.sh` on a fresh Ubuntu VM, set my API keys, and `colonyos daemon` starts listening for Slack requests.

**US-4: Doctor Diagnosis**
> As a user who just installed via Homebrew, `colonyos doctor` detects my install method and shows correct upgrade instructions (`brew upgrade colonyos` not `pip install --upgrade`).

## 4. Functional Requirements

### FR-1: Homebrew Tap Repository
- Create `rangelak/homebrew-colonyos` GitHub repository
- Contains `Formula/colonyos.rb` with all required Python dependency `resource` blocks
- README with install instructions

### FR-2: Formula with Dependency Resources
- Generate complete `resource` blocks for all transitive Python dependencies using `homebrew-pypi-poet` or equivalent
- Formula declares `depends_on "python@3.11"`
- `test` block runs `colonyos --version` and verifies output
- Add `caveats` block with post-install guidance (run `colonyos doctor`, install Claude Code CLI)

### FR-3: Release Workflow Tap Update
- Add a `update-homebrew` job to `.github/workflows/release.yml`
- After PyPI publish succeeds, compute SHA-256 of the sdist tarball
- Generate updated formula with new version, URL, SHA-256, and refreshed resource blocks
- Push updated formula to `rangelak/homebrew-colonyos` tap repo
- Use a fine-grained PAT scoped only to the tap repo (stored as `HOMEBREW_TAP_TOKEN` secret)

### FR-4: Install Method Detection in Doctor
- `colonyos doctor` detects whether ColonyOS was installed via Homebrew, pipx, or pip
- Upgrade instructions match the install method (e.g., `brew upgrade colonyos`)

### FR-5: VM Provisioning Script
- `deploy/provision.sh` automates full-stack setup on Ubuntu 22.04+
- Installs: Python 3.11+, Node.js (for Claude Code CLI), Git, GitHub CLI, pipx, ColonyOS
- Creates dedicated `colonyos` system user
- Sets up systemd service from `deploy/colonyos-daemon.service`
- Prompts for or reads API keys from environment

### FR-6: README Update
- Add Homebrew as the first install option for macOS
- Keep curl installer as cross-platform option
- Add VM deployment quickstart pointing to `deploy/provision.sh`

### FR-7: Guard Against Non-Repo Init
- `colonyos init` should warn (not hard-fail) when run outside a git repository
- Prevents accidentally creating `.colonyos/` in `$HOME` or `/`

## 5. Non-Goals

- **Linuxbrew**: Homebrew on Linux servers adds massive overhead (GCC toolchain, Python build). Linux users use pipx or the provisioning script.
- **Offline/air-gapped installation**: ColonyOS requires live API access to Anthropic and GitHub at runtime. Offline install is pointless.
- **homebrew-core submission**: Self-hosted tap is the right approach at this stage.
- **Windows support**: Not supported by Claude Code CLI. `install.sh` already rejects it.
- **npm wrapper package**: Unnecessary indirection.
- **Version pinning in Homebrew**: Standard `brew upgrade` semantics are sufficient. Users who need pinning use `pipx install colonyos==X.Y.Z`.
- **Bundling Claude Code CLI**: Separate product with its own auth flow. `colonyos doctor` catches it.

## 6. Technical Considerations

### Persona Consensus Matrix

| Decision | Consensus | Resolution |
|---|---|---|
| Separate tap repo required | **7/7 unanimous** | Create `rangelak/homebrew-colonyos` |
| Formula needs resource blocks | **6/7** (1 says delete formula) | Use `homebrew-pypi-poet` to generate |
| No init changes for brew | **6/7** (1 wants git-repo guard) | Add warning, not hard error |
| Homebrew = macOS only | **6/7** | pipx for Linux VMs |
| Release workflow must auto-update | **7/7 unanimous** | New job in `release.yml` |
| No offline support | **7/7 unanimous** | Skip entirely |
| Doctor detects install method | **5/7** | Add install method detection |
| VM provisioning script | **4/7** | Include as `deploy/provision.sh` |

### Key Tension: Should We Even Do Homebrew?

**Linus Torvalds persona** argued to delete the formula entirely and just use pipx — Homebrew formulas with Python virtualenvs and deep dependency trees (claude-agent-sdk has many transitive deps) are maintenance-heavy. The resource blocks must be regenerated on every release.

**Resolution**: The user explicitly asked for brew installation. The maintenance burden is real but manageable by automating resource block generation in the release workflow. If it becomes unmaintainable, we can always fall back to pipx-only.

### Architecture

```
rangelak/ColonyOS (this repo)
├── Formula/colonyos.rb          ← Development reference (may be removed)
├── .github/workflows/release.yml ← Gains "update-homebrew" job
├── deploy/provision.sh           ← NEW: VM provisioning script
└── src/colonyos/doctor.py        ← Gains install-method detection

rangelak/homebrew-colonyos (NEW repo)
└── Formula/colonyos.rb           ← The canonical formula, auto-updated
```

### Dependencies & Constraints

- **`homebrew-pypi-poet`**: Generates resource blocks from a pip-installed package. Must be run in CI to capture the full dependency tree.
- **Fine-grained PAT**: Required for the release workflow to push to the tap repo. Scoped to `rangelak/homebrew-colonyos` only, stored as `HOMEBREW_TAP_TOKEN` in the `pypi` environment.
- **Formula resource blocks**: Must be regenerated on every release because dependency versions may change. The release workflow handles this automatically.
- **Existing files to modify**: `.github/workflows/release.yml`, `src/colonyos/doctor.py`, `src/colonyos/init.py`, `README.md`
- **New files**: `deploy/provision.sh`, tap repo `Formula/colonyos.rb`, tap repo `README.md`

### Security Considerations (from Staff Security Engineer)

- Fine-grained PAT for tap repo with minimal scope (contents:write on `homebrew-colonyos` only)
- Formula SHA-256 verified against PyPI artifact
- `deploy/provision.sh` should recommend `systemd-creds` for secrets, not plaintext env files
- Guard `colonyos init` against running outside a git repository (prevents `.colonyos/` with `bypassPermissions` agents in overly broad directories)

## 7. Success Metrics

1. **End-to-end brew install**: `brew install rangelak/colonyos/colonyos && colonyos --version` succeeds on clean macOS (CI-verified)
2. **Auto-update latency**: Formula updated within 10 minutes of PyPI publish on every `v*` tag
3. **Doctor accuracy**: `colonyos doctor` shows correct upgrade instructions for brew, pipx, and pip installs
4. **VM provision time**: `deploy/provision.sh` on a fresh Ubuntu 22.04 VM results in `colonyos doctor` passing within 5 minutes

## 8. Open Questions

1. **PAT setup**: Who creates the `HOMEBREW_TAP_TOKEN` fine-grained PAT and adds it to the repo secrets? (Manual step, needs documentation)
2. **Tap repo creation**: Should the tap repo be created manually or via `gh repo create`? (Manual, one-time setup)
3. **Formula testing in CI**: Should we add a CI job that runs `brew install --build-from-source` on PRs touching the formula? (Nice-to-have, not V1)
4. **claude-agent-sdk transitive deps**: How many resource blocks will be needed? Could be 50+. Is the maintenance burden acceptable? (Automated generation mitigates this)
