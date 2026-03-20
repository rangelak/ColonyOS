# PRD: GitHub PR Review Comment Response Integration

## Introduction/Overview

This feature adds a `colonyos pr-respond <pr-number>` CLI command and extends `colonyos watch` to monitor GitHub PR review comments and automatically address reviewer feedback. When a human reviewer leaves a comment on a ColonyOS-generated PR, the system fetches unaddressed comments, runs a fix agent to address them, pushes commits, and replies to each comment with what was done.

This closes the feedback loop where ColonyOS already creates PRs autonomously. Currently, after a reviewer comments, developers must context-switch to manually address feedback or craft new prompts. This feature enables ColonyOS to iterate on its own work based on human review, maintaining the autonomous workflow from initial implementation through final approval.

## Goals

1. **Reduce reviewer wait time**: Automatically address PR review comments without requiring developer intervention
2. **Maintain code quality**: Use the same fix pipeline quality (Sonnet/Opus models) as existing review/fix loops
3. **Preserve audit trail**: Track all comment responses in run logs for cost accounting and debugging
4. **Ensure safety**: Apply same security controls as Slack integration (allowlists, sanitization, rate limits)
5. **Integrate seamlessly**: Work with existing `colonyos stats`, `colonyos show`, and queue infrastructure

## User Stories

1. **Solo Developer**: "I wake up to find a reviewer left 3 comments on my ColonyOS-generated PR. I run `colonyos pr-respond 42` and come back to find all comments addressed with commits pushed and replies posted."

2. **Small Team**: "Our team uses `colonyos watch --github` to monitor our ColonyOS PRs. When a teammate reviews and comments, the system automatically addresses feedback overnight, ready for re-review in the morning."

3. **Reviewer**: "I leave a comment saying 'please extract this into a helper function' on a ColonyOS PR. Within 10 minutes, I get a threaded reply explaining the change and a new commit on the branch."

4. **Security-conscious Org**: "Only comments from our allowlisted reviewers trigger automatic fixes. External contributors' comments are ignored to prevent prompt injection attacks."

## Functional Requirements

### CLI Command: `colonyos pr-respond`

1. **FR-1**: `colonyos pr-respond <pr-number>` fetches all unaddressed review comments from the specified PR via `gh api`
2. **FR-2**: `colonyos pr-respond <pr-number> --dry-run` displays what would be addressed without making changes
3. **FR-3**: `colonyos pr-respond <pr-number> --comment-id <id>` addresses only a specific review comment
4. **FR-4**: Unaddressed comments are identified by checking if ColonyOS has already replied (via a marker in reply text or bot user check)
5. **FR-5**: Comments within 10 lines of each other in the same file are grouped into a single fix batch
6. **FR-6**: Each fix batch runs through the thread-fix pipeline (`Implement → Verify → Deliver`)
7. **FR-7**: After successful fix, a threaded reply is posted to each addressed comment summarizing the changes
8. **FR-8**: After failed fix, a user-friendly reply is posted suggesting manual review (no internal errors exposed)
9. **FR-9**: The command validates the PR is on a `colonyos/` branch (or configured prefix) before proceeding
10. **FR-10**: Bot account comments are skipped by default (check `author.type == "Bot"`)

### GitHub Watch Mode: `colonyos watch --github`

11. **FR-11**: `colonyos watch --github` polls for new review comments on open PRs created by ColonyOS
12. **FR-12**: Auto-detect ColonyOS PRs via branch prefix (`colonyos/`) or PR body marker
13. **FR-13**: Poll interval configurable via `github_watch.poll_interval_seconds` (default: 60)
14. **FR-14**: When new review comments are detected, queue them for processing (reuse existing queue infrastructure)
15. **FR-15**: `colonyos watch --github --dry-run` logs triggers without executing fixes
16. **FR-16**: Watch state persisted to `.colonyos/runs/github_watch_state_<id>.json` for resume capability

### Comment Processing

17. **FR-17**: Fetch review comments via `gh api repos/:owner/:repo/pulls/:number/comments`
18. **FR-18**: Parse comment metadata: `id`, `body`, `path`, `line`, `original_line`, `user.login`, `user.type`, `created_at`
19. **FR-19**: Filter to unaddressed comments (ColonyOS has not replied yet)
20. **FR-20**: Sanitize comment content using existing `sanitize_untrusted_content()` from `sanitize.py`
21. **FR-21**: Group adjacent comments (same file, within 10 lines) for batched fixes

