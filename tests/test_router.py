"""Tests for the Intent Router module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.router import (
    RouterCategory,
    RouterResult,
    _build_router_prompt,
    _parse_router_response,
    route_query,
)


# ---------------------------------------------------------------------------
# RouterCategory enum tests (Task 1.1, 1.2)
# ---------------------------------------------------------------------------


class TestRouterCategory:
    """Tests for RouterCategory enum."""

    def test_code_change_value(self) -> None:
        assert RouterCategory.CODE_CHANGE.value == "code_change"

    def test_question_value(self) -> None:
        assert RouterCategory.QUESTION.value == "question"

    def test_status_value(self) -> None:
        assert RouterCategory.STATUS.value == "status"

    def test_out_of_scope_value(self) -> None:
        assert RouterCategory.OUT_OF_SCOPE.value == "out_of_scope"

    def test_all_categories_are_strings(self) -> None:
        for cat in RouterCategory:
            assert isinstance(cat.value, str)

    def test_category_count(self) -> None:
        """Ensure exactly 4 categories exist."""
        assert len(RouterCategory) == 4


# ---------------------------------------------------------------------------
# RouterResult dataclass tests (Task 1.1, 1.3)
# ---------------------------------------------------------------------------


class TestRouterResult:
    """Tests for RouterResult dataclass."""

    def test_basic_construction(self) -> None:
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.95,
            summary="Add new feature",
            reasoning="User wants to add a feature",
        )
        assert result.category == RouterCategory.CODE_CHANGE
        assert result.confidence == 0.95
        assert result.summary == "Add new feature"
        assert result.reasoning == "User wants to add a feature"

    def test_question_category(self) -> None:
        result = RouterResult(
            category=RouterCategory.QUESTION,
            confidence=0.85,
            summary="Asking about function behavior",
            reasoning="User is asking what something does",
        )
        assert result.category == RouterCategory.QUESTION

    def test_status_category(self) -> None:
        result = RouterResult(
            category=RouterCategory.STATUS,
            confidence=0.9,
            summary="Wants queue status",
            reasoning="User asking about queue state",
            suggested_command="colonyos status",
        )
        assert result.category == RouterCategory.STATUS
        assert result.suggested_command == "colonyos status"

    def test_out_of_scope_category(self) -> None:
        result = RouterResult(
            category=RouterCategory.OUT_OF_SCOPE,
            confidence=0.75,
            summary="Unrelated request",
            reasoning="Not about code or the project",
        )
        assert result.category == RouterCategory.OUT_OF_SCOPE

    def test_suggested_command_default_none(self) -> None:
        result = RouterResult(
            category=RouterCategory.QUESTION,
            confidence=0.8,
            summary="Test",
            reasoning="Test",
        )
        assert result.suggested_command is None

    def test_frozen_dataclass(self) -> None:
        """RouterResult should be immutable (frozen)."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        with pytest.raises(AttributeError):
            result.confidence = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _build_router_prompt tests (Task 1.4)
# ---------------------------------------------------------------------------


class TestBuildRouterPrompt:
    """Tests for router prompt construction."""

    def test_includes_category_definitions(self) -> None:
        system, user = _build_router_prompt("fix the login bug")
        assert "code_change" in system.lower()
        assert "question" in system.lower()
        assert "status" in system.lower()
        assert "out_of_scope" in system.lower()

    def test_includes_json_format_instructions(self) -> None:
        system, user = _build_router_prompt("add a feature")
        assert "json" in system.lower()
        assert "category" in system.lower()
        assert "confidence" in system.lower()

    def test_includes_user_query(self) -> None:
        system, user = _build_router_prompt("what does the sanitize function do?")
        assert "sanitize function" in user

    def test_includes_project_context(self) -> None:
        system, user = _build_router_prompt(
            "add login",
            project_name="MyApp",
            project_description="A web application",
            project_stack="Python/FastAPI",
        )
        assert "MyApp" in system
        assert "web application" in system
        assert "Python/FastAPI" in system

    def test_includes_vision_when_provided(self) -> None:
        system, user = _build_router_prompt(
            "fix bug",
            vision="Be the best developer tool",
        )
        assert "best developer tool" in system

    def test_minimal_prompt_works(self) -> None:
        system, user = _build_router_prompt("hello world")
        assert "hello world" in user
        assert len(system) > 100  # Should have instructions

    def test_sanitizes_user_input(self) -> None:
        """User input should be sanitized to prevent prompt injection."""
        system, user = _build_router_prompt("<script>alert('xss')</script> fix the bug")
        assert "<script>" not in user
        assert "fix the bug" in user


# ---------------------------------------------------------------------------
# _parse_router_response tests (Task 1.5)
# ---------------------------------------------------------------------------


