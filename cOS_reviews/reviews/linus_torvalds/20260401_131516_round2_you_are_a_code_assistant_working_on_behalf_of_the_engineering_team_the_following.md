# Review by Linus Torvalds (Round 2)

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: 12 lines added — explicit tool list, concrete Glob pattern with `{reviews_dir}/**/*.md`, negative constraint with consequence explanation. All necessary, nothing superfluous.
- [tests/test_orchestrator.py]: 25 lines of regression tests verifying tool-constraint language and concrete Glob pattern presence. Appropriately scoped as static prompt checks — no LLM needed to run them.
- [cOS_prds/...]: PRD correctly scoped to the root cause. All 5 functional requirements addressed.
- [cOS_tasks/...]: All tasks marked complete. No TODOs remaining.
- No changes to orchestrator.py, agent.py, or learnings.py. No expanded privileges, no new dependencies, no unrelated changes.

SYNTHESIS:
This is the simplest possible fix for a 100% failure rate bug. The prompt told the agent what to do without telling it which tools it had. The agent guessed wrong, crashed, burned the budget on retries. The fix adds 12 lines to the instruction template — an explicit tool list, a copy-pasteable Glob pattern, and a negative constraint that explains the consequence of non-compliance. Two regression tests (25 lines) catch future prompt-tool misalignment. No architectural changes, no privilege escalation, no scope creep. The data structures are unchanged, the enforcement layer is untouched. Show me the data structures and I'll understand the code — and these data structures are exactly right. Ship it.
