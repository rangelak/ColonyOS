## Proposal: GitHub Issue as Pipeline Input

### Rationale
ColonyOS currently only accepts free-text prompts as input, which disconnects it from how real teams track work. Allowing `colonyos run --issue <url-or-number>` to consume a GitHub Issue—pulling its title, body, labels, and comments as rich context—bridges ColonyOS into existing developer workflows and makes it immediately useful in any repo with an issue backlog. The deliver phase can then auto-link the PR with "Closes #N", completing the loop.

### Builds Upon
- "Autonomous CEO Stage (`colonyos auto`)" — the CEO could reference open issues for prioritization
- "ColonyOS v2: Clean Slate Build" — extends the core `run` command's input surface
- "Developer Onboarding & Long-Running Autonomous Loops" — doctor already checks for `gh` CLI availability

### Feature Request
Add GitHub Issue integration to ColonyOS so users can point the pipeline at an issue instead of writing a prompt from scratch.

**CLI surface:**
- `colonyos run --issue 42` — accepts an issue number in the current repo
- `colonyos run --issue https://github.com/owner/repo/issues/42` — accepts a full URL
- The `--issue` flag is mutually exclusive with the positional `prompt` argument

**Issue fetching (new module `src/colonyos/github.py`):**
- Use `gh issue view <number> --json title,body,comments,labels,assignees,state` via subprocess to fetch issue data (no new dependencies—`gh` is already a checked prerequisite)
- Parse the JSON response into a dataclass (`GitHubIssue` with `number`, `title`, `body`, `labels`, `comments`)
- Format the issue into a rich prompt that includes the title, full body, label context, and a summary of comment discussion (if any)

**Plan phase enhancement:**
- When an issue is the source, inject the issue number and URL into the plan prompt so the PRD references it
- The generated PRD should include a `## Source Issue` section linking back to the GitHub issue

**Deliver phase enhancement:**
- When the run was triggered by an issue, the PR body should include `Closes #N` to auto-close the issue on merge
- The PR body should also reference the issue number in its summary section

**Run log tracking:**
- Add an optional `source_issue: int | None` field to `RunLog` so runs triggered by issues are traceable
- The `colonyos status` output should show the source issue number when present

**CEO integration (lightweight):**
- Add a helper `fetch_open_issues()` that returns titles + numbers of open issues (limit 20)
- Inject this list into the CEO prompt so it can reference existing issues in its rationale (e.g., "This addresses issue #15")
- The CEO can optionally output `Issue: #N` in its proposal to signal it's addressing an existing issue

**Acceptance criteria:**
1. `colonyos run --issue 42` fetches the issue, builds a prompt, and runs the full pipeline
2. `colonyos run --issue https://github.com/org/repo/issues/42` works with full URLs
3. The generated PR body contains `Closes #42` when triggered by an issue
4. `colonyos status` shows the source issue number for issue-triggered runs
5. The CEO prompt includes a list of open issues when available
6. Unit tests cover issue parsing, prompt building, URL/number extraction, and the mutually-exclusive flag validation
7. Graceful error handling when `gh` is not authenticated or the issue doesn't exist