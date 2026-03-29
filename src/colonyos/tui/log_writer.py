"""TranscriptLogWriter -- persists TUI transcript content to plain-text log files."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from colonyos.sanitize import SECRET_PATTERNS

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"

# Regex to strip Rich markup/ANSI from log output
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _redact_secrets(text: str) -> str:
    """Apply SECRET_PATTERNS redaction to text."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class TranscriptLogWriter:
    """Writes transcript messages to a plain-text log file.

    Log files are created in ``.colonyos/logs/`` with ``0o600`` permissions.
    Content is sanitized for secrets before writing.

    Args:
        logs_dir: Directory for log files (usually repo_root / ".colonyos" / "logs").
        run_id: Unique identifier for this TUI session.
        max_log_files: Maximum number of log files to retain (oldest-first rotation).
    """

    def __init__(
        self,
        logs_dir: Path,
        run_id: str,
        max_log_files: int = 50,
    ) -> None:
        self._logs_dir = logs_dir
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._max_log_files = max_log_files
        self._log_path = logs_dir / f"{run_id}.log"
        # Create file with restricted permissions
        fd = os.open(str(self._log_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        self._file = os.fdopen(fd, "w", encoding="utf-8")
        self._closed = False
        self._rotate_old_logs()

    @property
    def log_path(self) -> Path:
        return self._log_path

    def write_line(self, text: str) -> None:
        """Write a single line to the log file, redacting secrets."""
        if self._closed:
            return
        clean = _ANSI_RE.sub("", text)
        clean = _redact_secrets(clean)
        self._file.write(clean + "\n")
        self._file.flush()

    def write_phase_header(self, phase_name: str, budget: float, model: str, extra: str = "") -> None:
        parts = [f"--- Phase: {phase_name}  ${budget:.2f} budget  {model}"]
        if extra:
            parts[0] += f"  {extra}"
        parts[0] += " ---"
        self.write_line(parts[0])

    def write_tool_line(self, tool_name: str, arg: str) -> None:
        self.write_line(f"  * {tool_name} {arg}")

    def write_text_block(self, text: str) -> None:
        for line in text.splitlines():
            self.write_line(f"  {line}")

    def write_phase_complete(self, cost: float, turns: int, duration: str) -> None:
        self.write_line(f"  > Phase completed  ${cost:.2f} . {turns} turns . {duration}")

    def write_phase_error(self, error: str) -> None:
        self.write_line(f"  x Phase failed: {error}")

    def write_user_message(self, text: str) -> None:
        self.write_line(f"  You: {text}")

    def write_notice(self, text: str) -> None:
        self.write_line(f"  ! {text}")

    def write_iteration_header(self, iteration: int, total: int, persona_name: str, cost: float) -> None:
        self.write_line(f"=== Iteration {iteration}/{total}  Persona: {persona_name}  Cost: ${cost:.2f} ===")

    def close(self) -> None:
        """Flush and close the log file."""
        if not self._closed:
            self._closed = True
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                logger.exception("Error closing log file")

    def _rotate_old_logs(self) -> None:
        """Delete oldest log files if count exceeds max_log_files."""
        try:
            log_files = sorted(
                self._logs_dir.glob("*.log"),
                key=lambda p: p.stat().st_mtime,
            )
            excess = len(log_files) - self._max_log_files
            if excess > 0:
                for old_file in log_files[:excess]:
                    old_file.unlink(missing_ok=True)
        except Exception:
            logger.exception("Error during log rotation")
