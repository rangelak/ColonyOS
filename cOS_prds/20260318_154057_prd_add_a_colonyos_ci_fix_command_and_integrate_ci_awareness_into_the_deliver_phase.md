# PRD: `colonyos ci-fix` Command & CI-Aware Deliver Phase

## 1. Introduction/Overview

ColonyOS currently opens PRs via its deliver phase but has no awareness of whether CI passes or fails after the PR is opened. This leaves a gap: the pipeline marks a run as COMPLETED even when CI is red, requiring manual intervention.

This feature adds:
1. A standalone `colonyos ci-fix <pr-number>` CLI command that detects CI failures on a PR, fetches failure logs, and runs an AI agent to fix the code and push a fix commit.
2. An optional post-deliver CI monitoring loop in the `auto` pipeline that waits for CI results and triggers the ci-fix agent automatically when checks fail.

This closes the "last mile" gap between code delivery and a green CI build, making ColonyOS a true end-to-end autonomous pipeline.

## 2. Goals

- **G1**: Enable automated CI failure detection and remediation via a single CLI command (`colonyos ci-fix <pr>`).
- **G2**: Integrate CI awareness into the `auto` pipeline so runs are only marked COMPLETED after CI passes (or retries are exhausted).
- **G3**: Track CI fix attempts as first-class `Phase.CI_FIX` entries in `RunLog`, visible in `colonyos stats`.
- **G4**: Maintain the existing pattern of `gh` CLI-based GitHub interaction — no new Python HTTP dependencies.
- **G5**: Ensure all CI log content is sanitized before injection into agent prompts (defense-in-depth against leaked secrets).

## 3. User Stories

**US1 — Standalone CI fix**: As a developer, I run `colonyos ci-fix 42` after my PR's CI fails. ColonyOS fetches the failed check logs, identifies the issue (e.g., a missing import caught by mypy), pushes a fix commit, and reports success.

**US2 — Wait for re-run**: As a developer, I run `colonyos ci-fix 42 --wait` and ColonyOS pushes a fix, then polls CI until the re-run completes, reporting final pass/fail status.

**US3 — Retry loop**: As a developer, I run `colonyos ci-fix 42 --max-retries 3` and ColonyOS loops up to 3 times: fix → push → wait → re-check → fix again if still failing.

**US4 — Auto pipeline integration**: As a team lead, I set `ci_fix.enabled: true` in `.colonyos/config.yaml`. Now when `colonyos auto` finishes a delivery, it waits for CI and auto-fixes failures before marking the run complete.

**US5 — Cost visibility**: As a budget-conscious user, I run `colonyos stats` and see CI fix attempts broken out as their own phase with cost and duration, separate from the implementation and review phases.

**US6 — Any PR**: As a developer who hasn't used ColonyOS for this PR, I still run `colonyos ci-fix 99` on a manually-created PR and it works, because the command operates on any PR in the repo.

## 4. Functional Requirements

### 4.1 New CLI Command: `colonyos ci-fix`

- **FR1**: Accept a PR number (integer) or GitHub PR URL as a positional argument. Parse URLs using the same pattern as `parse_issue_ref` in `github.py`.
- **FR2**: Fetch check run statuses via `gh pr checks <number> --json name,state,conclusion,detailsUrl`.
- **FR3**: If all checks pass, print a success message and exit 0.
- **FR4**: If any checks failed, fetch failed check run logs via `gh run view <run-id> --log-failed`, filtered to only the failed steps.
- **FR5**: Truncate log output to a maximum of 12,000 characters per failed step (tail-biased — keep the end where errors appear), with a `[... N lines truncated]` marker.
- **FR6**: Sanitize log content through both XML tag stripping (`sanitize_untrusted_content`) and a new secret-pattern regex pass (redact `ghp_*`, `ghs_*`, `sk-*`, `AKIA*`, `Bearer` tokens, and high-entropy base64 strings > 40 chars adjacent to keywords like TOKEN/SECRET/KEY/PASSWORD).
- **FR7**: Format CI failure context into a structured prompt block with step name, exit code, and sanitized log snippet, wrapped in `<ci_failure_log>` delimiters.
- **FR8**: Run a CI fix agent session using the new `ci_fix.md` instruction template with full Read/Write/Edit/Bash/Glob/Grep tools (same as existing fix phase).
- **FR9**: After the agent completes, push the fix commit to the PR branch.
- **FR10**: Support `--wait` flag: after pushing, poll `gh pr checks` every 30 seconds (with 1.5x exponential backoff, capped at 5 minutes between polls) until CI completes or `--wait-timeout` (default 600 seconds) is reached.
- **FR11**: Support `--max-retries N` (default 1): loop fix → push → wait → re-check up to N times. Exit with success if CI passes, failure if retries exhausted.
- **FR12**: Support `--wait-timeout N` (default 600 seconds): maximum time to wait for CI after each push.
- **FR13**: Record each CI fix attempt as a `PhaseResult` with `Phase.CI_FIX`.

