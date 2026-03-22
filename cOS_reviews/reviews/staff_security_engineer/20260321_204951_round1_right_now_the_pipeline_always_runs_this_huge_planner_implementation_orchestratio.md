# Review by Staff Security Engineer (Round 1)

Now I have a thorough understanding of the implementation. Let me produce my review.

---

## Security Review: Intent Router Agent Implementation

**Reviewer**: Staff Security Engineer

### Assessment

I've reviewed all changed files across this branch: `router.py` (new, 429 lines), `cli.py` (+155 lines), `config.py` (+86 lines), `models.py` (+1 line), `slack.py` (+81 lines), `instructions/qa.md` (new, 77 lines), plus comprehensive test coverage in `test_router.py` (878 lines), `test_config.py` (+216 lines), and `test_models.py` (+53 lines). All 225 tests in the relevant test files pass; the single test failure (`test_default_port`) is pre-existing on main.

### Security Strengths

1. **Least privilege is well-enforced**. The router classifier runs with `allowed_tools=[]` (zero tools) and the Q&A agent runs with `allowed_tools=["Read", "Glob", "Grep"]` (read-only). This is the correct two-tier privilege architecture — classification gets no blast radius, and Q&A gets read-only access.

2. **Input sanitization is consistent**. All three entry points (router prompt, Q&A prompt, audit log) pass user input through `sanitize_untrusted_content()`, which strips XML-like tags to reduce prompt injection surface. The existing sanitizer also handles secret patterns.

3. **Fail-open defaults are correct from a safety perspective**. When confidence is below threshold or parsing fails, the router defaults to `CODE_CHANGE` (full pipeline), which is the safer path since it gets full human review via the PR flow.

4. **Audit trail is implemented**. Every routing decision is logged to `.colonyos/runs/triage_<timestamp>.json` with sanitized prompt, classification, confidence, reasoning, source, and timestamp. This enables post-hoc security review of what the agent decided.

5. **The `--no-triage` bypass is properly scoped**. It only skips routing and goes to the full pipeline — it doesn't skip security controls. The bypass conditions are sensible (`--from-prd`, `--issue`, etc. skip routing since those have explicit intent).

6. **Budget caps are tight**. Router: $0.05. Q&A: $0.50 (configurable). These prevent runaway cost even if something goes wrong.

### Security Concerns (Minor)

1. **Timestamp collision in audit logs**. `log_router_decision` uses `%Y%m%d_%H%M%S` granularity. Two rapid calls within the same second would overwrite one log entry. This is a minor data integrity concern for the audit trail — consider adding a random suffix or microseconds.

2. **Q&A instruction template is loaded from disk at runtime** (`_QA_TEMPLATE_PATH`). While this is the project's established pattern, note that if an attacker can write to the `instructions/` directory, they could modify the Q&A agent's system prompt. This is mitigated by the fact that the Q&A agent still only has read-only tools, limiting exfiltration to stdout output. Acceptable risk given the existing codebase patterns.

3. **Slack integration maps QUESTION to `actionable=False`** without spawning the Q&A agent. This means Slack questions currently get rejected rather than answered. This is a functional gap but not a security issue — it's fail-safe behavior.

### Completeness Check

| PRD Requirement | Status |
|---|---|
| FR-1: Intent Classification (4 categories) | ✅ Implemented |
| FR-2: Reuse Slack Triage | ✅ Shared router, backward-compat mapping |
| FR-3: Two-stage Q&A | ✅ Router → Q&A agent with read-only tools |
| FR-4: Entry points (run + REPL + Slack) | ✅ All three integrated |
| FR-5: Fail-open at <0.7 confidence | ✅ Implemented with logging |
| FR-6: `--no-triage` flag | ✅ Added to `colonyos run` |
| FR-7: Config in `.colonyos/config.yaml` | ✅ `RouterConfig` with all fields |
| FR-8: Audit logging | ✅ JSON logs with sanitized prompts |

---

VERDICT: approve

FINDINGS:
- [src/colonyos/router.py:404]: Timestamp-based audit log filename uses second-level granularity (`%Y%m%d_%H%M%S`), which could silently overwrite entries during rapid successive calls. Consider adding microseconds or a short random suffix.
- [src/colonyos/router.py:28]: Q&A instruction template loaded from disk at runtime — if an attacker gains write access to `instructions/qa.md`, they could influence the Q&A agent's system prompt. Mitigated by read-only tool restriction, but worth noting for defense-in-depth.
- [src/colonyos/slack.py:830]: Slack integration maps QUESTION category to `actionable=False` but does not spawn a Q&A agent to answer the question. This is a functional gap (Slack users asking questions get no answer), but it's fail-safe from a security perspective.

SYNTHESIS:
From a security standpoint, this implementation is well-designed. The two-tier privilege model (zero-tools for classification, read-only for Q&A) correctly applies the principle of least privilege. Input sanitization is consistently applied across all code paths. The audit trail provides the visibility needed for post-hoc security review. The fail-open behavior is the right default — when uncertain, the system routes to the full pipeline with its existing review controls rather than silently answering with a less-supervised agent. The budget caps on both tiers prevent cost-based denial-of-wallet attacks. The minor findings are all low-severity and don't warrant blocking this change. This is a clean, security-conscious implementation that correctly isolates the new Q&A agent's capabilities while maintaining full audit visibility.