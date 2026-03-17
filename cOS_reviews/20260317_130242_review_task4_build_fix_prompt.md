# Review: Task 4.0 -- Implement `_build_fix_prompt()` Function

**Branch:** `colonyos/add_a_review_driven_fix_loop_to_the_orchestrator_pipeline_when_the_decision_gate`
**PRD:** `cOS_prds/20260317_144239_prd_add_a_review_driven_fix_loop_to_the_orchestrator_pipeline_when_the_decision_gate.md`
**Task:** 4.0 Implement `_build_fix_prompt()` function

---

## Consolidated Verdict: **REQUEST-CHANGES**

**Approve:** 3 (YC Partner, Steve Jobs, Karpathy)
**Request Changes:** 4 (Jony Ive, Systems Engineer, Linus Torvalds, Security Engineer)

### Critical Issue (Unanimous)

All seven reviewers identified the same bug: **`str.format()` will crash when `decision_text` contains curly braces.** Since `decision_text` is LLM-generated output that routinely contains JSON, Python dicts, code fences, and format-string-like patterns, this is a realistic runtime crash -- not a theoretical edge case. The fix is trivial (escape braces before interpolation), but blocking.

---

## Review Checklist

### Completeness
- [x] FR-4 functional requirements implemented (function signature, base+fix template, inline decision text, reviews_dir reference)
- [x] Tests present in `TestBuildFixPrompt` class (5 tests)
- [x] No placeholder or TODO code remains
- [ ] **Missing:** Test for curly-brace edge case in `decision_text`

### Quality
- [x] Code follows existing `_build_*_prompt()` conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [ ] **Bug:** `str.format()` crashes on `decision_text` containing `{` or `}`

### Safety
- [x] No secrets or credentials in committed code
- [x] Error handling present in calling code (fix loop)
- [ ] **Risk:** Fix agent runs with `bypassPermissions` + full Bash/Write access (noted by Security Engineer; related to broader architecture, not this function specifically)

---

## Persona Reviews

### 1. YC Partner (Michael Seibel) -- APPROVE

**Findings:**
- `src/colonyos/orchestrator.py`: Signature drops `reviews_dir` param in favor of `config.reviews_dir` -- pragmatic simplification, correct call.
- `src/colonyos/instructions/fix.md`: Well-structured template with scope-limiting rules that prevent agent wandering.
- `tests/test_orchestrator.py`: Five tests covering key behaviors, proportionate to complexity.

**Synthesis:** Clean, minimal implementation that ships the smallest thing that works. The `reviews_dir` parameter simplification is actually better than the PRD spec. Template discipline prevents fix-agent scope creep. Ship it.

---

### 2. Steve Jobs -- APPROVE

**Findings:**
- `src/colonyos/orchestrator.py`: Signature deviation from PRD is the better design -- eliminates a redundant parameter.
- `src/colonyos/orchestrator.py`: Decision text placed in system prompt (not user prompt as PRD states) is a defensible choice -- context belongs in system prompt, action in user prompt.
- `tests/test_orchestrator.py`: `test_includes_reviews_dir` only asserts substring presence without structural context (minor).

**Synthesis:** The function does one thing and does it well. 27 lines. The signature is cleaner than the PRD prescribed. The decision to embed findings in the system prompt keeps the user message focused on the action. You cannot remove anything else from this implementation.

---

### 3. Jony Ive -- REQUEST-CHANGES

**Findings:**
- `src/colonyos/orchestrator.py` (lines 244-251): Signature deviates from PRD without documentation -- creates a silent lie between intent and artifact.
- `src/colonyos/orchestrator.py` (lines 265-269): User prompt duplicates information already in system prompt -- repeating contextual data adds visual mass without informational mass.
- `src/colonyos/instructions/fix.md` (line 15): Hardcodes "NO-GO" as static text when the template already receives `{decision_text}` -- a form of decoration pretending to be structure.
- `tests/test_orchestrator.py`: No test for `decision_text` containing curly braces -- leaves a real failure mode uncovered.

**Synthesis:** Structurally sound but imprecise in its details. Dropping the `reviews_dir` parameter, repeating context in the user prompt, hardcoding "NO-GO", and missing the format-string edge case test are all small acts of imprecision that add up. A short round of targeted fixes would bring this to approval.

---

### 4. Principal Systems Engineer (Google/Stripe caliber) -- REQUEST-CHANGES

**Findings:**
- `src/colonyos/orchestrator.py` (lines 255-263) **[HIGH]**: `str.format()` injection via `decision_text` causes runtime crash. Decision text containing `{something}` will raise `KeyError`. Fix: escape braces or switch to `string.Template`.
- `src/colonyos/orchestrator.py` (line 244) **[MEDIUM]**: PRD signature deviation (`reviews_dir` removed) is undocumented.
- `tests/test_orchestrator.py` **[MEDIUM]**: No test for curly-brace edge case.
- `src/colonyos/orchestrator.py` (lines 244-270) **[LOW]**: No input validation on `fix_iteration` (negative values produce confusing prompts).
- `src/colonyos/orchestrator.py` (lines 255-263) **[LOW]**: Decision text embedded in system prompt, not user prompt as PRD states.

