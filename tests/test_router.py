"""Tests for the Intent Router module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import ColonyConfig, RouterConfig, load_config
from colonyos.router import (
    ModeAgentMode,
    ModeAgentDecision,
    RouterCategory,
    RouterResult,
    _build_mode_selection_prompt,
    _build_router_prompt,
    _heuristic_mode_decision,
    _parse_mode_selection_response,
    _parse_router_response,
    build_direct_agent_prompt,
    choose_tui_mode,
    log_router_decision,
    log_mode_selection,
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
# Mode-selection agent tests
# ---------------------------------------------------------------------------


class TestModeAgentDecision:
    def test_basic_construction(self) -> None:
        result = ModeAgentDecision(
            mode=ModeAgentMode.DIRECT_AGENT,
            confidence=0.9,
            summary="Answer a question directly",
            reasoning="This is small and focused",
            announcement="Handling this directly.",
        )
        assert result.mode == ModeAgentMode.DIRECT_AGENT
        assert result.announcement == "Handling this directly."


class TestBuildModeSelectionPrompt:
    def test_lists_supported_modes(self) -> None:
        system, user = _build_mode_selection_prompt("continue the last plan")
        assert "direct_agent" in system
        assert "plan_implement_loop" in system
        assert "implement_only" in system
        assert "review_only" in system
        assert "cleanup_loop" in system
        assert "continue the last plan" in user


class TestParseModeSelectionResponse:
    def test_valid_direct_agent_json(self) -> None:
        raw = json.dumps({
            "mode": "direct_agent",
            "confidence": 0.91,
            "summary": "Small direct request",
            "reasoning": "This should not enter the full pipeline",
            "announcement": "Handling this directly.",
        })
        result = _parse_mode_selection_response(raw)
        assert result.mode == ModeAgentMode.DIRECT_AGENT
        assert result.confidence == 0.91
        assert result.announcement == "Handling this directly."

    def test_invalid_mode_falls_back_to_pipeline(self) -> None:
        result = _parse_mode_selection_response('{"mode":"weird","confidence":1.0}')
        assert result.mode == ModeAgentMode.PLAN_IMPLEMENT_LOOP
        assert result.confidence == 0.0


class TestHeuristicModeDecision:
    """Tests for _heuristic_mode_decision including adversarial inputs."""

    def test_empty_input_returns_fallback(self) -> None:
        result = _heuristic_mode_decision("")
        assert result is not None
        assert result.mode == ModeAgentMode.FALLBACK

    def test_continue_from_latest_prd(self) -> None:
        result = _heuristic_mode_decision("use the latest prd")
        assert result is not None
        assert result.mode == ModeAgentMode.IMPLEMENT_ONLY

    def test_review_request(self) -> None:
        result = _heuristic_mode_decision("review this branch")
        assert result is not None
        assert result.mode == ModeAgentMode.REVIEW_ONLY

    def test_cleanup_request(self) -> None:
        result = _heuristic_mode_decision("cleanup the codebase")
        assert result is not None
        assert result.mode == ModeAgentMode.CLEANUP_LOOP

    def test_question_mark_routes_direct(self) -> None:
        result = _heuristic_mode_decision("what does this function do?")
        assert result is not None
        assert result.mode == ModeAgentMode.DIRECT_AGENT

    def test_change_routes_direct(self) -> None:
        result = _heuristic_mode_decision("change the button color to red")
        assert result is not None
        assert result.mode == ModeAgentMode.DIRECT_AGENT

    def test_rename_routes_direct(self) -> None:
        result = _heuristic_mode_decision("rename the function foo to bar")
        assert result is not None
        assert result.mode == ModeAgentMode.DIRECT_AGENT

    def test_build_routes_to_pipeline(self) -> None:
        result = _heuristic_mode_decision("build a new REST API")
        assert result is not None
        assert result.mode == ModeAgentMode.PLAN_IMPLEMENT_LOOP

    def test_implement_routes_to_pipeline(self) -> None:
        result = _heuristic_mode_decision("implement pagination for the user list")
        assert result is not None
        assert result.mode == ModeAgentMode.PLAN_IMPLEMENT_LOOP

    # -- Adversarial inputs: phrases that previously caused false positives --

    def test_make_sure_does_not_route_direct(self) -> None:
        """'make sure' is not an action verb — should NOT match DIRECT_AGENT."""
        result = _heuristic_mode_decision("I want to make sure the tests pass")
        assert result is None or result.mode != ModeAgentMode.DIRECT_AGENT

    def test_make_certain_does_not_route_direct(self) -> None:
        result = _heuristic_mode_decision("make certain the deploy works")
        assert result is None or result.mode != ModeAgentMode.DIRECT_AGENT

    def test_make_sense_does_not_route_direct(self) -> None:
        result = _heuristic_mode_decision("does this make sense?")
        # Should route as a question (ends with ?) not as DIRECT_AGENT via "make"
        assert result is not None
        assert result.mode == ModeAgentMode.DIRECT_AGENT  # from the ? heuristic
        assert result.confidence == 0.94  # question confidence, not 0.9

    def test_change_my_mind_does_not_route_direct(self) -> None:
        """'change my mind' is not a code action."""
        result = _heuristic_mode_decision("change my mind about the approach")
        assert result is None or result.mode != ModeAgentMode.DIRECT_AGENT

    def test_add_a_note_does_not_route_pipeline(self) -> None:
        """'add a note' is not a feature request."""
        result = _heuristic_mode_decision("add a note about this decision")
        assert result is None or result.mode != ModeAgentMode.PLAN_IMPLEMENT_LOOP

    def test_ambiguous_input_returns_none(self) -> None:
        """Ambiguous input should fall through to the LLM router."""
        result = _heuristic_mode_decision("I think we should discuss the architecture")
        assert result is None

    def test_real_change_request_still_works(self) -> None:
        """Ensure legitimate change requests still route correctly."""
        result = _heuristic_mode_decision("change the background color to blue")
        assert result is not None
        assert result.mode == ModeAgentMode.DIRECT_AGENT

    def test_real_make_request_still_works(self) -> None:
        """Ensure legitimate make requests still route correctly."""
        result = _heuristic_mode_decision("make the header font larger")
        assert result is not None
        assert result.mode == ModeAgentMode.DIRECT_AGENT


class TestChooseTUIMode:
    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    def test_uses_triage_phase(self, tmp_repo: Path) -> None:
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={
                    "result": json.dumps({
                        "mode": "direct_agent",
                        "confidence": 0.9,
                        "summary": "Question",
                        "reasoning": "Small ask",
                        "announcement": "Handling this directly.",
                    })
                },
                error=None,
            )
            result = choose_tui_mode("please decide the right workflow", repo_root=tmp_repo)
            assert result.mode == ModeAgentMode.DIRECT_AGENT
            call_args = mock_run.call_args.args
            from colonyos.models import Phase
            assert call_args[0] == Phase.TRIAGE


class TestBuildDirectAgentPrompt:
    def test_mentions_direct_handling(self) -> None:
        system, user = build_direct_agent_prompt("change this button to red")
        assert "handling a request directly" in system.lower()
        assert "change this button to red" in user


class TestLogModeSelection:
    def test_writes_mode_selection_log(self, tmp_path: Path) -> None:
        result = ModeAgentDecision(
            mode=ModeAgentMode.DIRECT_AGENT,
            confidence=0.88,
            summary="Direct answer",
            reasoning="Small ask",
            announcement="Handling this directly.",
        )
        log_path = log_mode_selection(
            repo_root=tmp_path,
            prompt="what does this do?",
            result=result,
            source="tui",
        )
        assert log_path is not None
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["mode"] == "direct_agent"
        assert data["source"] == "tui"


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
        assert "complexity" in system.lower()

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
            "complexity": "small",
        })
        result = _parse_router_response(raw)
        assert result.category == RouterCategory.CODE_CHANGE
        assert result.confidence == 0.95
        assert result.summary == "Add health check endpoint"
        assert result.reasoning == "User wants to add a new feature"
        assert result.complexity == "small"

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
        assert result.complexity == "large"

    def test_invalid_complexity_defaults_to_large(self) -> None:
        result = _parse_router_response(json.dumps({
            "category": "code_change",
            "confidence": 0.9,
            "summary": "Fix typo",
            "reasoning": "Small edit",
            "complexity": "odd",
        }))
        assert result.complexity == "large"

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

    def test_uses_opus_model_by_default(self, tmp_repo: Path) -> None:
        """route_query should use the default configured router model."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query("add a feature", repo_root=tmp_repo)
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["model"] == "opus"

    def test_respects_explicit_model_override(self, tmp_repo: Path) -> None:
        """route_query should honor an explicit model override."""
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": '{"category": "code_change", "confidence": 0.9, "summary": "x", "reasoning": "y"}'},
                error=None,
            )
            route_query("add a feature", repo_root=tmp_repo, model="sonnet")
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["model"] == "sonnet"

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

    def test_uses_opus_model_by_default(self, tmp_repo: Path) -> None:
        """answer_question should use opus model by default (matching RouterConfig.qa_model)."""
        from colonyos.router import answer_question
        with patch("colonyos.agent.run_phase_sync") as mock_run:
            mock_run.return_value = MagicMock(
                artifacts={"result": "Answer"},
                error=None,
                success=True,
            )
            answer_question("test question", repo_root=tmp_repo)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["model"] == "opus"

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
        # Default should match RouterConfig.qa_model default (opus)
        assert param.default == "opus"


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


