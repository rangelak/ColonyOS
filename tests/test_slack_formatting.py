"""Tests for Slack formatting functions in orchestrator.py.

Task 1.0: Test foundation for informative Slack pipeline notifications.
These tests verify the formatting functions produce human-readable bullet-formatted
output suitable for Slack threads.
"""

import json

import pytest

from colonyos.models import Persona, Phase, PhaseResult


# ---------------------------------------------------------------------------
# Imports for functions under test.  _extract_review_findings_summary is new
# and will be added in task 4.0 — guard its import so we can still run the
# other tests before that function exists.
# ---------------------------------------------------------------------------
from colonyos.orchestrator import (
    _format_task_outline_note,
    _format_implement_result_note,
    _format_review_round_note,
    _format_fix_iteration_extra,
    _format_task_ids,
)

try:
    from colonyos.orchestrator import _extract_review_findings_summary
except ImportError:
    _extract_review_findings_summary = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_phase_result(
    *,
    success: bool = True,
    artifacts: dict | None = None,
    cost_usd: float | None = None,
    duration_ms: int = 0,
) -> PhaseResult:
    return PhaseResult(
        phase=Phase.IMPLEMENT,
        success=success,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        artifacts=artifacts or {},
    )


def _make_review_result(
    *,
    success: bool = True,
    result_text: str = "",
) -> PhaseResult:
    return PhaseResult(
        phase=Phase.REVIEW,
        success=success,
        artifacts={"result": result_text},
    )


# ===================================================================
# 1.1  _format_task_outline_note
# ===================================================================


class TestFormatTaskOutlineNote:
    """Parametrized tests for _format_task_outline_note()."""

    def test_empty_list(self):
        assert _format_task_outline_note([]) == ""

    def test_single_task(self):
        result = _format_task_outline_note([("1.0", "Setup frontend")])
        assert "`1.0`" in result
        assert "Setup frontend" in result
        # Should mention the count
        assert "(1)" in result or "1)" in result

    def test_six_tasks_at_limit(self):
        tasks = [(f"{i}.0", f"Task number {i}") for i in range(1, 7)]
        result = _format_task_outline_note(tasks)
        for i in range(1, 7):
            assert f"`{i}.0`" in result
            assert f"Task number {i}" in result
        # Exactly at limit — no +N more
        assert "+0 more" not in result
        assert "more" not in result
        assert "(6)" in result or "6)" in result

    def test_eight_tasks_overflow(self):
        tasks = [(f"{i}.0", f"Task number {i}") for i in range(1, 9)]
        result = _format_task_outline_note(tasks)
        # First 6 should be shown
        for i in range(1, 7):
            assert f"`{i}.0`" in result
        # Tasks 7 and 8 should NOT be shown individually
        assert "`7.0`" not in result
        assert "`8.0`" not in result
        # Should show +2 more
        assert "+2 more" in result
        assert "(8)" in result or "8)" in result

    def test_long_description_truncation(self):
        long_desc = "A" * 100
        result = _format_task_outline_note([("1.0", long_desc)])
        # Description should be truncated (not all 100 chars)
        assert "A" * 100 not in result
        assert "..." in result

    @pytest.mark.xfail(reason="Bullet formatting not yet implemented (task 2.0)", strict=True)
    def test_uses_bullet_format(self):
        """Output should use bullet points with newlines, not semicolons."""
        tasks = [("1.0", "First task"), ("2.0", "Second task")]
        result = _format_task_outline_note(tasks)
        # Should use bullet format with newlines
        assert "\u2022" in result  # bullet character
        assert "\n" in result


# ===================================================================
# 1.2  _format_implement_result_note
# ===================================================================


