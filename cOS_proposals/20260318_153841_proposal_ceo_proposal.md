## Proposal: CI Feedback Loop (`colonyos ci-fix`)

### Rationale
The pipeline currently stops at "PR opened" — but CI failures on delivered PRs are extremely common and break the autonomous loop. Adding automatic CI failure detection and repair closes the last major gap between "code written" and "code merged," making ColonyOS truly end-to-end autonomous. This is the single highest-leverage improvement because every other feature (CEO, reviews, learnings) is wasted if the delivered PR sits red in CI.

### Builds Upon
- "GitHub Issue Integration" (uses `gh` CLI and GitHub API patterns from `github.py`)
- "Post-Implement Verification Gate" (extends the verify→fix loop concept to post-delivery CI)
- "Resume Failed Runs (`--resume`)" (reuses the pattern of continuing work on an existing branch)

### Feature Request
Add a `colonyos ci-fix` command and integrate CI awareness into the deliver phase so that after a PR is opened, ColonyOS can detect CI check failures, fetch their logs, and automatically push fixes.

**New CLI command: `colonyos ci-fix <pr-number>`**
- Accepts a PR number (or URL) as argument
- Uses `gh pr checks <number>` to fetch check run statuses
- If all checks pass, reports success and exits
- If any checks failed, uses `gh api` to fetch the failed check run logs (annotation messages and log output)
- Formats the CI failure context (test name, error message, log snippet) into a structured prompt
- Runs a FIX phase on the PR's branch with the CI failure context injected, using a new `ci_fix.md` instruction template that tells the agent: "You are fixing CI failures on an open PR. Here are the failing checks and their logs. Fix the code and commit."
- After the fix, re-runs the local verification command (if configured) as a sanity check before pushing
- Pushes the fix commit to the PR branch
- Optionally re-checks CI status with `--wait` flag (polls `gh pr checks` for up to N minutes)
- Supports `--max-retries N` (default 3) to loop: fix → push → wait → re-check → fix again if still failing
- Tracks the ci-fix as a PhaseResult in the original run's RunLog (new `Phase.CI_FIX` enum value)

**Integration into the auto loop (optional, config-driven):**
- Add `ci_fix` section to config.yaml: `enabled: true`, `max_retries: 3`, `wait_timeout: 300` (seconds to wait for CI after each push)
- When enabled, the deliver phase in `orchestrator.py` doesn't just open the PR — it also waits for initial CI results and triggers the ci-fix loop if checks fail
- The auto loop only marks a run as COMPLETED after CI passes (or ci-fix retries exhausted)

**New files:**
- `src/colonyos/ci.py` — Functions: `fetch_pr_checks(pr_number)` → list of check results, `fetch_check_logs(check_id)` → failure details, `format_ci_failures_as_prompt(failures)` → structured text
- `src/colonyos/instructions/ci_fix.md` — Instruction template for the CI fix agent
- `tests/test_ci.py` — Unit tests for CI log parsing, prompt formatting, retry logic

**Modified files:**
- `src/colonyos/models.py` — Add `Phase.CI_FIX` enum value
- `src/colonyos/config.py` — Add `CIFixConfig` dataclass, parse from YAML
- `src/colonyos/cli.py` — Add `ci-fix` command with `--max-retries`, `--wait`, `--wait-timeout` options
- `src/colonyos/orchestrator.py` — Wire ci-fix loop after deliver phase when config enabled

**Acceptance criteria:**
1. `colonyos ci-fix 42` fetches check status for PR #42, identifies failures, and pushes a fix commit
2. `colonyos ci-fix 42 --wait` polls until CI re-runs and reports final status
3. `colonyos ci-fix 42 --max-retries 3` loops up to 3 fix attempts
4. When `ci_fix.enabled: true` in config, `colonyos auto` runs include post-deliver CI monitoring
5. CI fix attempts are recorded as `Phase.CI_FIX` in the run log and visible in `colonyos stats`
6. All new code has unit tests; `gh` CLI calls are mockable via subprocess injection