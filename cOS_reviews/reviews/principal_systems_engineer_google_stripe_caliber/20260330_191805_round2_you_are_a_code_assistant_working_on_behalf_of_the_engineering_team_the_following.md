# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

---

## Review: Principal Systems Engineer — Homebrew Global Installation & VM-Ready Deployment

I've reviewed the full diff (20 files, ~2,203 lines) across the branch against the PRD. All 400 tests pass (333 unit + 67 e2e).

### Checklist

**Completeness** — All 7 functional requirements implemented:
- ✅ FR-1: Tap setup documented with step-by-step guide
- ✅ FR-2: Formula generation with `homebrew-pypi-poet`, resource blocks, caveats, test block
- ✅ FR-3: Release workflow `update-homebrew` job with SHA-256 validation, concurrency group, failure alerting
- ✅ FR-4: `detect_install_method()` in doctor with method-specific upgrade hints
- ✅ FR-5: `deploy/provision.sh` — comprehensive VM provisioning with dry-run, deadsnakes PPA fallback, signed apt repos
- ✅ FR-6: README updated with Homebrew first, VM deployment section added
- ✅ FR-7: `is_git_repo()` guard with warn-not-fail behavior

**Quality** — ✅ All tests pass, CI updated (shellcheck + formula dry-run), conventions followed, no new deps

**Safety** — ✅ No secrets committed, env file `chmod 600`, all Actions SHA-pinned

### Findings (all non-blocking)

| File | Finding | Severity |
|---|---|---|
| `release.yml` | Token embedded in clone URL — credential helper approach preferred for log-leak defense-in-depth | Low |
| `release.yml` | No retry on transient git push failure — issue auto-creation provides backstop | Low |
| `provision.sh` | `read -r` should be `read -rs` for API key prompts (suppress terminal echo) | Low |
| `provision.sh` | pipx binary path may not be visible to systemd service (pre-existing, not introduced) | Info |
| `doctor.py` | Install method detection is heuristic-based; non-standard paths will misidentify (informational only) | Low |

VERDICT: **approve**

SYNTHESIS: This is a well-executed implementation with mature operational thinking. The concurrency handling (`cancel-in-progress: false`), auto-generated GitHub issues on tap failures, SHA-256 validation with exact-version file matching, and the `set -euo pipefail` + dry-run patterns throughout show someone thinking about what happens when things break. The five findings are all hardening opportunities, not correctness bugs. The blast radius of any single failure is minimal — formula breakage doesn't block PyPI, provision script failures don't affect existing installs, and install-method misdetection is informational only. Ship it.