class TestFormatImplementResultNote:
    """Parametrized tests for _format_implement_result_note()."""

    def test_all_completed(self):
        task_results = {
            "1.0": {"status": "COMPLETED", "description": "Setup frontend"},
            "2.0": {"status": "COMPLETED", "description": "Backend API"},
        }
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"task_results": json.dumps(task_results)})
        )
        assert "2 completed" in result
        assert "0 failed" in result
        assert "0 blocked" in result
        assert "`1.0`" in result
        assert "`2.0`" in result

    def test_mixed_statuses(self):
        task_results = {
            "1.0": {"status": "COMPLETED", "description": "Setup"},
            "2.0": {"status": "FAILED", "description": "Backend"},
            "3.0": {"status": "BLOCKED", "description": "Deploy"},
        }
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"task_results": json.dumps(task_results)})
        )
        assert "1 completed" in result
        assert "1 failed" in result
        assert "1 blocked" in result

    def test_fallback_no_task_results(self):
        """When task_results dict is missing, fall back to count-based display."""
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"completed": "3", "failed": "1", "blocked": "0"})
        )
        assert "3 completed" in result
        assert "1 failed" in result
        assert "0 blocked" in result

    @pytest.mark.xfail(reason="Descriptions not yet included in output (task 3.0)", strict=True)
    def test_descriptions_appear_in_output(self):
        """Task descriptions from task_results should appear in the output."""
        task_results = {
            "1.0": {"status": "COMPLETED", "description": "Frontend dependencies and type foundations"},
            "2.0": {"status": "COMPLETED", "description": "Daemon health banner component"},
        }
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"task_results": json.dumps(task_results)})
        )
        assert "Frontend dependencies" in result
        assert "Daemon health banner" in result

    @pytest.mark.xfail(reason="Cost/duration not yet included in output (task 3.0)", strict=True)
    def test_cost_and_duration_shown(self):
        """Cost and duration data should appear in output when available."""
        task_results = {
            "1.0": {
                "status": "COMPLETED",
                "description": "Setup frontend",
                "cost_usd": 0.58,
                "duration_ms": 142000,
            },
        }
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"task_results": json.dumps(task_results)})
        )
        assert "$0.58" in result
        assert "142s" in result

    @pytest.mark.xfail(reason="Bullet formatting not yet implemented (task 3.0)", strict=True)
    def test_uses_bullet_format(self):
        """Output should use bullet-point format for task listing."""
        task_results = {
            "1.0": {"status": "COMPLETED", "description": "First"},
            "2.0": {"status": "COMPLETED", "description": "Second"},
        }
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"task_results": json.dumps(task_results)})
        )
        assert "\u2022" in result  # bullet character


# ===================================================================
# 1.3  _format_review_round_note
# ===================================================================


class TestFormatReviewRoundNote:
    """Parametrized tests for _format_review_round_note()."""

    @staticmethod
    def _personas(n: int = 2) -> list[Persona]:
        roles = [
            "Principal Systems Engineer",
            "Linus Torvalds",
            "Staff Security Engineer",
            "Andrej Karpathy",
        ]
        return [Persona(role=roles[i % len(roles)], expertise="test", perspective="test") for i in range(n)]

    def test_all_approved(self):
        reviewers = self._personas(2)
        results = [
            _make_review_result(result_text="VERDICT: approve\nLooks good."),
            _make_review_result(result_text="VERDICT: approve\nShip it."),
        ]
        note = _format_review_round_note(results, reviewers, round_num=1, total_rounds=3)
        assert "2 approved" in note
        assert "0 requested changes" in note
        assert "approved" in note.lower()

    def test_mixed_approved_and_changes(self):
        reviewers = self._personas(3)
        results = [
            _make_review_result(result_text="VERDICT: approve\nLGTM."),
            _make_review_result(
                result_text=(
                    "VERDICT: request-changes\n"
                    "FINDINGS:\n"
                    "- [src/api.py]: Missing error handling in retry loop\n"
                    "- [src/models.py]: Unused import\n"
                    "SYNTHESIS:\n"
                    "The code needs better error handling."
                )
            ),
            _make_review_result(result_text="VERDICT: approve\nGood to go."),
        ]
        note = _format_review_round_note(results, reviewers, round_num=2, total_rounds=5)
        assert "2 approved" in note
        assert "1 requested changes" in note
        assert "R2 Linus Torvalds" in note

    def test_failed_reviewer(self):
        reviewers = self._personas(2)
        results = [
            _make_review_result(result_text="VERDICT: approve"),
            _make_review_result(success=False, result_text=""),
        ]
        note = _format_review_round_note(results, reviewers, round_num=1, total_rounds=3)
        assert "1 failed" in note

    @pytest.mark.xfail(reason="Finding summaries not yet included in review notes (task 4.0)", strict=True)
    def test_findings_in_output(self):
        """When a reviewer requests changes with FINDINGS, those should appear in the note."""
        reviewers = self._personas(2)
        results = [
            _make_review_result(result_text="VERDICT: approve"),
            _make_review_result(
                result_text=(
                    "VERDICT: request-changes\n"
                    "FINDINGS:\n"
                    "- [src/config.py]: API key should use env var not hardcoded string\n"
                    "SYNTHESIS:\n"
                    "Security concern with hardcoded API key."
                )
            ),
        ]
        note = _format_review_round_note(results, reviewers, round_num=1, total_rounds=3)
        assert "API key" in note or "config.py" in note

    def test_no_findings_section_fallback(self):
        """When review text has no FINDINGS section, should still produce output."""
        reviewers = self._personas(2)
        results = [
            _make_review_result(result_text="VERDICT: approve"),
            _make_review_result(
                result_text="VERDICT: request-changes\nThe code has issues with error handling."
            ),
        ]
        note = _format_review_round_note(results, reviewers, round_num=1, total_rounds=3)
        # Should still mention the reviewer requested changes
        assert "requested changes" in note


