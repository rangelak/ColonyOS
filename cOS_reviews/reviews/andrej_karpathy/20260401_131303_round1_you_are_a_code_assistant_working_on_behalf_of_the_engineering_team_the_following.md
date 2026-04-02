# Review by Andrej Karpathy (Round 1)

## Review Complete — Andrej Karpathy (Round 1)

**VERDICT: approve** ✅

### Summary

This is a textbook prompt-program mismatch fix, done correctly. The learn agent's instructions told it to "read all review artifacts recursively" but never told it which tools were available — so it naturally reached for `Bash` and `Agent`, both disallowed, causing 100% crash rate.

### Key findings:

1. **All 5 functional requirements implemented.** Available Tools section, concrete Glob patterns, negative constraint with consequence, regression tests, all tests passing.

2. **The fix is exactly right-sized**: 11 lines changed in `learn.md`, 25 lines of regression tests. No scope creep into orchestrator, agent, or learnings code.

3. **Good prompt engineering.** The negative constraint says "will cause a fatal error" — models comply better with constraints that explain consequences vs. bare prohibitions. The `{reviews_dir}/**/*.md` Glob pattern gives the agent a copy-pasteable tool call rather than an abstract description.

4. **Tests are appropriately scoped** as static prompt checks (no LLM needed). They catch both removal of the tool-constraint section and removal of the negative constraint.

5. **Minor non-blocking note**: test assertions are slightly loose (`"read" in system_lower` matches any context), but sufficient for regression detection since removing the Available Tools section would also remove the negative constraint that the other assertions check.

Review artifact written to `cOS_reviews/reviews/andrej_karpathy/20260401_130207_round1_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`.