**Synthesis:** Clean implementation with one genuine reliability bug. Using `str.format()` with untrusted LLM-generated `decision_text` is a costly failure mode -- the pipeline has already consumed budget on prior phases and then crashes on prompt construction. The fix is small (escape braces), but it must be done before this ships.

---

### 5. Linus Torvalds -- REQUEST-CHANGES

**Findings:**
- `src/colonyos/orchestrator.py` (lines 255-263) **[HIGH]**: `str.format()` will blow up on real-world decision text. LLM output routinely contains curly braces. This is a "pipeline crashes on the second run" concern, not theoretical.
- `src/colonyos/orchestrator.py` (line 244) **[MEDIUM]**: Signature deviates from PRD without justification in code or comments.
- `tests/test_orchestrator.py` **[LOW]**: No test for curly-brace decision text -- if such a test existed, it would immediately expose the HIGH severity bug.
- `src/colonyos/instructions/fix.md` **[LOW]**: Template content is well-structured, no structural complaints.

**Synthesis:** The function is clean, short, follows the established pattern. Would approve in ten seconds if not for the `str.format()` problem. This is the one parameter in the entire template system that carries arbitrary external text. Fix the templating, add a curly-brace test, and this is ready to merge.

---

### 6. Staff Security Engineer -- REQUEST-CHANGES

**Findings:**
- `src/colonyos/orchestrator.py` (lines 255-263) **[HIGH]**: Prompt injection via `str.format()` on untrusted `decision_text`. Format specifiers like `{branch_name}` in decision text would silently be replaced with actual values, leaking config. `{__class__}` or similar could cause crashes.
- `src/colonyos/orchestrator.py` (lines 669-676) **[HIGH]**: Fix agent runs with `bypassPermissions` and full Bash/Write access with no sandboxing. Combined with prompt injection, this creates a realistic attack chain: malicious content in review artifacts -> decision agent echoes it -> fix agent executes arbitrary commands.
- `tests/test_orchestrator.py` **[MEDIUM]**: No test for format-string injection in `decision_text`.
- `src/colonyos/orchestrator.py` (lines 661-676) **[LOW]**: No audit trail of the actual prompts sent to the fix agent -- no forensic artifact for post-incident analysis.

**Synthesis:** Two compounding high-severity issues: (1) unescaped `decision_text` through `str.format()` creates both crash and info-leak vectors, and (2) the fix agent consuming this prompt runs with unrestricted permissions. Together they form a realistic attack chain. Immediate fixes: escape format specifiers in `decision_text`, explicitly declare and minimize `allowed_tools` for the fix phase, and add audit logging.

---

### 7. Andrej Karpathy -- APPROVE (with strong recommendation)

**Findings:**
- `src/colonyos/orchestrator.py` (lines 255-263) **[MEDIUM]**: `str.format()` will crash on brace-containing decision text. The decision gate template actively encourages fenced code blocks, making this a realistic failure path.
- `src/colonyos/orchestrator.py` (lines 265-269) **[LOW]**: User prompt redundantly repeats context already in system prompt -- mild context window inefficiency.
- `src/colonyos/instructions/fix.md` **[POSITIVE]**: Excellent prompt structure -- four-step process scaffold, inline decision text embedding (eliminates tool-use round trip), behavioral guardrails in Rules section.
- `src/colonyos/instructions/fix.md` **[LOW]**: No explicit instruction for the agent to summarize what was fixed (would help downstream review cycle).
- `tests/test_orchestrator.py` **[MEDIUM]**: No test for brace-containing decision text.

**Synthesis:** Architecturally sound. Inline embedding of decision text is the correct design for minimizing failure modes in a stochastic agent loop. The fix.md template reads like a well-structured program. The one actionable issue is `str.format()` fragility with LLM-generated content. Approving with strong recommendation to address brace-escaping before production.

---

## Required Changes (Before Approval)

### 1. Escape curly braces in `decision_text` before `str.format()` (All 7 reviewers)

**File:** `src/colonyos/orchestrator.py`, lines 255-263

```python
# Before passing to .format(), escape any braces in decision_text
safe_decision_text = decision_text.replace("{", "{{").replace("}", "}}")

system = _format_base(config) + "\n\n" + fix_template.format(
    ...
    decision_text=safe_decision_text,
    ...
)
```

### 2. Add test for curly-brace decision text (6 of 7 reviewers)

**File:** `tests/test_orchestrator.py`, in `TestBuildFixPrompt`

```python
def test_decision_text_with_curly_braces(self):
    config = ColonyConfig(max_fix_iterations=2)
    decision = "Fix the config: {'key': 'value'}\n```\n{bad}\n```"
    system, _ = _build_fix_prompt(
        config, "prd.md", "tasks.md", "branch", decision, 1,
    )
    assert "{'key': 'value'}" in system
```

## Recommended Changes (Non-Blocking)

### 3. Explicitly pass `allowed_tools` for fix phase invocation (Security Engineer)
**File:** `src/colonyos/orchestrator.py`, line 669 -- Make the permission grant auditable rather than relying on defaults.

### 4. Document the `reviews_dir` signature deviation from PRD (Jony Ive, Systems Engineer, Linus Torvalds)
Either update the PRD or add a code comment noting the intentional simplification.

### 5. Consider adding fix prompt audit trail (Security Engineer)
Persist constructed fix prompts to disk as `fix_prompt_iter{N}.md` for post-incident forensics.
