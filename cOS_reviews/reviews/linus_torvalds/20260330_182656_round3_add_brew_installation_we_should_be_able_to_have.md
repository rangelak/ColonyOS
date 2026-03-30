# Review: Homebrew Global Installation & VM-Ready Deployment — Round 3

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/add_brew_installation_we_should_be_able_to_have_f9c251f8f1`
**PRD**: `cOS_prds/20260330_182656_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-03-30

---

## Checklist

### Completeness
- [x] FR-1: Homebrew tap repository — formula generation script and tap setup docs exist
- [x] FR-2: Formula with dependency resources — `generate-homebrew-formula.sh` uses `homebrew-pypi-poet` to produce resource blocks, formula has `depends_on`, test block, caveats
- [x] FR-3: Release workflow tap update — `update-homebrew` job in release.yml, SHA-256 verified, credential helper for auth, concurrency control, failure alerting
- [x] FR-4: Install method detection in doctor — `detect_install_method()` checks `sys.executable` path for Cellar/pipx patterns, upgrade hints match
- [x] FR-5: VM provisioning script — `deploy/provision.sh` handles full stack on Ubuntu 22.04+
- [x] FR-6: README update — Homebrew first, curl second, VM deployment section added
- [x] FR-7: Non-repo init guard — `is_git_repo()` walks parents, CLI warns and prompts

### Quality
- [x] All 403 tests pass
- [x] No linter errors introduced (shellcheck added to CI for new scripts)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets in committed code — PAT flows through GitHub secrets only
- [x] Credential helper pattern prevents token in URLs/logs
- [x] Error handling present throughout — exact-version sdist lookup, SHA-256 validation, failure issue creation
- [x] `chmod 600` on env file, `systemd-creds` recommendation for production

---

## Findings

- `[scripts/generate-homebrew-formula.sh]`: The `setuptools<78` pin is a ticking time bomb. When the pin stops working (setuptools 78+ already shipped), you'll need to either find a `poet` replacement or fork it. CI will catch this immediately when it breaks, so the blast radius is contained to a failed release — not a broken install. Acceptable.

- `[scripts/generate-homebrew-formula.sh]`: The GNU sed invocation (`sed -e :a -e '/^[[:space:]]*$/d;N;ba'`) is write-only code. It has a `|| echo` fallback for BSD sed, but the comment says it only runs on Ubuntu CI runners, which is correct. Fine, but if someone ever tries to run this locally on macOS they'll get the unprocessed output. Not a bug, just fragile.

- `[deploy/provision.sh]`: `NODE_MAJOR=20` hardcoded. Node 22 LTS is already out. One-line fix when someone gets to it. Non-blocking.

- `[src/colonyos/init.py]`: `is_git_repo()` is clean — walks parents, checks for both `.git` directory and file (submodules). Exactly what you'd expect, nothing more.

- `[src/colonyos/doctor.py]`: `detect_install_method()` is three `if` statements checking string substrings in `sys.executable`. This is the right level of complexity. No framework, no registry, no plugin system — just look at the path and return the answer.

- `[.github/workflows/release.yml]`: The failure notification step correctly uses `GITHUB_TOKEN` instead of `HOMEBREW_TAP_TOKEN`. The concurrency group with `cancel-in-progress: false` is the right call for a job that pushes to an external repo — you don't want half-pushed state. The `pull --rebase` before push handles concurrent tag pushes gracefully.

---

## Verdict

**VERDICT: approve**

## Synthesis

This is the third round of review and the implementation is solid. All seven functional requirements from the PRD are implemented, all 403 tests pass, and the previous rounds' findings (silent secret input, credential helper, redundant `which`, sed comment, failure notification token) have all been addressed. The code is simple throughout — `detect_install_method()` is three conditionals, `is_git_repo()` is a parent-walk loop, the provisioning script is seven labeled steps each doing one thing. The formula generation automates the maintenance burden I warned about in the PRD review, which is the correct answer: if you're going to have a Homebrew formula with a deep Python dependency tree, make the machine regenerate it on every release. The `setuptools<78` pin will eventually need attention, but CI will tell you exactly when. 20 files changed, 2265 lines added, all doing exactly what was asked for and nothing else. Ship it.
