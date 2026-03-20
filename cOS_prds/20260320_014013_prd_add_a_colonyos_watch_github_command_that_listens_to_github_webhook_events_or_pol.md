# PRD: GitHub Watch Command for PR Review Auto-Fixes

## 1. Introduction/Overview

ColonyOS currently creates PRs via its autonomous pipeline (Plan → Implement → Review → Deliver) but lacks the ability to respond to human reviewer feedback automatically. When a reviewer clicks "Request Changes" on a ColonyOS-created PR, developers must manually copy-paste review comments into Slack or the CLI to trigger fixes.

The `colonyos watch-github` command closes this feedback loop by monitoring GitHub PR review events and automatically running the existing `run_thread_fix()` pipeline to address reviewer feedback. This extends the existing Slack thread-fix pattern to GitHub's native review interface.

**Why it matters:** The Slack thread-fix feature (1000+ LOC in `slack.py`, `run_thread_fix()` in `orchestrator.py`) already proves iteration value. GitHub PR reviews are the canonical place where external reviewers leave feedback, and forcing context-switching between GitHub and Slack creates friction for teams adopting ColonyOS.

## 2. Goals

1. **Close the feedback loop**: When a reviewer clicks "Request Changes" on a `colonyos/*` branch PR, automatically detect and process the fix request within 60 seconds (poll mode).

2. **Reuse existing infrastructure**: Leverage the `run_thread_fix()` pipeline, `QueueItem` state tracking, and sanitization patterns from the Slack watcher—no parallel implementation.

3. **Prevent abuse and runaway costs**: Enforce per-PR fix round limits, cumulative cost caps, and reviewer allowlists to prevent malicious or accidental budget exhaustion.

4. **Maintain security posture**: Treat GitHub PR review comments as maximally adversarial input (public repos allow comments from anyone) with the same defense-in-depth sanitization applied to Slack messages.

5. **Ship incrementally**: MVP delivers poll-mode only with `review_request_changes` trigger—webhooks, mentions, and GHE support are follow-on enhancements.

## 3. User Stories

### Story 1: Automated Fix on Request Changes
As a developer using ColonyOS, when a reviewer clicks "Request Changes" on my auto-generated PR with specific file/line comments, I want the watcher to automatically detect this, run fixes, push commits to the branch, and comment on the PR with status updates—so I don't have to manually re-trigger the pipeline.

### Story 2: Cost-Controlled Iteration
As a team lead, I want to configure maximum fix rounds per PR (`max_fix_rounds_per_pr: 3`) and cumulative cost caps (`max_fix_cost_per_pr_usd: 10.0`)—so a stuck loop or ambiguous feedback doesn't exhaust our API budget.

### Story 3: Reviewer Allowlist
As a security-conscious team, I want to restrict which GitHub users can trigger auto-fixes via an allowlist (`allowed_reviewers: [alice, bob]`)—so random drive-by commenters on public repos can't invoke the agent.

### Story 4: Status Visibility
As a PR author, I want the watcher to post a GitHub comment when it starts fixing ("🔧 Addressing review feedback...") and another when complete ("✅ Fixes pushed. Please re-review.")—so I know the agent is working without polling the branch.

### Story 5: Graceful Degradation
As an operator, I want the watcher to pause auto-fixes for a PR if it hits round/cost limits or consecutive failures, and post a comment explaining why—so humans can take over without confusion.

## 4. Functional Requirements

### FR1: CLI Command
1. `colonyos watch-github` — Long-running process that polls GitHub API for PR review events.
2. `colonyos watch-github --poll-interval 30` — Configure polling frequency (default: 60 seconds).
3. `colonyos watch-github --dry-run` — Log detected events without triggering fixes.

### FR2: Event Detection
1. Poll the GitHub API via `gh api` to fetch `pull_request_review` events where:
   - `action == "submitted"` and `state == "changes_requested"`
   - PR head branch matches `colonyos/*` prefix
   - Event not already processed (deduplication via event ID)
