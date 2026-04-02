"""Tests for verify and verify-fix instruction templates."""

from pathlib import Path


INSTRUCTIONS_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "colonyos"
    / "instructions"
)


# ---------------------------------------------------------------------------
# verify.md template tests
# ---------------------------------------------------------------------------


class TestVerifyInstructionTemplate:
    TEMPLATE_PATH = INSTRUCTIONS_DIR / "verify.md"

    def test_file_exists(self):
        assert self.TEMPLATE_PATH.exists(), (
            f"Expected verify instruction at {self.TEMPLATE_PATH}"
        )

    def test_is_read_only(self):
        """Verify template must explicitly forbid code modification."""
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "do NOT" in content.lower() or "do not" in content.lower()
        assert "modify" in content.lower() or "change" in content.lower()

    def test_contains_test_suite_instruction(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "test" in content.lower()

    def test_contains_branch_placeholder(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "{branch_name}" in content

    def test_contains_change_summary_placeholder(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "{change_summary}" in content

    def test_specifies_reporting_failures(self):
        """Template must instruct agent to report failing tests."""
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "fail" in content.lower()
        assert "report" in content.lower() or "list" in content.lower()

    def test_mentions_available_tools(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "Read" in content
        assert "Bash" in content

    def test_does_not_contain_fix_instructions(self):
        """Read-only verify template must not instruct fixing."""
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        # Should not tell the agent to fix things
        assert "implement the fix" not in content.lower()


# ---------------------------------------------------------------------------
# verify_fix.md template tests
# ---------------------------------------------------------------------------


class TestVerifyFixInstructionTemplate:
    TEMPLATE_PATH = INSTRUCTIONS_DIR / "verify_fix.md"

    def test_file_exists(self):
        assert self.TEMPLATE_PATH.exists(), (
            f"Expected verify_fix instruction at {self.TEMPLATE_PATH}"
        )

    def test_allows_code_modification(self):
        """Fix template must instruct the agent to modify code."""
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "fix" in content.lower()

    def test_contains_branch_placeholder(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "{branch_name}" in content

    def test_contains_test_failure_placeholder(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "{test_failure_output}" in content

    def test_contains_fix_iteration_placeholders(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "{fix_attempt}" in content
        assert "{max_fix_attempts}" in content

    def test_instructs_rerun_tests(self):
        """Fix template must instruct running tests after fixing."""
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        lower = content.lower()
        assert "run" in lower and "test" in lower

    def test_fix_code_not_tests(self):
        """Template should instruct fixing implementation, not tests."""
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        # Should contain guidance about fixing code rather than tests
        assert "fix the code" in content.lower() or "fix the implementation" in content.lower()

    def test_contains_commit_instructions(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "commit" in content.lower()

    def test_contains_rules_section(self):
        content = self.TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "## Rules" in content