### Fix Pipeline

22. **FR-22**: Reuse `run_thread_fix()` pattern from `orchestrator.py` (Implement → Verify → Deliver, no Plan phase)
23. **FR-23**: Build fix context from: comment text, file path, line range, original PR description
24. **FR-24**: Inject relevant PRD/task file context if available from original run log
25. **FR-25**: Use model tier from `config.get_model(Phase.FIX)` (default: Sonnet)
26. **FR-26**: Push commits to existing branch (skip PR creation, reuse `skip_pr_creation=True` pattern)

### Response Flow

27. **FR-27**: Post replies using `gh api repos/:owner/:repo/pulls/comments/:id/replies`
28. **FR-28**: Success reply template: "Addressed in commit `<sha>`: <summary of changes>"
29. **FR-29**: Failure reply template: "I wasn't able to address this automatically. Manual review needed. See run: `<run_id>`"
30. **FR-30**: Response includes ColonyOS marker for deduplication (e.g., `<!-- colonyos-response -->`)

### Configuration

31. **FR-31**: New `github_watch` config section in `.colonyos/config.yaml`:
```yaml
github_watch:
  enabled: false
  poll_interval_seconds: 60
  auto_respond: false          # require explicit trigger vs auto-fix
  max_responses_per_pr_per_hour: 3
  budget_per_response: 5.0     # USD cap per response round
  allowed_comment_authors: []  # empty = org members only
  skip_bot_comments: true
  comment_response_marker: "<!-- colonyos-response -->"
```
32. **FR-32**: `allowed_comment_authors` allowlist controls who can trigger fixes (empty = check org membership via `gh api`)
33. **FR-33**: `max_responses_per_pr_per_hour` rate limit with per-PR tracking

### Safety Guards

34. **FR-34**: Only process PRs on `colonyos/` branches (or configured `branch_prefix`)
35. **FR-35**: Rate limit: max N responses per hour per PR (default: 3)
36. **FR-36**: Budget cap per response round respects `config.budget.per_run`
37. **FR-37**: Skip comments from bot accounts by default (`skip_bot_comments: true`)
38. **FR-38**: Require comment author to be in allowlist or org member
39. **FR-39**: Validate HEAD SHA before fix to detect force-push tampering (reuse `expected_head_sha` pattern from `run_thread_fix`)

### Output & Observability

40. **FR-40**: Each response round creates a `RunLog` with `source_type: "pr_comment"`
41. **FR-41**: `QueueItem` tracks: `pr_number`, `comment_ids`, `pr_url` in metadata
42. **FR-42**: Run logs appear in `colonyos stats` and `colonyos show` like other source types
43. **FR-43**: Watch state persisted with hourly rate limit counters (reuse `SlackWatchState` pattern)

## Non-Goals

- **Semantic comment grouping**: No ML/embedding-based grouping of "related" comments across files. Simple line-range adjacency only.
- **Bot comment handling**: No special handling for Dependabot, CodeQL, or other automation comments (skip them entirely)
- **Webhook mode**: No GitHub webhook receiver - polling only for MVP
- **PR creation from comments**: Comments on non-ColonyOS PRs are ignored (no new PR creation flow)
- **Comment approval workflow**: No human-in-the-loop approval before fixing (use `auto_respond: false` to require explicit CLI trigger)
- **Multi-repo watching**: Watch mode operates on single repo only (current working directory)

## Technical Considerations

### Existing Infrastructure to Reuse

| Component | Location | Reuse Pattern |
|-----------|----------|---------------|
| PR check fetching | `ci.py:fetch_pr_checks()` | Adapt for comment fetching |
| Content sanitization | `sanitize.py:sanitize_untrusted_content()` | Direct reuse |
| Thread-fix pipeline | `orchestrator.py:run_thread_fix()` | Direct reuse |
| Watch state persistence | `slack.py:SlackWatchState` | Adapt for GitHub |
| Rate limiting | `slack.py:check_rate_limit()` | Adapt for per-PR limits |
| Queue infrastructure | `models.py:QueueItem`, `cli.py:queue` | Add `source_type: "pr_comment"` |
| Allowlist pattern | `config.py:SlackConfig.allowed_user_ids` | Mirror for GitHub |

### New Files to Create

| File | Purpose |
|------|---------|
| `src/colonyos/pr_comments.py` | PR comment fetching, parsing, grouping, reply posting |
| `src/colonyos/instructions/pr_comment_fix.md` | Instruction template for PR comment fix agent |
| `tests/test_pr_comments.py` | Unit tests for comment processing |

