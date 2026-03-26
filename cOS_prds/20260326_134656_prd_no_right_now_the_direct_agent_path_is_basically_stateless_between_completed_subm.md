# PRD: Direct-Agent Conversational State Persistence

## Introduction/Overview

When a user interacts with ColonyOS through the TUI in direct-agent mode, each completed run is fully stateless. If the agent asks "Would you like me to commit and push this fix?" and the user responds "yes", that "yes" is treated as a brand-new, contextless request — the agent has no idea what "yes" refers to.

This is because `_run_direct_agent()` in `src/colonyos/cli.py` creates a completely fresh agent session each time via `run_phase_sync()`, passing only the new user text through `build_direct_agent_prompt()`. No prior conversation history is carried forward.

The Claude Agent SDK already supports session resumption via `ClaudeAgentOptions.resume` (accepts a `session_id` string) and `continue_conversation: bool`. The `ResultMessage` already returns a `session_id` that is stored in `PhaseResult` but currently only used for audit. This feature will wire that session ID back into subsequent direct-agent calls to enable natural conversational continuity.

## Goals

1. **Conversational continuity**: Follow-up messages like "yes", "do it", "commit that" resolve correctly against the prior direct-agent exchange
2. **Zero-config**: Works automatically — no user action required to "enable" conversation mode
3. **Explicit reset**: Users can start a fresh conversation via a `/new` command
4. **Minimal complexity**: Use the SDK's native `resume` mechanism rather than building custom transcript replay

## User Stories

1. **Follow-up confirmation**: User asks the agent to fix a bug. Agent fixes it and asks "Want me to commit?" User types "yes" → agent commits (instead of saying "I don't know what you mean")
2. **Iterative refinement**: User asks for a function. Agent writes it. User says "add error handling" → agent modifies the same function with full context of what it just wrote
3. **Explicit fresh start**: User finishes a conversation about feature A, types `/new`, then starts asking about feature B with no stale context
4. **Mode transition**: User has a direct-agent conversation, then submits a complex prompt that routes to plan+implement → pipeline starts clean without stale chat context

## Functional Requirements

1. **FR-1**: `run_phase()` and `run_phase_sync()` in `src/colonyos/agent.py` must accept an optional `resume: str | None` parameter and pass it to `ClaudeAgentOptions`
2. **FR-2**: `_run_direct_agent()` in `src/colonyos/cli.py` must accept an optional `resume_session_id: str | None` parameter and pass it through to `run_phase_sync()`, and must return the `session_id` from the result (not just `bool`)
3. **FR-3**: The `_run_callback()` closure in `_launch_tui()` must maintain a `last_direct_session_id: str | None` state variable across runs. After a successful direct-agent run, store the returned session ID. Before the next direct-agent run, pass it as `resume_session_id`
4. **FR-4**: When the routed mode is anything other than `direct_agent`, clear `last_direct_session_id` so pipeline runs start clean
5. **FR-5**: Add `/new` to `_SAFE_TUI_COMMANDS` and handle it in `_handle_tui_command()` — it clears `last_direct_session_id` and emits a confirmation message
6. **FR-6**: When resuming a session, emit a brief "Continuing conversation..." indicator in the TUI transcript before the phase header
7. **FR-7**: On resume failure (e.g., expired/invalid session), fall back gracefully to a fresh session with no error shown to user — just start clean

## Non-Goals

- **Cross-restart persistence**: Session state does not survive TUI process restart. A fresh TUI launch = fresh conversation. (Can be added later.)
- **Cross-mode context**: Direct-agent conversation history is NOT carried into plan+implement, review, or other pipeline modes
- **Custom transcript replay**: We will NOT build our own transcript serialization/replay. The SDK's `resume` handles this natively
- **Follow-up detection heuristics**: We will NOT build a classifier to distinguish "follow-up" from "new request". Instead, always resume when a session exists — the model handles irrelevant prior context gracefully. `/new` is the explicit escape hatch
- **Conversation summarization or compaction**: The SDK handles context compaction internally via `PreCompactHookInput`

## Technical Considerations

### SDK Mechanism
- `ClaudeAgentOptions.resume: str | None` (line 1044 of `claude_agent_sdk/types.py`) accepts a session_id to resume
- `ClaudeAgentOptions.continue_conversation: bool` (line 1043) — set to `True` when resuming
- `ResultMessage.session_id` is already captured in `PhaseResult.session_id` (line 196 of `agent.py`)
- The SDK persists session transcripts as JSONL in `~/.claude/projects/` and handles rehydration

### Architecture Changes
- **`src/colonyos/agent.py`**: Add `resume` parameter to `run_phase()` / `run_phase_sync()`, thread it into `ClaudeAgentOptions`
- **`src/colonyos/cli.py`**:
  - `_run_direct_agent()` returns `PhaseResult` (or at minimum `session_id`) instead of `bool`
  - `_run_callback()` closure gets `last_direct_session_id` nonlocal variable
  - `/new` command handler added
- **`src/colonyos/tui/app.py`**: No changes needed — the state lives in the `_launch_tui()` closure, not in the app
- **`src/colonyos/tui/adapter.py`**: No changes needed

### Risk: Return Type Change
`_run_direct_agent()` currently returns `bool`. Changing to return `PhaseResult` or a richer type affects callers. The TUI callback at line 4904 ignores the return value, and the CLI REPL at line ~830 checks truthiness. Both are safe to update.

### Persona Consensus & Tensions

**Strong consensus across all 7 personas:**
- In-memory only (no disk persistence for v1)
- No cross-mode context carry-forward
- Add `/new` command for explicit reset
- Subtle "Continuing conversation..." UX indicator

**Key tension — SDK resume vs. context replay:**
- **Steve Jobs, Linus Torvalds, Karpathy**: Use SDK's native `resume` — it's simpler, the infrastructure exists, don't reinvent it
- **Michael Seibel, Jony Ive, Systems Engineer**: Prefer context replay for more control and debuggability
- **Security Engineer**: Prefers replay (for sanitization chokepoint) but acknowledges SDK resume is safe since transcripts are user-owned

**Resolution**: Use SDK `resume`. It's simpler (3 lines of real logic per Steve Jobs), the SDK handles compaction, and the security boundary is equivalent since transcripts live in `~/.claude/projects/` with user permissions. If `resume` fails for any reason, fall back to a fresh session.

## Success Metrics

1. **Primary**: User types a follow-up like "yes" or "do it" after a direct-agent run → agent correctly resolves the anaphoric reference and takes the expected action
2. **Regression**: Existing direct-agent flows (fresh requests, slash commands, mode routing) continue to work unchanged
3. **Graceful degradation**: If session resume fails, user sees no error — just a fresh session start

## Open Questions

1. **Should `Ctrl+L` (clear transcript) also clear conversation state?** Current lean: No — `Ctrl+L` clears the visual transcript only, `/new` clears both. These are distinct operations.
2. **Max conversation depth**: Should we cap the number of resumed turns (e.g., after 10 follow-ups, force a fresh session)? The SDK handles compaction, so this may be unnecessary. Start without a cap, add if needed.
3. **CLI REPL**: The non-TUI REPL loop (around line 830 of `cli.py`) has the same statelessness problem. Should this be fixed simultaneously? Current lean: Yes, same pattern applies — store `last_direct_session_id` in the REPL loop closure.
