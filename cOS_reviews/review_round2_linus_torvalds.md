# Review by Linus Torvalds (Round 2)

Here's my review:

---

## Code Review — Linus Torvalds

I've read the PRD, reviewed every changed file across the 2 commits on this branch, run all 125 new/modified tests (all pass), and verified the install script in dry-run mode.

### Summary of Implementation

The branch adds:
- `.github/workflows/ci.yml` — CI pipeline (pytest on 3.11/3.12, shellcheck)
- `.github/workflows/release.yml` — Tag-triggered release: test → build → PyPI publish → GitHub Release → Homebrew formula update
- `install.sh` — Curl installer with OS detection, Python version check, pipx install, dry-run mode, TTY-aware stdin handling
- `Formula/colonyos.rb` — Homebrew formula
- `pyproject.toml` / `src/colonyos/__init__.py` — setuptools-scm single-source versioning
- `src/colonyos/doctor.py` — Version check added
- Tests: `test_version.py`, `test_ci_workflows.py`, `test_install_script_integration.py`, `test_install_script.sh`
- README and review file updates

---

VERDICT: request-changes

FINDINGS:
- [Formula/colonyos.rb:13]: `sha256 "PLACEHOLDER_SHA256_UPDATED_BY_RELEASE_WORKFLOW"` — This is a literal placeholder string. Anyone who tries `brew install colonyos/tap/colonyos` before the first release workflow runs will get a checksum mismatch and a cryptic Homebrew error. Either populate this with the actual SHA256 of the current v0.1.0 tarball from PyPI, or don't ship the formula file until the first release. Shipping known-broken artifacts is not acceptable — it's worse than shipping nothing.
- [.github/workflows/release.yml:185-211]: The `update-homebrew` job commits directly to `main` via `git push` from a GitHub Actions bot. This bypasses branch protection, PR review, and any required status checks. A release workflow should not be silently pushing commits to your default branch. Use a PR-based approach (open a PR from the bot, auto-merge it) or at minimum document this loudly as a deliberate bypass.
- [.github/workflows/release.yml:195]: The `sed -i` command for updating the Homebrew formula is fragile. It pattern-matches on the URL and sha256 lines with regex. If someone reformats the formula or adds a second `sha256` for a resource block, this silently corrupts the file. A templating approach or at least a `grep -c` guard to verify exactly one substitution was made would be more robust.
- [install.sh:105-106]: In non-interactive mode (the `curl | sh` path), pipx is installed automatically without user consent. The PRD explicitly says "Installs pipx if not present (**with user confirmation**)". The non-interactive path skips confirmation and force-installs. This is a design decision worth acknowledging, but it contradicts FR-4.3. At minimum, add a `--yes` or `--no-pipx` flag so automation can opt out.
- [install.sh:99]: `pip_install_user pipx` with `--break-system-packages` fallback is a big hammer. On Debian 12+ / Ubuntu 23.04+, this deliberately bypasses the distribution's package manager protection. The PEP 668 guard exists for a reason. This should at minimum warn the user clearly about what it's doing, not silently retry with the nuclear option.
- [.github/workflows/release.yml]: The test job in the release workflow is duplicated verbatim from `ci.yml`. This is copy-paste that will drift. Extract into a reusable workflow (`workflow_call`) or use `workflow_run` to depend on the CI workflow. Don't Repeat Yourself applies to YAML too.
- [tests/test_ci_workflows.py, tests/test_install_script_integration.py]: These are not terrible, but ~50% of the test lines are testing that YAML files contain certain keys and that a shell script contains certain strings. These are essentially lint checks masquerading as unit tests. The YAML structure tests are fragile — they'll break on any refactor of the workflow files. The shellcheck CI step already validates install.sh syntax. Consider whether these "tests" are pulling their weight or just adding maintenance burden.
- [Formula/colonyos.rb]: The formula uses `pypi.io` URLs. The conventional PyPI URL scheme is `https://files.pythonhosted.org/packages/source/c/colonyos/colonyos-VERSION.tar.gz`. `pypi.io` may redirect but it's not the canonical host. Use the right URL.

SYNTHESIS:
The implementation covers all six functional requirements from the PRD and the code is generally competent — the workflow structure is sound, the install script handles edge cases like TTY detection and PEP 668, and the single-source versioning is done correctly. The test suite passes clean. But there are two things I won't let slide: (1) shipping a Homebrew formula with a literal `PLACEHOLDER_SHA256` string that will fail for any user who actually tries it, and (2) the release workflow pushing commits directly to main without review. The first is shipping broken code. The second is a governance hole. Fix those two, consider the `sed` fragility and the duplicated workflow YAML, and this is ready to merge.