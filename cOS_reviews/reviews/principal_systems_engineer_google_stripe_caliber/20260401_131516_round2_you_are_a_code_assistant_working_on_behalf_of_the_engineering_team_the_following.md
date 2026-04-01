# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: Clean, correctly-scoped fix. Tool constraints, concrete Glob patterns, and negative constraint with consequence explanation. Exactly the right 12 lines to add.
- [tests/test_orchestrator.py]: Two regression tests cover the critical invariants. Individual assertions on "read"/"glob" are loose but collectively sufficient when combined with "bash" and negative-constraint checks. Non-blocking.
- [cOS_tasks/20260401_130207_tasks_...]: All tasks marked complete with dependency tracking.
- [src/colonyos/orchestrator.py]: Correctly left unchanged — enforcement layer was never the problem.

SYNTHESIS:
This is a textbook prompt-program contract fix, executed with surgical precision. The root cause — instruction-template telling an agent to "read recursively" without communicating available tools — is correctly addressed at the instruction layer, preserving the enforcement layer unchanged. The fix adds exactly two things: (1) tell the agent what tools it has, with copy-pasteable examples, and (2) tell it what tools it doesn't have, with consequences. The regression tests are appropriately scoped as static prompt-content checks (no LLM needed, fast, deterministic). From an operational perspective, this takes the learn phase from 0% success rate to near-100% with zero blast radius. Defense in depth is now two-layered: prompt prevents the attempt, `allowed_tools` enforcement catches any mistakes. Ship it.