### Files to Modify

| File | Changes |
|------|---------|
| `cli.py` | Add `pr-respond` command, extend `watch` with `--github` flag |
| `config.py` | Add `GitHubWatchConfig` dataclass, parsing logic |
| `models.py` | Add `source_type: "pr_comment"` to QueueItem schema (bump `SCHEMA_VERSION`) |
| `orchestrator.py` | Add `run_pr_comment_fix()` wrapper around `run_thread_fix()` |

### API Calls Required

1. `gh api repos/:owner/:repo/pulls/:number/comments` - Fetch review comments
2. `gh api repos/:owner/:repo/pulls/:number` - Get PR metadata (branch, author)
3. `gh api repos/:owner/:repo/pulls/comments/:id/replies -X POST` - Post reply
4. `gh api repos/:owner/:repo/collaborators/:username` - Validate org membership
5. `gh api user` - Get authenticated user for bot detection

### Security Considerations

- PR comments are untrusted input flowing into `bypassPermissions` agent sessions
- Apply `sanitize_untrusted_content()` at point of use (defense-in-depth)
- Allowlist comment authors to prevent external prompt injection
- Never expose internal errors in PR comment replies
- Validate file paths from comments against repo root (prevent path traversal)

## Success Metrics

1. **Adoption**: >50% of ColonyOS PR runs that receive review comments also have `pr-respond` triggered within 24 hours
2. **Fix Success Rate**: >70% of PR comment fix attempts result in successful commits pushed
3. **Time Savings**: Average time from review comment to fix commit <10 minutes (vs manual ~20 minutes)
4. **Cost Efficiency**: Average cost per comment response <$2.00 USD
5. **Safety**: Zero prompt injection incidents from PR comment content

## Open Questions

1. **Org membership check caching**: Should org membership checks be cached to avoid API rate limits, or always fresh?
   - *Recommendation*: Cache for 1 hour, store in watch state

2. **Multiple reviewers commenting simultaneously**: How to handle race conditions when multiple reviewers comment at once?
   - *Recommendation*: Process comments in order received, rate limit naturally throttles

3. **Comment threading depth**: Should ColonyOS respond to replies on its own responses?
   - *Recommendation*: No, only top-level review comments to avoid conversation loops

4. **Integration with existing Slack watch**: Should `colonyos watch` support both `--slack` and `--github` simultaneously?
   - *Recommendation*: Yes, single watch process can monitor both with combined state

---

## Persona Q&A Synthesis

### Areas of Strong Agreement

All personas agreed on:
- **CLI-first MVP**: Ship `pr-respond` command before watch mode integration
- **Reuse infrastructure**: Use existing `run_thread_fix`, `sanitize_untrusted_content`, and rate limiting patterns
- **Full run logs**: PR comment responses should be full `RunLog` entries, not lightweight types
- **Quality over speed**: Use Sonnet/Opus models, not Haiku, for review comment fixes
- **Skip all bots**: Default to skipping all bot comments, no special handling for Dependabot/CodeQL
- **Allowlist comment authors**: Security boundary is who can inject text into prompts
- **User-friendly failure responses**: Don't expose internal errors in PR comments

### Areas of Tension

| Topic | Tension | Resolution |
|-------|---------|------------|
| Watch mode priority | Some said CLI-only MVP, others said watch is essential | Ship CLI first, watch as fast-follow |
| Comment grouping | Simple adjacency vs semantic understanding | Start with 10-line adjacency, measure, iterate |
| Allowlist scope | Comment author only vs both PR author + comment author | Comment author primary, warn on external PR authors |
| Rate limit default | 2-5 responses per hour per PR | Default to 3, configurable |

### Key Security Insights (Staff Security Engineer)

- PR comments have higher tampering risk than CI logs (user-authored vs server-generated)
- Need comment-author allowlist + org membership check
- Validate file paths in comments to prevent path traversal
- Never reflect raw errors to PR comments (prompt injection via error reflection)
- Per-PR rate limits prevent single noisy PR from monopolizing resources

### Key AI/Prompt Insights (Andrej Karpathy)

- PR comments are unstructured human feedback, not structured error logs
- The prompt must teach the model to interpret conversational critique as actionable fixes
- Don't burn tokens on pre-fix clustering - the model can synthesize multiple comments in context
- Haiku is too weak for instruction-following on untrusted input; use Sonnet minimum
