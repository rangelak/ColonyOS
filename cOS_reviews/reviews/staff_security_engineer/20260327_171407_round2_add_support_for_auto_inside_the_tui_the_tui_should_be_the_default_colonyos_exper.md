# Security Review — Round 2: TUI-Native Auto Mode, CEO Profile Rotation & UX Fixes

**Reviewer**: Staff Security Engineer
**Branch**: `colonyos/add_support_for_auto_inside_the_tui_the_tui_should_be_the_default_colonyos_exper`
**Commit**: `ccc812b` — 1,269 lines added across 21 files
**Date**: 2026-03-27
**Tests**: 52 passed (test_ceo_profiles: 12, test_log_writer: 15, test_transcript: 4 new + existing)

---

## Checklist Assessment

### Completeness
- [x] All 5 functional requirements (FR-1 through FR-5) have implementation
- [x] CEO profiles, log writer, transcript export, auto-scroll fix, auto-in-TUI wiring all present
- [ ] **Partial**: Budget/time caps not enforced in TUI auto loop path (see SEC-1)
- [ ] **Partial**: `.colonyos/logs/` not added to gitignore entries in `init.py` (see SEC-2)

### Quality
- [x] All 52 tests pass
- [x] Code follows existing project conventions (dataclass messages, adapter pattern, `_handle_tui_command` flow)
- [x] No unnecessary dependencies added
- [x] No unrelated changes

### Safety
- [x] No secrets or credentials in committed code
- [x] Log files written with `0o600` permissions (verified in tests)
- [x] Secret redaction via `SECRET_PATTERNS` in log writer
- [x] `sanitize_display_text` applied to user-defined CEO profiles
- [x] `auto_approve` guard preserved for TUI auto command
- [ ] **Missing**: Budget enforcement in TUI auto loop (see SEC-1)
- [ ] **Missing**: Transcript export file does not set restrictive permissions (see SEC-3)

---

## Security Findings

### SEC-1 [HIGH] — Budget and time caps not enforced in TUI auto loop
**File**: `src/colonyos/cli.py` (lines ~5249-5379, `_run_auto_in_tui`)

The CLI `auto` command (`auto_command`) resolves `effective_max_budget` and `effective_max_hours` from CLI flags and config, then checks them before each iteration. The TUI path (`_run_auto_in_tui`) parses `--loop` but **completely ignores `--max-budget` and `--max-hours`**. There is no budget cap check between iterations.

This means a user typing `auto --loop 50` in the TUI gets an uncapped spend loop. The `per_run` budget from the orchestrator still applies per-iteration, but the aggregate loop budget is unchecked. An attacker who can inject a TUI command (e.g., via a crafted instruction template) could trigger unbounded API spend.

**Recommendation**: Port the budget/time cap resolution and inter-iteration checks from `auto_command` into `_run_auto_in_tui`. Parse `--max-budget` and `--max-hours` from tokens, fall back to `config.budget.max_total_usd` and `config.budget.max_duration_hours`, and check before each iteration.

### SEC-2 [MEDIUM] — `.colonyos/logs/` not gitignored
**File**: `src/colonyos/init.py` (line 1023)

The `entries_needed` list for `.gitignore` includes `.colonyos/runs/` and `.colonyos/memory.db` but **not `.colonyos/logs/`**. Log files contain full transcript content which, despite secret redaction, may include sensitive code, proprietary business logic, API responses, and partial secrets that don't match `SECRET_PATTERNS`.

If a user commits their repo without noticing, log files leak into version control and potentially to public repositories.

**Recommendation**: Add `.colonyos/logs/` to the `entries_needed` list in `_finalize_init`.

### SEC-3 [LOW] — Transcript export writes with default permissions
**File**: `src/colonyos/tui/app.py` (`action_export_transcript`)

The `TranscriptLogWriter` correctly uses `os.open()` with `0o600` to create log files. However, the transcript export (Ctrl+S) uses `export_path.write_text()` which inherits the default umask (typically `0o644` — world-readable). Exported transcripts contain the same sensitive content as logs.

**Recommendation**: Use the same `os.open()` + `os.fdopen()` pattern from `TranscriptLogWriter` for exported files, or apply `os.chmod(export_path, 0o600)` after writing.