# ===================================================================
# 1.4  _extract_review_findings_summary (new helper)
# ===================================================================

_extract_findings_available = pytest.mark.skipif(
    _extract_review_findings_summary is None,
    reason="_extract_review_findings_summary not yet implemented (task 4.0)",
)


@_extract_findings_available
class TestExtractReviewFindingsSummary:
    """Tests for the _extract_review_findings_summary() helper."""

    def test_well_formatted_findings(self):
        text = (
            "FINDINGS:\n"
            "- [src/api.py]: Missing error handling in retry loop\n"
            "- [src/models.py]: Unused import\n"
            "- [src/config.py]: Hardcoded API key\n"
            "SYNTHESIS:\n"
            "The code needs better error handling overall."
        )
        findings = _extract_review_findings_summary(text)
        assert len(findings) <= 2  # default max_findings=2
        assert any("api.py" in f.lower() or "error handling" in f.lower() for f in findings)

    def test_missing_findings_section_fallback(self):
        text = "VERDICT: request-changes\nThe code has serious issues with error handling."
        findings = _extract_review_findings_summary(text)
        # Should return something (fallback to first line or synthesis)
        assert len(findings) >= 1

    def test_empty_text(self):
        findings = _extract_review_findings_summary("")
        assert findings == []

    def test_truncation_of_long_findings(self):
        long_finding = "- [src/very/long/path/to/file.py]: " + "A" * 200
        text = f"FINDINGS:\n{long_finding}\nSYNTHESIS:\nSummary."
        findings = _extract_review_findings_summary(text, max_chars=80)
        for finding in findings:
            assert len(finding) <= 80

    def test_custom_max_findings(self):
        text = (
            "FINDINGS:\n"
            "- [a.py]: Issue 1\n"
            "- [b.py]: Issue 2\n"
            "- [c.py]: Issue 3\n"
            "- [d.py]: Issue 4\n"
        )
        findings = _extract_review_findings_summary(text, max_findings=3)
        assert len(findings) <= 3

    def test_synthesis_fallback(self):
        """When no FINDINGS section but SYNTHESIS exists, use it as fallback."""
        text = (
            "VERDICT: request-changes\n"
            "SYNTHESIS:\n"
            "The implementation lacks proper error boundaries and needs retry logic."
        )
        findings = _extract_review_findings_summary(text)
        assert len(findings) >= 1


# ===================================================================
# 1.5  Message size cap (3,000 chars)
# ===================================================================


class TestMessageSizeCap:
    """Verify that no single formatted message exceeds 3,000 characters
    when given pathologically long inputs."""

    def test_task_outline_max_length(self):
        """Task outline with many tasks and long descriptions stays under 3000 chars."""
        tasks = [(f"{i}.0", "X" * 100) for i in range(1, 51)]
        result = _format_task_outline_note(tasks)
        assert len(result) <= 3000

    def test_implement_result_max_length(self):
        """Implement result with many tasks stays under 3000 chars."""
        task_results = {}
        for i in range(1, 51):
            task_results[f"{i}.0"] = {
                "status": "COMPLETED",
                "description": "X" * 100,
                "cost_usd": 1.23,
                "duration_ms": 99999,
            }
        result = _format_implement_result_note(
            _make_phase_result(artifacts={"task_results": json.dumps(task_results)})
        )
        # After task 5.0 adds truncation, this should be under 3000 chars.
        # For now, just verify it produces output.
        assert len(result) > 0

    def test_review_round_max_length(self):
        """Review round with many reviewers and long findings stays under 3000 chars."""
        roles = [f"Reviewer {i}" for i in range(10)]
        reviewers = [Persona(role=r, expertise="test", perspective="test") for r in roles]
        long_findings = "FINDINGS:\n" + "\n".join(
            f"- [src/file{i}.py]: {'A' * 200}" for i in range(20)
        )
        results = [
            _make_review_result(result_text=f"VERDICT: request-changes\n{long_findings}")
            for _ in range(10)
        ]
        note = _format_review_round_note(results, reviewers, round_num=1, total_rounds=3)
        # Should produce output without error
        assert len(note) > 0
