"""Tests for the TranscriptLogWriter."""

from __future__ import annotations

import os
import stat

import pytest

from colonyos.tui.log_writer import TranscriptLogWriter, _redact_secrets


@pytest.fixture
def logs_dir(tmp_path):
    """Create a temporary logs directory."""
    d = tmp_path / "logs"
    d.mkdir()
    return d


class TestTranscriptLogWriter:
    """Tests for TranscriptLogWriter."""

    def test_creates_log_file(self, logs_dir) -> None:
        """Log file should be created on init."""
        writer = TranscriptLogWriter(logs_dir, "test-run-001")
        assert writer.log_path.exists()
        writer.close()

    def test_file_permissions(self, logs_dir) -> None:
        """Log file should have 0o600 permissions."""
        writer = TranscriptLogWriter(logs_dir, "test-run-002")
        mode = os.stat(writer.log_path).st_mode
        assert stat.S_IMODE(mode) == 0o600
        writer.close()

    def test_write_line(self, logs_dir) -> None:
        """write_line should append text to the log file."""
        writer = TranscriptLogWriter(logs_dir, "test-run-003")
        writer.write_line("Hello world")
        writer.close()
        content = writer.log_path.read_text()
        assert "Hello world" in content

    def test_write_line_strips_ansi(self, logs_dir) -> None:
        """ANSI escape sequences should be stripped from log output."""
        writer = TranscriptLogWriter(logs_dir, "test-run-004")
        writer.write_line("\x1b[31mRed text\x1b[0m")
        writer.close()
        content = writer.log_path.read_text()
        assert "\x1b" not in content
        assert "Red text" in content

    def test_write_line_redacts_secrets(self, logs_dir) -> None:
        """Secret patterns should be redacted."""
        writer = TranscriptLogWriter(logs_dir, "test-run-005")
        writer.write_line("Token: ghp_abc123def456ghi789jkl012mno345pqr678")
        writer.close()
        content = writer.log_path.read_text()
        assert "ghp_" not in content
        assert "[REDACTED]" in content

    def test_write_phase_header(self, logs_dir) -> None:
        """Phase header should include phase name and budget."""
        writer = TranscriptLogWriter(logs_dir, "test-run-006")
        writer.write_phase_header("planning", 5.0, "opus")
        writer.close()
        content = writer.log_path.read_text()
        assert "planning" in content
        assert "$5.00" in content
        assert "opus" in content

    def test_write_phase_header_with_extra(self, logs_dir) -> None:
        """Phase header with extra metadata should include it."""
        writer = TranscriptLogWriter(logs_dir, "test-run-007")
        writer.write_phase_header("implement", 5.0, "opus", "branch: feat")
        writer.close()
        content = writer.log_path.read_text()
        assert "branch: feat" in content

    def test_write_tool_line(self, logs_dir) -> None:
        """Tool line should include tool name and arg."""
        writer = TranscriptLogWriter(logs_dir, "test-run-008")
        writer.write_tool_line("Read", "/some/file.py")
        writer.close()
        content = writer.log_path.read_text()
        assert "Read" in content
        assert "/some/file.py" in content

    def test_write_iteration_header(self, logs_dir) -> None:
        """Iteration header should include iteration and persona info."""
        writer = TranscriptLogWriter(logs_dir, "test-run-009")
        writer.write_iteration_header(1, 3, "Safety CEO", 1.5)
        writer.close()
        content = writer.log_path.read_text()
        assert "Iteration 1/3" in content
        assert "Safety CEO" in content
        assert "$1.50" in content

    def test_close_prevents_writes(self, logs_dir) -> None:
        """After close, write_line should be a no-op."""
        writer = TranscriptLogWriter(logs_dir, "test-run-010")
        writer.write_line("before close")
        writer.close()
        writer.write_line("after close")
        content = writer.log_path.read_text()
        assert "before close" in content
        assert "after close" not in content

    def test_log_rotation(self, logs_dir) -> None:
        """Old log files should be rotated when max_log_files is exceeded."""
        # Create 5 old log files
        for i in range(5):
            (logs_dir / f"old-{i}.log").write_text(f"old log {i}")

        # Create writer with max_log_files=3, which adds 1 more = 6 total, keep 3
        writer = TranscriptLogWriter(logs_dir, "new-run", max_log_files=3)
        writer.close()

        remaining = list(logs_dir.glob("*.log"))
        assert len(remaining) <= 3

    def test_double_close_safe(self, logs_dir) -> None:
        """Calling close twice should not raise."""
        writer = TranscriptLogWriter(logs_dir, "test-run-011")
        writer.close()
        writer.close()  # Should not raise


class TestRedactSecrets:
    """Tests for _redact_secrets()."""

    def test_redacts_github_pat(self) -> None:
        assert "[REDACTED]" in _redact_secrets("ghp_abc123def456ghi789jkl012mno345pqr678")

    def test_redacts_openai_key(self) -> None:
        assert "[REDACTED]" in _redact_secrets("sk-abc123def456ghi789jkl012mno345pqr678")

    def test_preserves_normal_text(self) -> None:
        text = "Just a normal log line with no secrets."
        assert _redact_secrets(text) == text