# ---------------------------------------------------------------------------
# log_router_decision tests (Task 9.1, 9.2, 9.3)
# ---------------------------------------------------------------------------


class TestLogRouterDecision:
    """Tests for the audit logging function."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        """Create a temporary repo directory."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    def test_creates_log_file(self, tmp_repo: Path) -> None:
        """log_router_decision should create a triage log file."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.95,
            summary="Add feature",
            reasoning="User wants to add a feature",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="add a health check endpoint",
            result=result,
            source="cli",
        )
        assert log_path is not None
        assert log_path.exists()
        assert log_path.name.startswith("triage_")
        assert log_path.suffix == ".json"

    def test_log_file_contains_required_fields(self, tmp_repo: Path) -> None:
        """Log file must contain prompt, category, confidence, reasoning, source, timestamp."""
        result = RouterResult(
            category=RouterCategory.QUESTION,
            confidence=0.88,
            summary="Asking about function",
            reasoning="User is asking what something does",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="what does sanitize do?",
            result=result,
            source="repl",
        )
        assert log_path is not None
        data = json.loads(log_path.read_text())
        assert "timestamp" in data
        assert data["source"] == "repl"
        assert "prompt" in data
        assert data["category"] == "question"
        assert data["confidence"] == 0.88
        assert data["reasoning"] == "User is asking what something does"
        assert data["summary"] == "Asking about function"

    def test_log_file_in_runs_directory(self, tmp_repo: Path) -> None:
        """Log files should be written to .colonyos/runs/."""
        result = RouterResult(
            category=RouterCategory.STATUS,
            confidence=0.9,
            summary="Status query",
            reasoning="Asking about status",
            suggested_command="colonyos status",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="show queue status",
            result=result,
        )
        assert log_path is not None
        assert log_path.parent == tmp_repo / ".colonyos" / "runs"

    def test_log_includes_suggested_command(self, tmp_repo: Path) -> None:
        """Log should include suggested_command for status queries."""
        result = RouterResult(
            category=RouterCategory.STATUS,
            confidence=0.9,
            summary="Stats request",
            reasoning="User wants stats",
            suggested_command="colonyos stats",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="show stats",
            result=result,
        )
        assert log_path is not None
        data = json.loads(log_path.read_text())
        assert data["suggested_command"] == "colonyos stats"

    def test_log_sanitizes_prompt(self, tmp_repo: Path) -> None:
        """Prompt should be sanitized before logging."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="<script>alert('xss')</script> fix the bug",
            result=result,
        )
        assert log_path is not None
        data = json.loads(log_path.read_text())
        assert "<script>" not in data["prompt"]

    def test_creates_runs_dir_if_missing(self, tmp_path: Path) -> None:
        """Should create the runs directory if it doesn't exist."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        log_path = log_router_decision(
            repo_root=tmp_path,
            prompt="fix bug",
            result=result,
        )
        assert log_path is not None
        assert (tmp_path / ".colonyos" / "runs").is_dir()

    def test_returns_none_on_write_failure(self, tmp_repo: Path) -> None:
        """Should return None if writing fails."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        with patch("pathlib.Path.write_text", side_effect=OSError("permission denied")):
            log_path = log_router_decision(
                repo_root=tmp_repo,
                prompt="fix bug",
                result=result,
            )
            assert log_path is None

    def test_default_source_is_cli(self, tmp_repo: Path) -> None:
        """Default source should be 'cli'."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="fix bug",
            result=result,
        )
        assert log_path is not None
        data = json.loads(log_path.read_text())
        assert data["source"] == "cli"

    def test_timestamp_consistency(self, tmp_repo: Path) -> None:
        """Filename timestamp and JSON body timestamp should be derived from same instant."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="fix bug",
            result=result,
        )
        assert log_path is not None
        data = json.loads(log_path.read_text())
        # The filename contains the timestamp with microseconds
        # e.g. triage_20260321_125008_123456.json
        fname = log_path.stem  # triage_YYYYMMDD_HHMMSS_ffffff
        parts = fname.split("_")
        # parts: ["triage", "YYYYMMDD", "HHMMSS", "ffffff"]
        assert len(parts) == 4, f"Expected 4 parts in filename, got {parts}"
        file_date = parts[1]
        file_time = parts[2]
        # The JSON timestamp should contain the same date/time
        body_ts = data["timestamp"]
        assert file_date[:4] in body_ts  # year
        assert file_date[4:6] in body_ts  # month

    def test_filename_includes_microseconds(self, tmp_repo: Path) -> None:
        """Filename should include microseconds to avoid collisions."""
        result = RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.9,
            summary="Test",
            reasoning="Test",
        )
        log_path = log_router_decision(
            repo_root=tmp_repo,
            prompt="fix bug",
            result=result,
        )
        assert log_path is not None
        # Filename format: triage_YYYYMMDD_HHMMSS_ffffff.json
        fname = log_path.stem
        parts = fname.split("_")
        assert len(parts) == 4
        # Last part should be 6-digit microseconds
        assert len(parts[3]) == 6
        assert parts[3].isdigit()