### 4.2 Pre-flight Checks

- **FR14**: Refuse to run if the working tree has uncommitted changes (`git status --porcelain` is non-empty). Hard error with actionable message.
- **FR15**: Refuse to run if the local branch is behind the remote. Hard error directing user to pull.
- **FR16**: Validate `gh` CLI is authenticated (same pattern as `doctor.py`). On failure, direct user to `colonyos doctor`.

### 4.3 Config Integration

- **FR17**: Add a `ci_fix` section to `config.yaml`:
  ```yaml
  ci_fix:
    enabled: false          # Enable post-deliver CI monitoring in auto mode
    max_retries: 2          # Max fix-push-wait cycles
    wait_timeout: 600       # Seconds to wait for CI per cycle
    log_char_cap: 12000     # Max chars of CI log per failed step
  ```
- **FR18**: Parse into a new `CIFixConfig` dataclass in `config.py`, with defaults matching above.

### 4.4 Auto Pipeline Integration

- **FR19**: When `ci_fix.enabled: true`, the `run()` function in `orchestrator.py` adds a post-deliver CI fix loop: wait for initial CI → if failed, run ci-fix → push → wait → retry up to `max_retries`.
- **FR20**: The auto loop only marks `RunStatus.COMPLETED` after CI passes or retries are exhausted (in which case, still COMPLETED but the CI_FIX phase records `success=False`).
- **FR21**: CI fix cost counts against `budget.per_run` to prevent runaway spend. The iteration cap (`max_retries`) independently prevents infinite loops.

### 4.5 New `Phase.CI_FIX` Enum Value

- **FR22**: Add `CI_FIX = "ci_fix"` to the `Phase` enum in `models.py`.
- **FR23**: Ensure `stats.py` includes CI_FIX in aggregate dashboards (cost, duration, success rate).

### 4.6 Instruction Template: `ci_fix.md`

- **FR24**: Create `src/colonyos/instructions/ci_fix.md` modeled after `fix.md`, with placeholders: `{branch_name}`, `{ci_failure_context}`, `{fix_attempt}`, `{max_retries}`.
- **FR25**: The template scopes the agent to: read the failure, fix only the failing code, run tests locally as a sanity check, commit with a clear message.
- **FR26**: The template explicitly prohibits refactoring unrelated code, adding features, or changing the PR description.

## 5. Non-Goals

- **NG1**: Third-party CI support (CircleCI, Jenkins, GitLab CI). GitHub Actions only for v1. The log-fetching layer will be cleanly separated so providers can be added later.
- **NG2**: Rich TUI dashboard for CI monitoring. A simple spinner with elapsed time and status is sufficient.
- **NG3**: Comprehensive secrets scanning. Basic regex patterns for common secret formats; not a replacement for dedicated secret scanners.
- **NG4**: Re-entering the review/fix loop when CI fails. CI fix is a distinct post-deliver phase, not a code quality review.
- **NG5**: Automatic CI fix on non-ColonyOS PRs during `auto` mode. The standalone command works on any PR; auto-mode integration only fires on ColonyOS-created PRs.

## 6. Technical Considerations

### 6.1 Architecture

The feature follows established patterns:
- **New module `ci.py`**: Mirrors `github.py` — wraps `gh` CLI subprocess calls for CI-specific operations. Functions: `fetch_pr_checks()`, `fetch_check_logs()`, `format_ci_failures_as_prompt()`, `sanitize_ci_logs()`.
- **New instruction `ci_fix.md`**: Mirrors `fix.md` — same Staff+ Engineer role, but scoped to CI failures instead of reviewer findings.
- **CLI command**: Follows the Click pattern of existing commands (`run`, `review`, `auto`). Uses `_find_repo_root()`, `load_config()`, and the same error-handling conventions.
- **Orchestrator integration**: Slots in after the deliver phase call (around line 1536 of `orchestrator.py`), gated by `config.ci_fix.enabled`.

### 6.2 Subprocess Patterns

