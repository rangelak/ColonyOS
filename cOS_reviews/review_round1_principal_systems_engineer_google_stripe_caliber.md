# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

The standalone review path uses `_build_standalone_fix_prompt` (no learnings injection), while the main pipeline uses `_build_fix_prompt` (with learnings injection). This is consistent — PRD FR-8 only calls for learnings in the main pipeline's fix prompt, and the standalone review is a separate feature.

Now I have a comprehensive picture. Here's my review:

---

VERDICT: approve

FINDINGS:
- [src/colonyos/learnings.py]: `prune_ledger` signature deviates from PRD FR-4 spec (`content: str, max_entries: int` → returns `str`) instead of `(repo_root: Path, max_entries: int) -> None`. This is actually a *better* design — it's a pure function operating on content, called internally by `append_learnings` which handles file I/O. The PRD's in-place mutation API would have been harder to test and compose. Acceptable deviation.
- [src/colonyos/learnings.py]: `parse_learnings` return type is `list[tuple[str, str, str, list[LearningEntry]]]` rather than the PRD's `list[LearningEntry]`. This is a richer return that the module needs internally. The PRD's simpler signature was an API sketch; the actual API serves its consumers correctly.
- [src/colonyos/instructions/learn.md]: The output format example is wrapped in a markdown code block (triple backticks). The `_parse_learn_output` regex in `orchestrator.py` matches `- **[category]** text` lines and will correctly parse the output regardless of whether the agent outputs inside or outside a code fence. However, some LLMs may emit the backtick fences literally — this would cause the regex to fail. Low risk given the explicit "Output ONLY" instruction, but worth noting.
- [src/colonyos/orchestrator.py]: `_build_learn_prompt` computes `lpath.relative_to(repo_root)` which will raise `ValueError` if `lpath` is not relative to `repo_root`. Since `learnings_path()` always returns `repo_root / ".colonyos" / LEARNINGS_FILE`, this is safe by construction. No issue.
- [src/colonyos/orchestrator.py]: `_run_learn_phase` imports `from datetime import date as date_cls` inside the function body (lazy import). Minor style inconsistency — all other imports are at module level. Not a bug but slightly unconventional.
- [src/colonyos/cli.py]: The `status` command had its early `return` removed (line 740 diff), so it now falls through to display the learnings ledger even when no runs or loop files exist. This is correct — FR-14 says learnings count should always appear.
- [tests/test_orchestrator.py]: The learn phase test coverage is thorough: GO path, NO-GO path, disabled config, failure non-blocking, exception non-blocking, budget validation, read-only tools. All 227 tests pass.
- [src/colonyos/config.py]: `LearningsConfig` follows the exact same `@dataclass` pattern as `BudgetConfig` and `PhasesConfig`. Parsing and serialization are both covered. Clean.
- [src/colonyos/learnings.py]: The deduplication strategy (normalized text comparison in `append_learnings`) plus LLM-prompt-level dedup instruction (FR-6) provides two layers of protection. The code-level dedup is deterministic and reliable.

SYNTHESIS:
This is a clean, well-structured implementation that faithfully delivers all 15 functional requirements from the PRD. The architecture decisions are sound — `learnings.py` is a pure-function module with no side effects except file I/O at the boundary, the learn phase is properly isolated behind a try/except that can never block the pipeline, and the read-only tool restriction (`["Read", "Glob", "Grep"]`) correctly mitigates the stored prompt injection concern. The test coverage is comprehensive with 227 tests passing, covering both happy paths and critical failure modes (learn phase exceptions, budget exhaustion, disabled config). The `prune_ledger` being a pure function on `content: str` rather than the PRD's file-mutating signature is a strictly better design. The only minor concern is the code-block-wrapped output format in `learn.md` which could cause parsing misses if the LLM echoes the backtick fences, but this is a low-probability edge case that would result in zero learnings extracted (not a pipeline failure), consistent with the non-disruptive design goal. No secrets, no destructive operations, no placeholder code. Ship it.