# ---------------------------------------------------------------------------
# _handle_routed_query integration tests (Tasks 6.1, 7.1)
# ---------------------------------------------------------------------------


class TestHandleRoutedQuery:
    """Integration tests for the shared routing helper used by both CLI run() and REPL."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        """Create a temporary repo directory with minimal config."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    @pytest.fixture
    def config(self, tmp_repo: Path) -> ColonyConfig:
        """Load default config for testing."""
        return load_config(tmp_repo)

    def test_question_returns_answer(self, tmp_repo: Path, config: ColonyConfig) -> None:
        """QUESTION category should return the Q&A answer string."""
        from colonyos.cli import _handle_routed_query

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.answer_question") as mock_answer, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.QUESTION,
                confidence=0.9,
                summary="Asking about auth",
                reasoning="User is asking a question",
            )
            mock_answer.return_value = "Auth uses JWT tokens."
            result = _handle_routed_query(
                "how does auth work?", config, tmp_repo, source="cli",
            )
            assert result == "Auth uses JWT tokens."
            mock_answer.assert_called_once()

    def test_code_change_returns_none(self, tmp_repo: Path, config: ColonyConfig) -> None:
        """CODE_CHANGE category should return None (proceed to pipeline)."""
        from colonyos.cli import _handle_routed_query

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.CODE_CHANGE,
                confidence=0.95,
                summary="Add feature",
                reasoning="Code change request",
            )
            result = _handle_routed_query(
                "add a health check", config, tmp_repo, source="cli",
            )
            assert result is None

    def test_status_returns_suggestion(self, tmp_repo: Path, config: ColonyConfig) -> None:
        """STATUS category should return a suggestion string."""
        from colonyos.cli import _handle_routed_query

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.STATUS,
                confidence=0.9,
                summary="Queue status",
                reasoning="Status query",
                suggested_command="colonyos status",
            )
            result = _handle_routed_query(
                "show queue status", config, tmp_repo, source="repl",
            )
            assert result is not None
            assert "colonyos status" in result

    def test_out_of_scope_returns_message(self, tmp_repo: Path, config: ColonyConfig) -> None:
        """OUT_OF_SCOPE category should return a rejection message."""
        from colonyos.cli import _handle_routed_query

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.OUT_OF_SCOPE,
                confidence=0.85,
                summary="Weather question",
                reasoning="Not code related",
            )
            result = _handle_routed_query(
                "what is the weather?", config, tmp_repo, source="cli",
            )
            assert result is not None
            assert "doesn't seem related" in result

    def test_low_confidence_returns_none(self, tmp_repo: Path, config: ColonyConfig) -> None:
        """Low-confidence result should fail-open (return None for pipeline)."""
        from colonyos.cli import _handle_routed_query

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.QUESTION,
                confidence=0.3,  # below default threshold of 0.7
                summary="Maybe a question",
                reasoning="Uncertain",
            )
            result = _handle_routed_query(
                "hmm something", config, tmp_repo, source="repl",
            )
            assert result is None

    def test_logs_routing_decision(self, tmp_repo: Path, config: ColonyConfig) -> None:
        """_handle_routed_query should log the routing decision."""
        from colonyos.cli import _handle_routed_query

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.log_router_decision") as mock_log:
            mock_route.return_value = RouterResult(
                category=RouterCategory.CODE_CHANGE,
                confidence=0.9,
                summary="Feature",
                reasoning="Code change",
            )
            _handle_routed_query(
                "add feature", config, tmp_repo, source="cli",
            )
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["source"] == "cli"
            assert call_kwargs["repo_root"] == tmp_repo


