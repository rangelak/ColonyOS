# Review by Staff Security Engineer (Round 3)

I now have a comprehensive view of the implementation. Here is my structured review:

---

## Security Review — Staff Security Engineer

### Assessment Summary

I've reviewed the full diff (23 files, ~1535 additions) across 3 commits implementing CI/CD pipeline, automated releases, multi-channel installation (curl, Homebrew), and single-source versioning.

---

### Completeness

All 6 functional requirements from the PRD (FR-1 through FR-6) are implemented. All 8 task groups (33 subtasks) are marked complete. No TODO/placeholder code remains in shipped logic. The Homebrew formula has a placeholder SHA256 which is documented and intentional — it gets populated by the first release workflow run.

Tests: 58 new tests pass across `test_version.py`, `test_ci_workflows.py`, `test_install_script_integration.py`, plus updates to `test_cli.py`.

### Quality

- Code follows existing project conventions (Click CLI, pytest classes, src-layout)
- `setuptools-scm` is a well-established dependency, not a random addition
- No linter errors introduced (shellcheck is gated in CI)
- README updates are proportional and accurate

---

### Security Findings

**GOOD — Supply Chain Hardening:**
- [`.github/workflows/ci.yml`]: All GitHub Actions pinned to full commit SHAs (e.g., `actions/checkout@34e114...`), not mutable tags. This is correct practice and prevents tag-repoint attacks. Tests enforce this invariant.
- [`.github/workflows/release.yml`]: Same SHA pinning on all actions including `pypa/gh-action-pypi-publish@4bb033...`.
- [`.github/workflows/ci.yml`]: Top-level `permissions: {}` with per-job grants. This is textbook least privilege.
- [`.github/workflows/release.yml`]: `id-token: write` is scoped only to the `publish` job, not granted globally. `contents: write` is only on the `release` job.

**GOOD — Curl Installer Script Safety:**
- [`install.sh`]: Uses `set -euo pipefail` — strict mode prevents silent failures
- [`install.sh`]: TTY detection via `[ -t 0 ]` prevents hanging when piped via `curl | sh`
- [`install.sh`]: Interactive `read` uses `< /dev/tty` — correct pattern for curl-pipe-sh
- [`install.sh`]: Non-interactive mode without `--yes` **fails safe** (exits 1) rather than auto-installing software without consent. This is the right call.
- [`install.sh`]: Unknown flags cause immediate exit — no silent flag swallowing
- [`install.sh`]: Uses `curl -fsSL` (the `-f` flag detects HTTP errors instead of silently executing error pages)

**GOOD — Homebrew Update via PR:**
- [`.github/workflows/release.yml`]: The `update-homebrew` job creates a PR rather than pushing directly to main. This preserves code review as a control point.
- [`.github/workflows/release.yml`]: Version format is validated with regex before `sed` substitution — prevents injection via crafted tag names
- [`.github/workflows/release.yml`]: SHA256 format is validated (exactly 64 hex chars)
- [`.github/workflows/release.yml`]: Guard checks verify exactly 1 url and 1 sha256 line before substitution — prevents multi-match corruption

**CONCERN — Medium: `--break-system-packages` fallback:**
- [`install.sh` L114]: The PEP 668 fallback uses `--break-system-packages`. While it's combined with `--user` (so it's user-scoped, not system-wide), and there's a clear warning, this is still a flag that bypasses a safety guardrail. The warning message is adequate and suggests the proper alternative (`apt install pipx`). This is acceptable for a v0.1 installer targeting developers.

**CONCERN — Low: Checksums are integrity, not authenticity:**
- [`.github/workflows/release.yml`]: SHA-256 checksums are generated and published. This provides tamper detection if someone verifies, but does not prove provenance. The PRD explicitly defers Sigstore/GPG to v1.0, which I accept, but want to note: checksums hosted alongside the artifact (same GitHub Release) provide zero protection against a compromised repository — an attacker who modifies the artifact also modifies the checksum. This is a known limitation documented in the PRD non-goals.

**CONCERN — Low: `install.sh` hosted on raw.githubusercontent.com:**
- [`README.md`]: The curl one-liner points to `raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh`. Anyone with write access to `main` can modify this script, and every future `curl | sh` invocation would execute the modified version. This is standard for the pattern but worth noting. The recommendation in the PRD to make pip/pipx the recommended path (with curl as alternative) is correctly reflected.

**NO ISSUES:**
- No secrets, credentials, or API tokens in committed code
- No `.env` files committed
- PyPI publishing uses OIDC Trusted Publishers — no stored API tokens
- `GITHUB_TOKEN` is the auto-provisioned token, not a PAT
- No destructive database operations

---

VERDICT: approve

FINDINGS:
- [install.sh L114]: `--break-system-packages` fallback bypasses PEP 668 safety — acceptable with the warning message present, but document this trade-off for future maintainers
- [.github/workflows/release.yml]: SHA-256 checksums provide integrity but not authenticity (deferred to v1.0 per PRD — acceptable)
- [README.md]: curl one-liner runs code from `main` branch — standard risk for this pattern, mitigated by making pip/pipx the recommended path
- [.github/workflows/ci.yml]: All actions pinned to commit SHAs — exemplary supply chain hygiene
- [.github/workflows/release.yml]: Least-privilege permissions with per-job scoping — correct
- [install.sh]: Non-interactive mode without `--yes` fails safe — correct security posture
- [.github/workflows/release.yml]: Homebrew update via PR with version/SHA validation — prevents injection and preserves review gate

SYNTHESIS:
From a security engineering perspective, this is a well-executed implementation. The most critical decisions — SHA-pinned actions, least-privilege permissions, OIDC publishing (no stored secrets), fail-safe non-interactive behavior, and PR-gated Homebrew updates — are all correct. The `curl | sh` pattern is inherently risky, but the implementation handles it as well as possible: TTY detection, `/dev/tty` reads, `--yes` for explicit consent, and fail-safe defaults. The `--break-system-packages` fallback is the one area where the script overrides a safety guardrail, but it's user-scoped and clearly warned. The deferred items (Sigstore signing, artifact provenance) are reasonable for a pre-1.0 project. I approve this implementation with no blocking issues.