2. Extract review comments with file path, line number, and feedback text.
3. Validate reviewer is in `allowed_reviewers` allowlist (if configured).

### FR3: Fix Pipeline Integration
1. Enqueue a `QueueItem` with `source_type="github_review"` containing:
   - PR number, branch name, review ID, reviewer username
   - Extracted file/line comments formatted as fix prompt
2. Reuse `run_thread_fix()` from `orchestrator.py` for Implement → Verify → Deliver phases.
3. Track fix rounds in `QueueItem.fix_rounds` and halt at `max_fix_rounds_per_pr`.

### FR4: State Persistence
1. Create `GitHubWatchState` dataclass mirroring `SlackWatchState` pattern:
   - `processed_events: dict[str, str]` — event_id → run_id mapping
   - `hourly_trigger_counts`, `aggregate_cost_usd`, `daily_cost_usd`
   - `consecutive_failures`, `pr_fix_costs: dict[int, float]` (per-PR cost tracking)
2. Persist to `cOS_runs/github_watch_state_{watch_id}.json` via atomic write.

### FR5: GitHub Comments
1. Post comment when fix starts: "🔧 Addressing review feedback from @{reviewer}..."
2. Post comment when fix completes: "✅ Fixes pushed ({commit_sha}). Cost: ${cost:.2f}. Please re-review."
3. Post comment when limits hit: "⚠️ Fix round limit reached ({rounds}/{max}). Manual intervention required."

### FR6: Configuration
Add to `.colonyos/config.yaml`:
```yaml
github_watch:
  enabled: true
  trigger_mode: review_request_changes  # MVP: only this mode
  max_fix_rounds_per_pr: 3
  max_fix_cost_per_pr_usd: 10.0
  poll_interval_seconds: 60
  allowed_reviewers: []  # Empty = all repo collaborators allowed
```

### FR7: Rate Limiting & Circuit Breakers
1. Respect `max_runs_per_hour` from existing config.
2. Increment `consecutive_failures` on pipeline errors; pause after 3.
3. Share daily budget pool with Slack watcher (if both run concurrently).

## 5. Non-Goals (Out of Scope for MVP)

1. **Webhook mode** (`--port 8080`) — Adds deployment complexity (HTTPS, signature verification, public endpoint). Poll mode is sufficient for MVP latency requirements.

2. **GitHub Enterprise support** — The `gh` CLI already handles GHE via `GH_HOST` env var. Explicit GHE config/docs are post-launch when a paying customer requests it.

3. **Trigger modes beyond `review_request_changes`** — The `mention` and `all_comments` modes introduce ambiguity and noise. Ship the high-signal trigger first.

4. **Conflict resolution UI** — If two reviewers leave conflicting feedback, the agent attempts a best-effort fix. Sophisticated "ask for clarification" flows are v2.

5. **PR-level dashboard** — No web UI for viewing per-PR cost/round history. Use log files and `cOS_runs/` JSON state for debugging.

## 6. Technical Considerations

### 6.1 Existing Code Reuse

| Component | Location | Reuse Strategy |
|-----------|----------|----------------|
| Fix pipeline | `orchestrator.py:run_thread_fix()` (L1690-1940) | Call directly with GitHub-sourced fix prompt |
| Queue model | `models.py:QueueItem` (L238-335) | Add `source_type="github_review"` |
| Sanitization | `sanitize.py:sanitize_untrusted_content()` | Apply to review comment bodies |
| Watch state | `slack.py:SlackWatchState` (L513-593) | Mirror pattern for `GitHubWatchState` |
| Rate limiting | `slack.py:check_rate_limit()` (L630-634) | Reuse or extract to shared module |
| Git ref validation | `slack.py:is_valid_git_ref()` (L828-841) | Validate PR branch names |

### 6.2 New Components

1. **`github_watcher.py`** — Event polling, detection logic, comment formatting (~400-500 LOC)
2. **`GitHubWatchState`** dataclass — Deduplication, per-PR cost tracking
3. **CLI integration** — `@app.command()` in `cli.py` for `watch-github`
4. **Config extension** — `GitHubWatchConfig` in `config.py`