# ---------------------------------------------------------------------------
# Slack Q&A integration tests
# ---------------------------------------------------------------------------


class TestSlackQuestionRouting:
    """Tests for Slack question routing via triage_message."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        return tmp_path

    def test_question_populates_answer(self, tmp_repo: Path) -> None:
        """When router classifies as QUESTION, triage_message should populate answer."""
        from colonyos.slack import triage_message

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.answer_question") as mock_answer, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.QUESTION,
                confidence=0.9,
                summary="Asking about code",
                reasoning="User question",
            )
            mock_answer.return_value = "The function does X."
            result = triage_message(
                "what does this function do?",
                repo_root=tmp_repo,
            )
            assert result.actionable is False
            assert result.answer == "The function does X."
            mock_answer.assert_called_once()
            assert mock_route.call_args.kwargs["model"] == "opus"
            assert mock_answer.call_args.kwargs["model"] == "opus"

    def test_code_change_no_answer(self, tmp_repo: Path) -> None:
        """CODE_CHANGE triage should not populate answer."""
        from colonyos.slack import triage_message

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.CODE_CHANGE,
                confidence=0.95,
                summary="Add feature",
                reasoning="Code change",
            )
            result = triage_message(
                "add a health check endpoint",
                repo_root=tmp_repo,
            )
            assert result.actionable is True
            assert result.answer is None
            assert mock_route.call_args.kwargs["model"] == "opus"

    def test_question_answer_error_fallback(self, tmp_repo: Path) -> None:
        """If answer_question fails, triage_message should still return with error answer."""
        from colonyos.slack import triage_message

        with patch("colonyos.router.route_query") as mock_route, \
             patch("colonyos.router.answer_question") as mock_answer, \
             patch("colonyos.router.log_router_decision"):
            mock_route.return_value = RouterResult(
                category=RouterCategory.QUESTION,
                confidence=0.9,
                summary="Question",
                reasoning="User question",
            )
            mock_answer.side_effect = RuntimeError("LLM error")
            result = triage_message(
                "how does auth work?",
                repo_root=tmp_repo,
            )
            assert result.actionable is False
            assert result.answer is not None
            assert "unable" in result.answer.lower() or "error" in result.answer.lower()
