# Review: Linus Torvalds — Homebrew Global Installation & VM-Ready Deployment

**Branch**: `colonyos/add_brew_installation_we_should_be_able_to_have_f9c251f8f1`
**PRD**: `cOS_prds/20260330_182656_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Round**: 2 (post-fix holistic review)
**Date**: 2026-03-30

---

## Checklist

### Completeness
- [x] FR-1 (Homebrew Tap): `docs/homebrew-tap-setup.md` with step-by-step PAT and repo creation. In-repo `Formula/colonyos.rb` updated to reference the canonical tap.
- [x] FR-2 (Formula with resource blocks): `scripts/generate-homebrew-formula.sh` uses `homebrew-pypi-poet` in a temp venv, validates SHA-256 (64 hex), validates no `v` prefix, includes caveats and test blocks.
- [x] FR-3 (Release workflow tap update): `update-homebrew` job in `release.yml` with concurrency group, exact-version sdist lookup, credential helper, failure issue creation.
- [x] FR-4 (Install method detection): `detect_install_method()` in `doctor.py` checks `sys.executable` for `/Cellar/` and `/pipx/venvs/`.
- [x] FR-5 (VM provisioning): `deploy/provision.sh` — Ubuntu version guard, deadsnakes PPA, Node.js via signed apt repo, systemd setup, `chmod 600` env file.
- [x] FR-6 (README update): Homebrew listed first, curl kept, VM deployment section added.
- [x] FR-7 (Non-git-repo guard): `is_git_repo()` walks parents, CLI warns with `click.confirm`.
- [x] No TODO/placeholder code remains.

### Quality
- [x] All 402 tests pass with zero regressions
- [x] Code follows existing project conventions (Click CLI, pytest, YAML workflows)
- [x] No new runtime dependencies added
- [x] No unrelated changes included
- [x] GitHub Actions pinned to full SHA commits
- [x] Shell scripts use `set -euo pipefail`

### Safety
- [x] No secrets in committed code — `HOMEBREW_TAP_TOKEN` only via `${{ secrets.HOMEBREW_TAP_TOKEN }}`
- [x] Credential helper used for git auth (no token in clone URL)
- [x] API key prompts use `read -rs` (silent input)
- [x] Env file created with `chmod 600`
- [x] Script warns about systemd-creds for production

---

VERDICT: approve

FINDINGS:
- [scripts/generate-homebrew-formula.sh]: `setuptools<78` pin will rot. The comment explains why, and it only runs in CI, so it's contained. When poet drops pkg_resources, this breaks and the CI will tell you immediately.
- [scripts/generate-homebrew-formula.sh]: The GNU sed command (`-e :a -e '/^[[:space:]]*$/d;N;ba'`) is write-only code. It works, the fallback handles BSD sed, and the comment says it only runs on Ubuntu CI runners. Fine.
- [deploy/provision.sh]: Node.js major version hardcoded to 20. When Node 22 LTS lands, update the constant. It's one line, in an obvious place.

SYNTHESIS:
I said in the PRD review that Homebrew formulas with deep Python dependency trees are a maintenance burden, and I still believe that. But the user asked for it, and this implementation automates away the worst of the pain — formula generation is fully automated in CI, resource blocks are regenerated on every release, and there's a failure notification if anything breaks. The code is straightforward throughout. The shell scripts have proper error handling without being over-engineered. The Python changes are minimal and surgical — `detect_install_method()` is three `if` statements checking string substrings, which is exactly the right amount of complexity. `is_git_repo()` walks parents looking for `.git`, handles both directories and files (submodules), done. The provisioning script does seven things in seven clearly-labeled steps, each one doing one job. The awk filter for poet output is three lines instead of a parser. The previous reviewers caught the security nits (silent secret input, credential helper for git auth) and they've been fixed. 402 tests pass. 20 files changed, all doing exactly what the PRD asked for, nothing more. Ship it.