### 6.3 Security Considerations (Per Staff Security Engineer Review)

- **Reviewer allowlist** — Default to repo collaborators only; explicit allowlist for public repos
- **Branch validation** — Only process `colonyos/*` branches (prevent arbitrary branch manipulation)
- **Content sanitization** — Strip XML tags from review bodies; quote branch names in subprocess calls
- **No webhook mode in MVP** — Avoids HMAC signature verification complexity
- **Separate concern:** Audit log all fix triggers with reviewer username, event ID, and cost

### 6.4 Race Conditions (Per Principal Systems Engineer Review)

- **Concurrent reviewers** — If two reviewers request changes simultaneously, the second event should queue behind the first (serialized via `pipeline_semaphore` pattern)
- **Force-push detection** — Check HEAD SHA before and after checkout; abort if mismatch (existing pattern in `run_thread_fix` L1810-1819)
- **Edit attacks** — Hash review comment body at detection time; reject re-processing if content changes

### 6.5 Prompt Design (Per Andrej Karpathy Review)

- **Structured fix context** — Format review comments as JSON: `{file_path, line_range, reviewer, feedback, severity}`
- **Confidence threshold** — Triage agent should output confidence score; if <0.7, post clarifying comment instead of attempting fix
- **Conflict handling** — Prompt explicitly states: "If feedback conflicts, propose resolution or ask reviewers"

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Detection latency | <60s from review submission | Log timestamp delta |
| Fix success rate | >80% of attempted fixes pass CI | Track `QueueItem.status` outcomes |
| Cost per fix round | <$3 average | Sum `PhaseResult.cost_usd` |
| False positive rate | <5% (fixes triggered on non-actionable comments) | Manual audit of first 50 fixes |
| Adoption | >10 distinct PRs using watch-github in first month | Count unique `source_type="github_review"` items |

## 8. Open Questions

1. **Triage agent for GitHub?** — Should we run the same Haiku-based triage agent (currently in `slack.py:770-825`) to filter non-actionable comments before attempting fixes? The `review_request_changes` trigger is high-signal, but individual comments within a review may still be vague.

2. **Cross-watcher budget pool** — If both `watch` (Slack) and `watch-github` run concurrently, should they share `daily_budget_usd`? The Principal Systems Engineer recommends yes to prevent attackers from bypassing Slack limits via GitHub.

3. **Reviewer username validation** — How do we validate `allowed_reviewers` are actual GitHub users? The `gh` CLI doesn't provide a "check user exists" command; we may need to allow any string and fail gracefully on invalid usernames.

4. **Edit attack mitigation** — Should we store a hash of the review comment body at detection time and verify it hasn't changed before running the fix? This adds complexity but prevents time-of-check-to-time-of-use attacks.

---

## Appendix: Persona Synthesis

### Areas of Agreement

| Topic | Consensus |
|-------|-----------|
| Poll-only MVP | All 7 personas agree: start poll-only, webhooks add operational complexity for unvalidated feature |
| `review_request_changes` first | All agree: highest-signal trigger, other modes introduce noise |
| Shared infrastructure | 6/7 agree: reuse queue, rate limiting, circuit breakers from Slack watcher |
| GHE follow-on | All agree: ship GitHub.com first, GHE when customer requests |
| Cost caps needed | 6/7 agree: round limits insufficient, add `max_fix_cost_per_pr_usd` |

### Areas of Tension

| Topic | Divergent Views |
|-------|-----------------|
| Feature value | Linus Torvalds questions if users want GitHub iteration vs. Slack (where team already is). Michael Seibel: "solving workflow tax, not core problem" |
| Security severity | Staff Security Engineer warns GitHub comments are "10x attack surface vs Slack" (public repos). Others treat it as incremental risk |
| Triage agent | Andrej Karpathy recommends triage with confidence scoring; Jony Ive prefers relying on `review_request_changes` signal without extra LLM call |
| Code structure | Linus warns codebase is "barely maintainable" at current size; adding watch-github risks pushing it "over the edge" |
