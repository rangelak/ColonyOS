# Security Review — Round 3: TUI-Native Auto Mode

**Reviewer**: Staff Security Engineer
**Branch**: `colonyos/add_support_for_auto_inside_the_tui_the_tui_should_be_the_default_colonyos_exper`
**Date**: 2026-03-27

---

## Summary

Round 2's critical findings (uncapped budget, dead TranscriptLogWriter, missing gitignore) have all been fixed. The implementation is now substantially more secure. 96 tests pass. One medium-severity sanitization gap remains.

## Findings

### MEDIUM: Custom CEO profiles bypass `sanitize_display_text` in config loading path

**File**: `src/colonyos/config.py:701`

The config loader parses `ceo_profiles` via `_parse_personas()`, which creates `Persona` objects directly without sanitization:

```python
ceo_profiles=_parse_personas(raw.get("ceo_profiles", [])),
```

Meanwhile, `parse_custom_ceo_profiles()` in `ceo_profiles.py` (lines 90-106) exists and correctly applies `sanitize_display_text` to all fields — but it's **never called** from `load_config()`. This means user-defined CEO profiles in `.colonyos/config.yaml` flow unsanitized into the CEO system prompt via `_build_ceo_prompt`.

**Risk**: A malicious PR modifying `.colonyos/config.yaml` could inject arbitrary prompt content through CEO profile fields (`role`, `expertise`, `perspective`). While the config file is typically under repo-owner control, supply-chain scenarios (fork PRs, shared monorepos) make this worth fixing.

**Fix**: Replace `_parse_personas(raw.get("ceo_profiles", []))` with `parse_custom_ceo_profiles(raw.get("ceo_profiles", []))` in `load_config()`. ~1 line change.

### Previously Fixed (Verified)

| Finding | Status |
|---------|--------|
| Budget/time caps not enforced in TUI auto path | **Fixed** — three checkpoint locations (pre-iteration, post-CEO, post-pipeline) |
| `.colonyos/logs/` not in `.gitignore` | **Fixed** — added to `entries_needed` in `init.py` |
| TranscriptLogWriter never instantiated | **Fixed** — created in `_launch_tui()`, passed to `AssistantApp`, wired into all queue consumer branches |
| Transcript export default permissions | **Fixed** — uses `os.open()` with `0o600` |
| Two-tier Ctrl+C broken | **Fixed** — first press no longer calls `self.exit()` |
| Custom CEO profiles not passed to `get_ceo_profile` | **Fixed** — `config.ceo_profiles` passed as `custom_profiles` |
| `--persona` flag not parsed | **Fixed** — parsed from tokens, passed to `get_ceo_profile(name=...)` |
| Concurrent auto loop guard | **Fixed** — `_auto_loop_active` checked before starting |
| LogWriter cleanup on unmount | **Fixed** — `on_unmount` calls `log_writer.close()` |

### What's Solid

- **`auto_approve` guard preserved**: Auto mode in TUI still requires explicit opt-in (`auto_approve: true` or `--no-confirm`). No bypass path.
- **SECRET_PATTERNS redaction**: Applied in `TranscriptLogWriter.write_line()` before every disk write. Covers GitHub PATs, OpenAI keys, AWS keys, etc.
- **File permissions**: Both `TranscriptLogWriter` and `action_export_transcript` use `os.open()` with `0o600`. Log files are not world-readable.
- **Log rotation**: `max_log_files` (default 50) with oldest-first deletion prevents unbounded disk growth.
- **ANSI stripping**: `_ANSI_RE` applied to all log output. Logs are clean plain text.
- **Budget enforcement**: Three-checkpoint model in `_run_auto_in_tui` (pre-iteration, post-CEO, post-pipeline) with config fallbacks. No path to uncapped spend.
- **Stop event checked between phases**: `_stop_event.is_set()` checked before CEO phase and before orchestrator phase. No mid-API-call cancellation.
- **Built-in profiles are safe**: The 8 hardcoded CEO profiles contain no injection vectors — they're static strings with genuine strategic perspectives.

### Minor Observations (Non-blocking)

1. **`max_log_files` not bounds-checked**: `int(raw.get("max_log_files", 50))` could be set to 0 or negative in config. Would cause `_rotate_old_logs` to delete all log files immediately. Consider `max(1, ...)`.
2. **Log rotation race**: If two TUI sessions start simultaneously, `_rotate_old_logs` could race. Low probability in practice.
3. **`get_plain_text` creates one `Console` per line**: In `transcript.py:244-249`, each line creates a new `Console(width=200)`. For very long transcripts, this could be slow. Not a security issue, but worth noting.

---

## Checklist Assessment

- [x] All functional requirements implemented (FR-1 through FR-5)
- [x] Tests pass (96/96)
- [x] No secrets or credentials in committed code
- [x] Log files sanitized for secrets before disk write
- [x] File permissions restricted to owner-only
- [x] Budget/time caps enforced in TUI auto path
- [x] `auto_approve` guard preserved
- [x] Two-tier cancellation works correctly
- [x] `.colonyos/logs/` gitignored
- [ ] Custom CEO profiles sanitized through config loading path (**GAP**)
