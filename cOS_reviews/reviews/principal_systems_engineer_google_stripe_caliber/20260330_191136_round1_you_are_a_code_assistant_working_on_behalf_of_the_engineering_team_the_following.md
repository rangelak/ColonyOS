# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

---

## Review Complete

**VERDICT: request-changes**

### P1 — Must Fix (3 items)

1. **`.github/workflows/release.yml` — Sdist glob ambiguity**: `ls dist/colonyos-*.tar.gz` can match multiple files. If it does, `sha256sum` gets confused and the formula ships with a wrong hash. Use `ls dist/colonyos-${VERSION}.tar.gz` or fail explicitly on multiple matches.

2. **`.github/workflows/release.yml` — Silent failure on tap push**: The `update-homebrew` job has zero failure alerting. If the PAT expires or the push fails, the `publish` job already succeeded — so the release looks green while the Homebrew formula goes stale. Nobody notices until a user complains. Add a `if: failure()` step that opens a GitHub issue or sends a notification.

3. **`deploy/provision.sh` — `pipx install` is not idempotent**: Re-running the provisioning script after a partial failure will itself fail because `pipx install colonyos` errors on "already installed." Use `pipx install --force` or guard with an existence check. This is the exact scenario where you need re-runnability.

### P2 — Should Fix (3 items)

4. **Release workflow race condition**: Concurrent tag pushes will cause the second `git push` to fail (non-fast-forward). Add a `concurrency` group or `git pull --rebase` before push.

5. **`curl | bash` for nodesource**: Supply chain risk. Install Node.js via signed apt repo (like the GitHub CLI installation just below it) instead of piping a remote script into bash.

6. **Duplicate documentation**: `docs/homebrew-tap-setup.md` and `scripts/HOMEBREW_TAP_SETUP.md` contain near-identical content. Keep one, delete the other.

### What's Good

- All 7 PRD requirements implemented with clear commit-to-task traceability
- 329 tests passing, shellcheck clean, no secrets in code
- Formula generation script is well-designed with input validation, temp-venv isolation, and `--dry-run`
- Doctor install-method detection is simple and effective
- Provisioning script is comprehensive with proper `chmod 600` on secrets and `systemd-creds` warning

Full review saved to `cOS_reviews/reviews/principal_systems_engineer/review_round1_homebrew_vm_deploy.md`.