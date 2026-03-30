# Staff Security Engineer — Review Round 1

**Branch**: `colonyos/add_brew_installation_we_should_be_able_to_have_f9c251f8f1`
**PRD**: `cOS_prds/20260330_182656_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Review Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-7)
- [x] All 7 parent tasks and 25 sub-tasks marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (100 in test_doctor/test_init/test_readme, 65 in test_e2e_validation, 38 in test_ci_workflows, 191 in test_cli)
- [x] No linter errors introduced (shellcheck integrated into CI for both new scripts)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code (only sanitization patterns and documentation placeholders like `sk-ant-...`)
- [x] No destructive database operations
- [x] Error handling present for failure cases

---

## Security-Specific Findings

### POSITIVE: PAT scope and documentation

The `HOMEBREW_TAP_TOKEN` is correctly documented as a fine-grained PAT scoped only to `rangelak/homebrew-colonyos` with `contents:write` — minimal privilege. The `update-homebrew` workflow job correctly has `permissions: contents: read` for the source repo, relying solely on the PAT for tap repo write access. Two setup guides (`docs/homebrew-tap-setup.md`, `scripts/HOMEBREW_TAP_SETUP.md`) document PAT rotation.

### POSITIVE: Non-git-repo guard (FR-7)

The `is_git_repo()` guard in `init.py` prevents `.colonyos/` configuration from being created in overly broad directories like `$HOME` or `/`. This was specifically called out in the PRD security section. The guard walks parent directories correctly and handles both `.git` directories and `.git` files (submodules).

### POSITIVE: Provision script secrets handling

`deploy/provision.sh` writes the env file with `chmod 600` and prints a warning recommending `systemd-creds` or a secrets manager for production. This matches the PRD security requirement.

### CONCERN: Token in git clone URL (release.yml)

Line in `release.yml`:
```bash
git clone "https://x-access-token:${HOMEBREW_TAP_TOKEN}@github.com/rangelak/homebrew-colonyos.git" /tmp/tap
```

The token is embedded in the clone URL. While GitHub Actions masks secrets in logs, if _any_ step after this prints the git remote URL (e.g., `git remote -v`, a `set -x`, or a diagnostic error message), the token could leak into workflow logs. **Recommendation**: Use `git clone https://github.com/rangelak/homebrew-colonyos.git /tmp/tap` then set credentials via `git -c http.extraheader="Authorization: bearer ${HOMEBREW_TAP_TOKEN}"` or use `git credential` helper. This is a low-severity concern since Actions does mask known secrets, but defense-in-depth applies.

### CONCERN: provision.sh pipes curl to bash

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
```

This is the standard NodeSource installation method, but it downloads and executes arbitrary code as root. If the NodeSource CDN is compromised, the VM is owned. **Recommendation**: Consider pinning to a specific NodeSource release or verifying a GPG signature. This is standard practice across the industry but worth noting for a tool that runs with repo access.

### CONCERN: `read -r` for secrets in provision.sh

```bash
read -r -p "  Enter ANTHROPIC_API_KEY (or leave blank to configure later): " ANTHROPIC_KEY
```

The `read` command echoes input to the terminal. For secrets, `read -rs` (silent mode) should be used to prevent shoulder-surfing or terminal scrollback exposure. The `--yes` non-interactive mode reads from environment variables which is fine.

### CONCERN: Formula generation runs pip install in temp venv

`scripts/generate-homebrew-formula.sh` does `pip install --quiet 'setuptools<78' "${PACKAGE_NAME}==${VERSION}" homebrew-pypi-poet` in a CI environment. This is a supply chain vector — if a malicious package claims the `colonyos` name on PyPI (typosquat unlikely since it's your package, but `homebrew-pypi-poet` could be compromised), the CI job runs it. Since this runs after the `publish` job succeeds, the package being installed is the one just published, which is fine. The `homebrew-pypi-poet` dependency is the real risk surface. **Recommendation**: Pin `homebrew-pypi-poet` to a specific version in the script.

### INFO: SHA-256 validation in generate-homebrew-formula.sh

Good: The script validates SHA-256 format (`^[a-f0-9]{64}$`) and rejects `v` prefix on versions. This prevents common mistakes from creating a broken formula.

### INFO: Actions are SHA-pinned

All GitHub Actions (`checkout`, `setup-python`, `download-artifact`) are pinned to full commit SHAs in the `update-homebrew` job. This is correct and matches existing project conventions.

### INFO: Duplicate documentation

Both `docs/homebrew-tap-setup.md` and `scripts/HOMEBREW_TAP_SETUP.md` document the same PAT setup process. While not a security issue, duplication risks them diverging. Consider removing one and linking to the other.

---

VERDICT: approve

FINDINGS:
- [.github/workflows/release.yml]: Token embedded in git clone URL — use credential helper instead of URL embedding for defense-in-depth
- [deploy/provision.sh]: `read -r` for API keys should use `read -rs` (silent) to avoid echoing secrets to terminal
- [deploy/provision.sh]: `curl | bash` for NodeSource installs arbitrary code as root — standard but worth pinning
- [scripts/generate-homebrew-formula.sh]: `homebrew-pypi-poet` dependency should be version-pinned to reduce supply chain risk
- [docs/homebrew-tap-setup.md, scripts/HOMEBREW_TAP_SETUP.md]: Duplicate PAT setup documentation may diverge over time

SYNTHESIS:
This is a solid implementation that addresses all PRD requirements with appropriate security measures. The PAT is correctly scoped to minimal privileges, the env file permissions are restrictive, the non-git-repo guard prevents config sprawl in dangerous directories, and all Actions are SHA-pinned. The concerns raised are hardening recommendations rather than blockers: the token-in-URL pattern is common in GitHub Actions, the `read` without silent mode is a minor UX issue, and the unpinned `homebrew-pypi-poet` is a low-probability supply chain risk. The provisioning script's recommendation of `systemd-creds` for production secrets shows good security awareness. I'm approving because no finding represents a material vulnerability — all are defense-in-depth improvements that can be addressed in a follow-up.