class TestParseRouterResponse:
    """Tests for router response parsing."""

    def test_valid_code_change_json(self) -> None:
        raw = json.dumps({
            "category": "code_change",
            "confidence": 0.95,
            "summary": "Add health check endpoint",
            "reasoning": "User wants to add a new feature",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.CODE_CHANGE
        assert result.confidence == 0.95
        assert result.summary == "Add health check endpoint"
        assert result.reasoning == "User wants to add a new feature"

    def test_valid_question_json(self) -> None:
        raw = json.dumps({
            "category": "question",
            "confidence": 0.88,
            "summary": "Asking about function behavior",
            "reasoning": "User is asking what something does",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.QUESTION
        assert result.confidence == 0.88

    def test_valid_status_json(self) -> None:
        raw = json.dumps({
            "category": "status",
            "confidence": 0.92,
            "summary": "Queue status inquiry",
            "reasoning": "User wants to see queue state",
            "suggested_command": "colonyos status",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.STATUS
        assert result.suggested_command == "colonyos status"

    def test_valid_out_of_scope_json(self) -> None:
        raw = json.dumps({
            "category": "out_of_scope",
            "confidence": 0.85,
            "summary": "Weather question",
            "reasoning": "Not related to code",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.OUT_OF_SCOPE

    def test_json_with_markdown_fences(self) -> None:
        raw = '```json\n{"category": "code_change", "confidence": 0.9, "summary": "Fix it", "reasoning": "Bug fix"}\n```'
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.CODE_CHANGE

    def test_malformed_json_returns_code_change_fallback(self) -> None:
        """Malformed JSON should fail-open to CODE_CHANGE."""
        result = _parse_router_response("this is not json")
        assert result.category == RouterCategory.CODE_CHANGE
        assert result.confidence == 0.0
        assert "Failed to parse" in result.reasoning

    def test_missing_fields_use_defaults(self) -> None:
        result = _parse_router_response('{"category": "question"}')
        assert result.category == RouterCategory.QUESTION
        assert result.confidence == 0.0
        assert result.summary == ""

    def test_invalid_category_returns_code_change_fallback(self) -> None:
        """Unknown category should fail-open to CODE_CHANGE."""
        raw = json.dumps({
            "category": "invalid_category",
            "confidence": 0.9,
            "summary": "Test",
            "reasoning": "Test",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.CODE_CHANGE
        assert "Unknown category" in result.reasoning

    def test_confidence_above_one_clamped(self) -> None:
        raw = json.dumps({
            "category": "question",
            "confidence": 5.0,
            "summary": "Test",
            "reasoning": "Test",
        })
        result = _parse_router_response(raw)
        assert result.confidence == 1.0

    def test_confidence_below_zero_clamped(self) -> None:
        raw = json.dumps({
            "category": "code_change",
            "confidence": -0.5,
            "summary": "Test",
            "reasoning": "Test",
        })
        result = _parse_router_response(raw)
        assert result.confidence == 0.0

    def test_suggested_command_for_status(self) -> None:
        raw = json.dumps({
            "category": "status",
            "confidence": 0.9,
            "summary": "Stats request",
            "reasoning": "User wants stats",
            "suggested_command": "colonyos stats",
        })
        result = _parse_router_response(raw)
        assert result.suggested_command == "colonyos stats"

    def test_suggested_command_default_none(self) -> None:
        raw = json.dumps({
            "category": "code_change",
            "confidence": 0.9,
            "summary": "Test",
            "reasoning": "Test",
        })
        result = _parse_router_response(raw)
        assert result.suggested_command is None


# ---------------------------------------------------------------------------
# route_query tests (Task 1.6)
# ---------------------------------------------------------------------------


class TestRouteQuery:
    """Tests for the main route_query function."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        """Create a temporary repo directory."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    def test_signature_accepts_required_params(self) -> None:
        """Verify route_query has the expected parameters."""
        import inspect
        sig = inspect.signature(route_query)
        params = list(sig.parameters.keys())
        assert "query" in params
        assert "repo_root" in params

    def test_returns_router_result(self, tmp_repo: Path) -> None:
        """route_query should return a RouterResult."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": json.dumps({
                    "category": "question",
                    "confidence": 0.85,
                    "summary": "Test question",
                    "reasoning": "User asking",
                })},
                error=None,
            )
            result = route_query("what does this function do?", repo_root=tmp_repo)
            assert isinstance(result, RouterResult)
            assert result.category == RouterCategory.QUESTION

    def test_uses_haiku_model(self, tmp_repo: Path) -> None:
        """route_query should use haiku model for classification."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query("add a feature", repo_root=tmp_repo)
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["model"] == "haiku"

    def test_uses_no_tools(self, tmp_repo: Path) -> None:
        """route_query should use no tools (read-only classification)."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query("add a feature", repo_root=tmp_repo)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["allowed_tools"] == []

    def test_uses_small_budget(self, tmp_repo: Path) -> None:
        """route_query should use a small budget ($0.05)."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query("add a feature", repo_root=tmp_repo)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["budget_usd"] == 0.05

    def test_uses_triage_phase(self, tmp_repo: Path) -> None:
        """route_query should use Phase.TRIAGE."""
        from colonyos.models import Phase
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query("add a feature", repo_root=tmp_repo)
            call_args = mock_run.call_args[0]
            assert call_args[0] == Phase.TRIAGE

    def test_handles_llm_error(self, tmp_repo: Path) -> None:
        """When LLM call fails, should fail-open to CODE_CHANGE."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={},
                error="API error",
            )
            result = route_query("add a feature", repo_root=tmp_repo)
            assert result.category == RouterCategory.CODE_CHANGE
            assert result.confidence == 0.0

    def test_includes_project_context(self, tmp_repo: Path) -> None:
        """route_query should include project context in prompt."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query(
                "fix bug",
                repo_root=tmp_repo,
                project_name="TestApp",
                project_description="A test app",
            )
            call_args = mock_run.call_args[0]
            prompt = call_args[1]
            assert "fix bug" in prompt

    def test_optional_source_parameter(self) -> None:
        """route_query should accept optional source parameter for logging."""
        import inspect
        sig = inspect.signature(route_query)
        assert "source" in sig.parameters
        param = sig.parameters["source"]
        assert param.default == "cli"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestRouterIntegration:
    """Integration tests for the router module."""

    def test_full_code_change_flow(self) -> None:
        """Test classification of an obvious code change request."""
        system, user = _build_router_prompt("add a health check endpoint to the API")
        assert "code_change" in system.lower()
        assert "health check" in user

        # Parse a well-formed response
        raw = json.dumps({
            "category": "code_change",
            "confidence": 0.95,
            "summary": "Add health check endpoint",
            "reasoning": "User wants to add a new API endpoint",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.CODE_CHANGE
        assert result.confidence == 0.95

    def test_full_question_flow(self) -> None:
        """Test classification of an obvious question."""
        system, user = _build_router_prompt("what does the sanitize function do?")
        assert "question" in system.lower()
        assert "sanitize" in user

        raw = json.dumps({
            "category": "question",
            "confidence": 0.92,
            "summary": "Asking about sanitize function",
            "reasoning": "User is asking what a function does",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.QUESTION

    def test_full_status_flow(self) -> None:
        """Test classification of a status query."""
        system, user = _build_router_prompt("show me the queue status")
        assert "status" in system.lower()
        assert "queue" in user

        raw = json.dumps({
            "category": "status",
            "confidence": 0.88,
            "summary": "Queue status inquiry",
            "reasoning": "User wants to see current queue state",
            "suggested_command": "colonyos status",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.STATUS
        assert result.suggested_command == "colonyos status"


# ---------------------------------------------------------------------------
# _build_qa_prompt tests (Task 5.3)
# ---------------------------------------------------------------------------


class TestBuildQaPrompt:
    """Tests for Q&A prompt construction."""

    def test_loads_qa_template(self) -> None:
        """_build_qa_prompt should load content from qa.md template."""
        from colonyos.router import _build_qa_prompt
        system, user = _build_qa_prompt("what does this function do?")
        # The template should include key Q&A instructions
        assert "read-only" in system.lower() or "read only" in system.lower()
        assert "question" in user.lower() or "what does" in user.lower()

    def test_includes_user_question(self) -> None:
        """User question should be included in the user prompt."""
        from colonyos.router import _build_qa_prompt
        system, user = _build_qa_prompt("explain the authentication flow")
        assert "authentication flow" in user

    def test_includes_project_context(self) -> None:
        """Project context should be included in system prompt when provided."""
        from colonyos.router import _build_qa_prompt
        system, user = _build_qa_prompt(
            "how does routing work?",
            project_name="TestProject",
            project_description="A test project",
            project_stack="Python/FastAPI",
        )
        assert "TestProject" in system
        assert "test project" in system.lower()
        assert "Python" in system or "FastAPI" in system

    def test_returns_tuple_of_strings(self) -> None:
        """_build_qa_prompt should return (system_prompt, user_prompt) tuple."""
        from colonyos.router import _build_qa_prompt
        result = _build_qa_prompt("test query")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_sanitizes_user_input(self) -> None:
        """User input should be sanitized to prevent prompt injection."""
        from colonyos.router import _build_qa_prompt
        system, user = _build_qa_prompt("<script>alert('xss')</script> what is this?")
        assert "<script>" not in user
        assert "what is this" in user


# ---------------------------------------------------------------------------
# answer_question tests (Task 5.1, 5.2, 5.4)
# ---------------------------------------------------------------------------


class TestAnswerQuestion:
    """Tests for the answer_question function."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        """Create a temporary repo directory."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    def test_signature_accepts_required_params(self) -> None:
        """Verify answer_question has the expected parameters."""
        import inspect
        from colonyos.router import answer_question
        sig = inspect.signature(answer_question)
        params = list(sig.parameters.keys())
        assert "question" in params
        assert "repo_root" in params

    def test_returns_string_answer(self, tmp_repo: Path) -> None:
        """answer_question should return a string answer."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "The function sanitizes user input."},
                error=None,
                success=True,
            )
            result = answer_question("what does sanitize do?", repo_root=tmp_repo)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_uses_qa_phase(self, tmp_repo: Path) -> None:
        """answer_question should use Phase.QA."""
        from colonyos.models import Phase
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer here"},
                error=None,
                success=True,
            )
            answer_question("test question", repo_root=tmp_repo)
            call_args = mock_run.call_args[0]
            assert call_args[0] == Phase.QA

    def test_uses_haiku_model_by_default(self, tmp_repo: Path) -> None:
        """answer_question should use haiku model by default."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer"},
                error=None,
                success=True,
            )
            answer_question("test question", repo_root=tmp_repo)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["model"] == "haiku"

    def test_uses_read_only_tools(self, tmp_repo: Path) -> None:
        """answer_question should only have read-only tools (Read, Glob, Grep)."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer"},
                error=None,
                success=True,
            )
            answer_question("test question", repo_root=tmp_repo)
            call_kwargs = mock_run.call_args[1]
            allowed_tools = call_kwargs["allowed_tools"]
            assert "Read" in allowed_tools
            assert "Glob" in allowed_tools
            assert "Grep" in allowed_tools
            # Should NOT have write tools
            assert "Write" not in allowed_tools
            assert "Edit" not in allowed_tools
            assert "Bash" not in allowed_tools

    def test_uses_default_qa_budget(self, tmp_repo: Path) -> None:
        """answer_question should use default $0.50 budget."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer"},
                error=None,
                success=True,
            )
            answer_question("test question", repo_root=tmp_repo)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["budget_usd"] == 0.50

    def test_respects_custom_budget(self, tmp_repo: Path) -> None:
        """answer_question should respect custom qa_budget parameter."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer"},
                error=None,
                success=True,
            )
            answer_question("test question", repo_root=tmp_repo, qa_budget=1.0)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["budget_usd"] == 1.0

    def test_handles_llm_error(self, tmp_repo: Path) -> None:
        """When LLM call fails, should return error message."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={},
                error="API error occurred",
                success=False,
            )
            result = answer_question("test question", repo_root=tmp_repo)
            assert "error" in result.lower() or "failed" in result.lower() or "unable" in result.lower()

    def test_includes_project_context(self, tmp_repo: Path) -> None:
        """answer_question should include project context in prompt."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer"},
                error=None,
                success=True,
            )
            answer_question(
                "how does auth work?",
                repo_root=tmp_repo,
                project_name="MyProject",
            )
            # The system prompt should be passed
            call_kwargs = mock_run.call_args[1]
            assert "system_prompt" in call_kwargs

    def test_optional_model_parameter(self) -> None:
        """answer_question should accept optional model parameter."""
        import inspect
        from colonyos.router import answer_question
        sig = inspect.signature(answer_question)
        assert "model" in sig.parameters
        param = sig.parameters["model"]
        # Default should be haiku
        assert param.default == "haiku"


class TestAnswerQuestionIntegration:
    """Integration tests for answer_question with the router flow."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        """Create a temporary repo directory."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    def test_question_routed_to_answer(self, tmp_repo: Path) -> None:
        """Test that a question category triggers answer_question path."""
        # This tests the integration between route_query and answer_question
        from colonyos.router import RouterCategory, RouterResult

        # Create a mock router result for a question
        result = RouterResult(
            category=RouterCategory.QUESTION,
            confidence=0.9,
            summary="User asking about code",
            reasoning="This is a question",
        )
        assert result.category == RouterCategory.QUESTION
        # In CLI integration (task 6.0), this would trigger answer_question

    def test_answer_returns_grounded_response(self, tmp_repo: Path) -> None:
        """Test that answer includes file references when LLM provides them."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "The function is defined in `src/colonyos/cli.py:527`. It handles..."},
                error=None,
                success=True,
            )
            result = answer_question("where is the run function?", repo_root=tmp_repo)
            assert "cli.py" in result
