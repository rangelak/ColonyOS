# Task Review: - [x] 4.0 Implement `_build_fix_prompt()` function

## Review Complete: Task 4.0 -- `_build_fix_prompt()`

### Consolidated Verdict: **REQUEST-CHANGES**

**Vote split:** 3 approve / 4 request-changes

### Critical Finding (Unanimous across all 7 reviewers)

**`str.format()` will crash on real-world `decision_text` containing curly braces.** Since `decision_text` is LLM-generated output that routinely contains JSON, Python dicts, and code fences, this is a realistic runtime crash — not theoretical. The pipeline would have already consumed significant budget on prior phases before hitting this crash during prompt construction.

### Required Changes

1. **Escape curly braces in `decision_text`** before passing to `.format()`:
   ```python
   safe_decision_text = decision_text.replace("{", "{{").replace("}", "}}")
   ```

2. **Add a test for curly-brace decision text** to prevent regression.

### Recommended (Non-Blocking)

- Explicitly pass `allowed_tools` for the fix phase invocation (security hardening)
- Document the `reviews_dir` parameter deviation from the PRD
- Add fix prompt audit trail for forensics

The review document has been saved to:
`cOS_reviews/20260317_130242_review_task4_build_fix_prompt.md`