### SEC-4 [LOW] — `_parse_personas` used for `ceo_profiles` config without sanitization
**File**: `src/colonyos/config.py` (line 701)

The `ceo_profiles` config key is parsed via `_parse_personas()` which does **not** call `sanitize_display_text`. The sanitization only happens in `parse_custom_ceo_profiles()` in `ceo_profiles.py`. However, `_run_auto_in_tui` calls `get_ceo_profile()` which receives `custom_profiles` from... nowhere — it doesn't pass `config.ceo_profiles` at all.

This means:
1. User-defined `ceo_profiles` in config are parsed but never used by the TUI auto loop
2. If they were used, the config parser path (`_parse_personas`) skips sanitization

**Recommendation**: (a) Pass `config.ceo_profiles` to `get_ceo_profile(custom_profiles=...)` in `_run_auto_in_tui`, and (b) either call `parse_custom_ceo_profiles` instead of `_parse_personas` in `load_config`, or add `sanitize_display_text` to `_parse_personas`.

### SEC-5 [INFO] — `_run_auto_in_tui` runs in the consumer thread, not a background worker
**File**: `src/colonyos/cli.py`

The `_run_auto_in_tui` function is called from the `_consumer_loop` (which processes queue messages). Since it contains blocking calls (`run_ceo`, `run_orchestrator`), it will block the entire TUI message processing during execution. This isn't a direct security issue, but it means the two-tier Ctrl+C cancellation (which depends on the TUI event loop processing key events) may not work reliably — the `_stop_event` is set from the TUI action but the blocking loop won't check it until the current API call returns.

This is an availability/UX concern rather than a confidentiality/integrity issue.

### SEC-6 [INFO] — Secret pattern coverage
**File**: `src/colonyos/sanitize.py`

The `SECRET_PATTERNS` list is solid for common token formats (GitHub PATs, OpenAI keys, AWS keys, Slack tokens, Bearer tokens). Notable gaps that aren't urgent but worth tracking:
- Anthropic API keys (`sk-ant-*`)
- Google Cloud service account keys (JSON blobs)
- Private SSH keys (`-----BEGIN`)

These could appear in transcript logs if a user's repo or tool output contains them.

---

## Summary of Findings

| ID | Severity | File | Finding |
|----|----------|------|---------|
| SEC-1 | HIGH | `cli.py` | Budget/time caps not enforced in TUI auto loop |
| SEC-2 | MEDIUM | `init.py` | `.colonyos/logs/` not in gitignore |
| SEC-3 | LOW | `app.py` | Transcript export uses default file permissions |
| SEC-4 | LOW | `config.py` / `cli.py` | Custom CEO profiles not wired through or sanitized in config path |
| SEC-5 | INFO | `cli.py` | Blocking loop may impair cancellation responsiveness |
| SEC-6 | INFO | `sanitize.py` | Secret pattern coverage gaps (Anthropic keys, SSH keys) |

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py]: Budget and time caps (`--max-budget`, `--max-hours`, config fallbacks) are not enforced in `_run_auto_in_tui`, allowing uncapped API spend in TUI auto loops
- [src/colonyos/init.py]: `.colonyos/logs/` directory not added to `.gitignore` entries, risking accidental commit of sensitive transcript logs
- [src/colonyos/tui/app.py]: `action_export_transcript` writes files with default umask permissions instead of `0o600`
- [src/colonyos/cli.py + config.py]: Custom `ceo_profiles` from config are never passed to `get_ceo_profile()` in TUI auto loop, and the config parser path skips `sanitize_display_text`

SYNTHESIS:
This is a dramatically improved implementation compared to Round 1 (which had zero code). The security fundamentals are largely correct: the `auto_approve` gate is preserved, log files use `0o600` permissions, secret redaction is applied, and CEO profile sanitization exists. However, the most critical security control for an autonomous spending loop — **budget enforcement** — was implemented in the CLI path but not ported to the TUI path. This is a must-fix before merge. The gitignore gap (SEC-2) is the second priority since it could lead to data leakage. SEC-3 and SEC-4 are straightforward fixes that should be addressed but aren't blockers. Overall, the architecture is sound and the security controls are in the right places — they just need to be consistently applied across both the CLI and TUI execution paths.