All `gh` CLI calls follow the established pattern from `github.py`:
- `capture_output=True, text=True, timeout=10, cwd=repo_root`
- `FileNotFoundError` catch for missing `gh`
- `TimeoutExpired` catch for hangs
- JSON output parsing via `--json` flag
- Non-zero returncode → `click.ClickException` with actionable message

### 6.3 Log Truncation

Mirroring `_COMMENTS_CHAR_CAP = 8_000` in `github.py`:
- `_CI_LOG_CHAR_CAP = 12_000` per failed step
- Tail-biased: keep the last N lines (errors are at the bottom)
- `[... N lines truncated]` marker at the top when truncated
- Total injection capped across all failed steps

### 6.4 Sanitization

Extends `sanitize.py` with a new `sanitize_ci_logs()` function:
1. Apply existing `sanitize_untrusted_content()` (XML tag stripping)
2. Regex pass for common secret patterns: `ghp_\w+`, `ghs_\w+`, `sk-\w+`, `AKIA\w+`, `Bearer \S+`, and base64 blobs > 40 chars near TOKEN/SECRET/KEY/PASSWORD keywords
3. Replace matches with `[REDACTED]`

### 6.5 Polling Strategy

- Initial interval: 30 seconds
- Backoff: 1.5x multiplier
- Max interval: 5 minutes
- Default timeout: 600 seconds (configurable via `--wait-timeout` and `ci_fix.wait_timeout`)
- Status output: single updating line with elapsed time and check status

### 6.6 Backward Compatibility

- `Phase.CI_FIX` is a new enum value — existing serialized `RunLog` JSON files will never contain it, so no migration needed.
- `CIFixConfig` defaults to `enabled: false`, so existing configs are unaffected.
- The `stats` command must handle runs with and without CI_FIX phases gracefully.

### 6.7 Persona Consensus & Tensions

**Strong consensus across all personas:**
- GitHub Actions only for v1 (unanimous)
- CI fix runs as a post-deliver phase, not re-entering the review/fix loop (unanimous)
- Hard refuse on uncommitted changes / behind remote (unanimous)
- Full agent tool access needed (6/7 agree; Steve Jobs advocated constraint but the existing fix phase already uses full tools)
- Sanitize CI logs for secrets (unanimous)
- Fail fast on `gh` CLI issues with actionable error (unanimous)

**Key tension — scope of `ci-fix` command:**
- **Michael Seibel, Linus, Jony Ive, Karpathy**: Work on **any PR** — growth wedge, useful standalone
- **Steve Jobs, Systems Engineer**: Restrict to **ColonyOS branches** — safer default, prevents foot-guns
- **Security Engineer**: Any PR but **warn if PR author ≠ authenticated user** (log injection risk)
- **Resolution**: Standalone command works on any PR (broader utility). Auto-mode integration only fires on ColonyOS PRs. Warn if PR author doesn't match authenticated user.

**Tension — budget model:**
- **Michael Seibel, Systems Engineer**: CI fix cost counts against `per_run` with separate iteration cap
- **Steve Jobs, Linus, Security Engineer**: Completely separate `ci_fix_budget`
- **Resolution**: CI fix cost counts against `per_run` (simpler accounting, prevents runaway spend from the same budget envelope). Iteration cap (`max_retries`) independently bounds attempts. Users can increase `per_run` if needed.

## 7. Success Metrics

- **SM1**: `colonyos ci-fix 42` successfully fixes CI on first attempt for >60% of common failure types (import errors, type errors, test assertion mismatches, linting).
- **SM2**: CI fix phase completes in <$2.00 average cost per attempt.
- **SM3**: End-to-end `colonyos auto` with `ci_fix.enabled: true` achieves green CI on >80% of delivered PRs (with up to 2 retries).
- **SM4**: Zero instances of secrets appearing in agent prompts from CI log injection (verified by sanitization unit tests).
- **SM5**: All existing tests continue to pass — no regressions.

## 8. Open Questions

- **OQ1**: Should the `--wait` flag be the default behavior (always wait after pushing a fix), or should the default be fire-and-forget? Current design: `--wait` is opt-in for standalone, always-on for auto-mode integration.
- **OQ2**: Should we add a `colonyos doctor` check for GitHub Actions specifically (e.g., detect if `.github/workflows/` exists)? Low priority but would improve error messages.
- **OQ3**: What is the right default for `max_retries`? Current design: 1 for standalone CLI (conservative), 2 for auto-mode config (more aggressive since it's unattended).
- **OQ4**: Should ci-fix attempts be shown in the PR description or as PR comments? Out of scope for v1 but worth considering.
