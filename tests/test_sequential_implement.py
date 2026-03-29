"""Tests for sequential (per-task) implement mode (Tasks 2.0 / 3.0 / 5.0 / 6.0)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import ColonyConfig, ParallelImplementConfig, load_config
from colonyos.dag import TaskDAG, parse_task_file
from colonyos.models import Phase, PhaseResult, RunLog, RunStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_TASK_FILE = textwrap.dedent("""\
    # Tasks

    - [ ] 1.0 Add user model
      depends_on: []
    - [ ] 2.0 Add authentication
      depends_on: [1.0]
    - [ ] 3.0 Add API endpoints
      depends_on: [2.0]
""")

INDEPENDENT_TASK_FILE = textwrap.dedent("""\
    # Tasks

    - [ ] 1.0 Add logging
      depends_on: []
    - [ ] 2.0 Add metrics
      depends_on: []
    - [ ] 3.0 Add dashboard
      depends_on: [1.0, 2.0]
""")

NO_TASKS_FILE = textwrap.dedent("""\
    # Tasks

    No tasks defined yet.
""")


def _make_phase_result(success: bool = True, cost: float = 0.50) -> PhaseResult:
    return PhaseResult(
        phase=Phase.IMPLEMENT,
        success=success,
        cost_usd=cost,
        duration_ms=1000,
        artifacts={},
        error=None if success else "task failed",
    )


def _make_run_log() -> RunLog:
    return RunLog(
        run_id="test-run-001",
        status=RunStatus.RUNNING,
        prompt="test",
        branch_name="test-branch",
        phases=[],
    )


def _setup_repo(tmp_path: Path, task_content: str) -> tuple[Path, str, str]:
    """Create a minimal repo structure for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    prd_dir = repo / "cOS_prds"
    prd_dir.mkdir()
    (prd_dir / "test.md").write_text("# PRD\nTest feature.")

    task_dir = repo / "cOS_tasks"
    task_dir.mkdir()
    (task_dir / "test_tasks.md").write_text(task_content)

    # Create instructions directory with implement.md
    instr_dir = repo / "src" / "colonyos" / "instructions"
    instr_dir.mkdir(parents=True)
    (instr_dir / "implement.md").write_text(
        "Implement feature.\n"
        "PRD: {prd_path}\nTasks: {task_path}\nBranch: {branch_name}"
    )
    (instr_dir / "base.md").write_text("You are a coding assistant.")

    return repo, "cOS_prds/test.md", "cOS_tasks/test_tasks.md"


# ---------------------------------------------------------------------------
# Task 1.0 — Default config is sequential (parallel disabled)
# ---------------------------------------------------------------------------


class TestDefaultConfigIsSequential:
    def test_parallel_implement_disabled_by_default(self, tmp_path: Path) -> None:
        config = load_config(tmp_path)
        assert config.parallel_implement.enabled is False

    def test_parallel_implement_config_dataclass_default(self) -> None:
        pic = ParallelImplementConfig()
        assert pic.enabled is False


# ---------------------------------------------------------------------------
# Task 2.0 — Sequential runner: DAG parsing and topological order
# ---------------------------------------------------------------------------


class TestSequentialTaskOrder:
    def test_simple_chain_topological_order(self) -> None:
        deps = parse_task_file(SIMPLE_TASK_FILE)
        dag = TaskDAG(dependencies=deps)
        order = dag.topological_sort()
        assert order == ["1.0", "2.0", "3.0"]

    def test_independent_tasks_come_before_dependent(self) -> None:
        deps = parse_task_file(INDEPENDENT_TASK_FILE)
        dag = TaskDAG(dependencies=deps)
        order = dag.topological_sort()
        # 1.0 and 2.0 must both precede 3.0
        assert order.index("1.0") < order.index("3.0")
        assert order.index("2.0") < order.index("3.0")

    def test_empty_task_file_returns_empty(self) -> None:
        deps = parse_task_file(NO_TASKS_FILE)
        assert deps == {}

    def test_per_task_budget_allocation(self) -> None:
        """Budget should be evenly divided among tasks."""
        deps = parse_task_file(SIMPLE_TASK_FILE)
        task_count = len(deps)
        phase_budget = 6.0
        per_task = phase_budget / task_count
        assert per_task == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Task 3.0 — Failure handling / DAG-aware skip logic
# ---------------------------------------------------------------------------


class TestDAGAwareSkipLogic:
    def test_failed_task_blocks_dependents(self) -> None:
        """If task 1.0 fails, tasks 2.0 and 3.0 should be BLOCKED."""
        deps = parse_task_file(SIMPLE_TASK_FILE)
        dag = TaskDAG(dependencies=deps)

        completed: set[str] = set()
        failed: set[str] = {"1.0"}
        blocked: set[str] = set()

        for task_id in dag.topological_sort():
            if task_id in failed:
                continue
            task_deps = dag.dependencies.get(task_id, [])
            blocked_by = [d for d in task_deps if d in failed or d in blocked]
            if blocked_by:
                blocked.add(task_id)

        assert "2.0" in blocked
        assert "3.0" in blocked

    def test_independent_tasks_continue_after_failure(self) -> None:
        """Independent tasks should not be blocked by unrelated failures."""
        deps = parse_task_file(INDEPENDENT_TASK_FILE)
        dag = TaskDAG(dependencies=deps)

        completed: set[str] = set()
        failed: set[str] = {"1.0"}
        blocked: set[str] = set()

        for task_id in dag.topological_sort():
            if task_id in failed:
                continue
            task_deps = dag.dependencies.get(task_id, [])
            blocked_by = [d for d in task_deps if d in failed or d in blocked]
            if blocked_by:
                blocked.add(task_id)
            else:
                completed.add(task_id)

        # 2.0 is independent of 1.0, so it should complete
        assert "2.0" in completed
        # 3.0 depends on both 1.0 and 2.0; 1.0 failed → blocked
        assert "3.0" in blocked

    def test_transitive_dependency_skip(self) -> None:
        """If A fails, B (depends on A) is blocked, C (depends on B) is also blocked."""
        deps = parse_task_file(SIMPLE_TASK_FILE)
        dag = TaskDAG(dependencies=deps)

        failed: set[str] = {"1.0"}
        blocked: set[str] = set()

        for task_id in dag.topological_sort():
            if task_id in failed:
                continue
            task_deps = dag.dependencies.get(task_id, [])
            blocked_by = [d for d in task_deps if d in failed or d in blocked]
            if blocked_by:
                blocked.add(task_id)

        # 2.0 blocked because 1.0 failed
        assert "2.0" in blocked
        # 3.0 blocked because 2.0 is blocked
        assert "3.0" in blocked


# ---------------------------------------------------------------------------
# Task 5.0 — Single-task prompt builder
# ---------------------------------------------------------------------------


class TestSingleTaskPromptBuilder:
    def test_prompt_includes_task_id(self) -> None:
        from colonyos.orchestrator import _build_single_task_implement_prompt

        config = ColonyConfig()
        system, user = _build_single_task_implement_prompt(
            config,
            task_id="2.0",
            task_description="Add authentication",
            prd_path="cOS_prds/test.md",
            task_path="cOS_tasks/test.md",
            branch_name="feature/test",
            completed_tasks=[],
        )
        assert "2.0" in user
        assert "Add authentication" in user

    def test_prompt_includes_completed_tasks_context(self) -> None:
        from colonyos.orchestrator import _build_single_task_implement_prompt

        config = ColonyConfig()
        system, user = _build_single_task_implement_prompt(
            config,
            task_id="2.0",
            task_description="Add authentication",
            prd_path="cOS_prds/test.md",
            task_path="cOS_tasks/test.md",
            branch_name="feature/test",
            completed_tasks=["1.0: Add user model"],
        )
        assert "Previously Completed Tasks" in system
        assert "1.0: Add user model" in system

    def test_prompt_no_completed_tasks_omits_section(self) -> None:
        from colonyos.orchestrator import _build_single_task_implement_prompt

        config = ColonyConfig()
        system, user = _build_single_task_implement_prompt(
            config,
            task_id="1.0",
            task_description="Add user model",
            prd_path="cOS_prds/test.md",
            task_path="cOS_tasks/test.md",
            branch_name="feature/test",
            completed_tasks=[],
        )
        assert "Previously Completed Tasks" not in system

    def test_prompt_tells_agent_to_focus_on_single_task(self) -> None:
        from colonyos.orchestrator import _build_single_task_implement_prompt

        config = ColonyConfig()
        _system, user = _build_single_task_implement_prompt(
            config,
            task_id="2.0",
            task_description="Add auth",
            prd_path="cOS_prds/test.md",
            task_path="cOS_tasks/test.md",
            branch_name="feature/test",
            completed_tasks=["1.0: Setup"],
        )
        assert "ONLY task 2.0" in user
        assert "Do not implement other tasks" in user


# ---------------------------------------------------------------------------
# Task 2.0 + 3.0 — _run_sequential_implement integration
# ---------------------------------------------------------------------------


class TestRunSequentialImplement:
    """Tests that exercise _run_sequential_implement with mocked agent calls."""

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_all_tasks_succeed(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(
            returncode=0, stdout="file.py\n",
        )

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        assert result.success is True
        assert result.artifacts["completed"] == "3"
        assert result.artifacts["failed"] == "0"
        assert result.artifacts["blocked"] == "0"
        assert result.artifacts["mode"] == "sequential"
        # run_phase_sync called once per task
        assert mock_run.call_count == 3

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_first_task_fails_blocks_chain(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        # First call fails, rest would succeed
        mock_run.side_effect = [
            _make_phase_result(success=False, cost=0.5),
        ]
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        assert result.success is False
        assert result.artifacts["completed"] == "0"
        assert result.artifacts["failed"] == "1"
        assert result.artifacts["blocked"] == "2"
        # Only 1 agent call (for task 1.0); 2.0 and 3.0 are blocked
        assert mock_run.call_count == 1
        # Verify blocked status in task_results
        task_results = result.artifacts["task_results"]
        assert task_results["2.0"]["status"] == "BLOCKED"
        assert task_results["3.0"]["status"] == "BLOCKED"

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_independent_tasks_continue_on_failure(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, INDEPENDENT_TASK_FILE)
        # Task 1.0 fails, 2.0 succeeds, 3.0 would be blocked (depends on 1.0)
        mock_run.side_effect = [
            _make_phase_result(success=False, cost=0.5),  # 1.0 fails
            _make_phase_result(success=True, cost=1.0),   # 2.0 succeeds
        ]
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        assert result.success is False  # overall fails because 1.0 failed
        assert result.artifacts["completed"] == "1"  # 2.0 completed
        assert result.artifacts["failed"] == "1"     # 1.0 failed
        assert result.artifacts["blocked"] == "1"    # 3.0 blocked
        # 2 agent calls: 1.0 and 2.0; 3.0 is blocked
        assert mock_run.call_count == 2

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_no_tasks_returns_none(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, NO_TASKS_FILE)

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is None
        assert mock_run.call_count == 0

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_missing_task_file_returns_none(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo = tmp_path / "repo"
        repo.mkdir()

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel="nonexistent/tasks.md",
            task_rel="nonexistent/tasks.md",
            _make_ui=lambda: None,
        )

        assert result is None

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_per_task_budget_is_divided(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")

        log = _make_run_log()
        config = ColonyConfig()
        # Default per_phase budget is 5.0, 3 tasks → ~1.67 per task

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        # Verify budget_usd kwarg passed to run_phase_sync
        for call in mock_run.call_args_list:
            budget = call.kwargs.get("budget_usd", call[1].get("budget_usd"))
            expected = config.budget.per_phase / 3
            assert budget == pytest.approx(expected)

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_commits_after_each_successful_task(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")

        log = _make_run_log()
        config = ColonyConfig()

        _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        # Each successful task triggers:
        #   git diff --name-only + git ls-files + git add + git commit = 4 calls
        # 3 tasks × 4 = 12 subprocess calls
        assert mock_subprocess.run.call_count == 12

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_agent_exception_marks_task_failed(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        mock_run.side_effect = RuntimeError("agent crashed")
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        assert result.success is False
        assert result.artifacts["failed"] == "1"
        task_results = result.artifacts["task_results"]
        assert task_results["1.0"]["status"] == "FAILED"
        assert "agent crashed" in task_results["1.0"]["error"]


# ---------------------------------------------------------------------------
# Security — selective staging filters out sensitive files
# ---------------------------------------------------------------------------


class TestSelectiveStagingSecurity:
    """Tests for the security fix: git add -A replaced with selective staging."""

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_secret_files_excluded_from_staging(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Sensitive files like .env must not be staged."""
        from colonyos.orchestrator import _run_sequential_implement

        single_task = textwrap.dedent("""\
            # Tasks
            - [ ] 1.0 Add feature
              depends_on: []
        """)
        repo, prd_rel, task_rel = _setup_repo(tmp_path, single_task)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)

        # git diff returns a mix of safe and secret files
        diff_mock = MagicMock(returncode=0, stdout="app.py\n.env\ncredentials.json\n")
        untracked_mock = MagicMock(returncode=0, stdout="new_file.py\nid_rsa\n")
        commit_mock = MagicMock(returncode=0, stdout="")
        add_mock = MagicMock(returncode=0, stdout="")
        mock_subprocess.run.side_effect = [diff_mock, untracked_mock, add_mock, commit_mock]

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        assert result.success is True

        # Verify git add was called with only safe files (not .env, credentials.json, id_rsa)
        add_call = mock_subprocess.run.call_args_list[2]
        staged_cmd = add_call[0][0]
        assert staged_cmd[0:3] == ["git", "add", "--"]
        staged_files = staged_cmd[3:]
        assert "app.py" in staged_files
        assert "new_file.py" in staged_files
        assert ".env" not in staged_files
        assert "credentials.json" not in staged_files
        assert "id_rsa" not in staged_files

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_no_files_to_stage_skips_git_add(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """When only secret files are changed, git add should be skipped."""
        from colonyos.orchestrator import _run_sequential_implement

        single_task = textwrap.dedent("""\
            # Tasks
            - [ ] 1.0 Add feature
              depends_on: []
        """)
        repo, prd_rel, task_rel = _setup_repo(tmp_path, single_task)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)

        # Only secret files changed
        diff_mock = MagicMock(returncode=0, stdout=".env\n")
        untracked_mock = MagicMock(returncode=0, stdout="")
        commit_mock = MagicMock(returncode=0, stdout="")
        mock_subprocess.run.side_effect = [diff_mock, untracked_mock, commit_mock]

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        # 3 subprocess calls: diff, ls-files, commit (no git add)
        assert mock_subprocess.run.call_count == 3

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_subprocess_calls_have_timeout(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """All subprocess calls in the commit step must have timeout=30."""
        from colonyos.orchestrator import _run_sequential_implement

        single_task = textwrap.dedent("""\
            # Tasks
            - [ ] 1.0 Add feature
              depends_on: []
        """)
        repo, prd_rel, task_rel = _setup_repo(tmp_path, single_task)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(
            returncode=0, stdout="file.py\n",
        )

        log = _make_run_log()
        config = ColonyConfig()

        _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        for call in mock_subprocess.run.call_args_list:
            assert call.kwargs.get("timeout") == 30, (
                f"Missing timeout=30 in subprocess call: {call}"
            )

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_commit_message_sanitizes_task_description(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Task descriptions used in commit messages must be sanitized."""
        from colonyos.orchestrator import _run_sequential_implement

        # Task description with XML-like injection
        injected_task = textwrap.dedent("""\
            # Tasks
            - [ ] 1.0 <script>alert('xss')</script> Add feature
              depends_on: []
        """)
        repo, prd_rel, task_rel = _setup_repo(tmp_path, injected_task)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(
            returncode=0, stdout="file.py\n",
        )

        log = _make_run_log()
        config = ColonyConfig()

        _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        # Find the git commit call and check the message is sanitized
        commit_calls = [
            c for c in mock_subprocess.run.call_args_list
            if c[0][0][0:2] == ["git", "commit"]
        ]
        assert len(commit_calls) == 1
        commit_msg = commit_calls[0][0][0][3]  # -m argument
        assert "<script>" not in commit_msg


# ---------------------------------------------------------------------------
# Task 4.0 — Parallel mode still works as opt-in
# ---------------------------------------------------------------------------


class TestParallelStillWorksAsOptIn:
    def test_parallel_enabled_when_explicitly_set(self, tmp_path: Path) -> None:
        config = ColonyConfig(
            parallel_implement=ParallelImplementConfig(enabled=True)
        )
        assert config.parallel_implement.enabled is True

    def test_parallel_disabled_by_default(self) -> None:
        config = ColonyConfig()
        assert config.parallel_implement.enabled is False


# ---------------------------------------------------------------------------
# Memory injection and context trimming
# ---------------------------------------------------------------------------


class TestMemoryInjectionAndContextTrimming:
    """Tests for _inject_memory_block / _drain_injected_context wiring and context caps."""

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    @patch("colonyos.orchestrator._inject_memory_block")
    @patch("colonyos.orchestrator._drain_injected_context")
    def test_memory_block_injected_per_task(
        self,
        mock_drain: MagicMock,
        mock_inject: MagicMock,
        mock_subprocess: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        """_inject_memory_block should be called once per task."""
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")
        mock_inject.side_effect = lambda system, *args, **kwargs: system
        mock_drain.return_value = ""

        fake_store = MagicMock()
        log = _make_run_log()
        config = ColonyConfig()

        _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
            memory_store=fake_store,
        )

        # Called once per task (3 tasks)
        assert mock_inject.call_count == 3
        # Each call passes the memory_store and phase="implement"
        for call in mock_inject.call_args_list:
            assert call[0][1] is fake_store
            assert call[0][2] == "implement"

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    @patch("colonyos.orchestrator._inject_memory_block")
    @patch("colonyos.orchestrator._drain_injected_context")
    def test_drain_injected_context_called_per_task(
        self,
        mock_drain: MagicMock,
        mock_inject: MagicMock,
        mock_subprocess: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        """_drain_injected_context should be called once per task."""
        from colonyos.orchestrator import _run_sequential_implement

        repo, prd_rel, task_rel = _setup_repo(tmp_path, SIMPLE_TASK_FILE)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="file.py\n")
        mock_inject.side_effect = lambda system, *args, **kwargs: system
        mock_drain.return_value = ""

        fake_provider = MagicMock(return_value=[])
        log = _make_run_log()
        config = ColonyConfig()

        _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
            user_injection_provider=fake_provider,
        )

        # Called once per task (3 tasks)
        assert mock_drain.call_count == 3
        for call in mock_drain.call_args_list:
            assert call[0][0] is fake_provider

    def test_completed_tasks_trimmed_above_10(self) -> None:
        """When more than 10 tasks are completed, only the last 10 should appear."""
        from colonyos.orchestrator import _build_single_task_implement_prompt

        config = ColonyConfig()
        # Use unique names that aren't substrings of each other
        completed = [f"task_{i:03d}: Implement feature {i:03d}" for i in range(1, 16)]  # 15 tasks
        system, _user = _build_single_task_implement_prompt(
            config,
            task_id="16.0",
            task_description="Final task",
            prd_path="cOS_prds/test.md",
            task_path="cOS_tasks/test.md",
            branch_name="feature/test",
            completed_tasks=completed,
        )
        assert "Previously Completed Tasks" in system
        # The first 5 tasks should be omitted
        assert "task_001: Implement feature 001" not in system
        assert "task_005: Implement feature 005" not in system
        # The last 10 should be present
        assert "task_006: Implement feature 006" in system
        assert "task_015: Implement feature 015" in system
        # Omission notice
        assert "5 earlier task(s) omitted" in system

    def test_completed_tasks_not_trimmed_at_10(self) -> None:
        """Exactly 10 completed tasks should all appear without trimming."""
        from colonyos.orchestrator import _build_single_task_implement_prompt

        config = ColonyConfig()
        completed = [f"{i}.0: Task {i}" for i in range(1, 11)]  # 10 tasks
        system, _user = _build_single_task_implement_prompt(
            config,
            task_id="11.0",
            task_description="Next task",
            prd_path="cOS_prds/test.md",
            task_path="cOS_tasks/test.md",
            branch_name="feature/test",
            completed_tasks=completed,
        )
        assert "omitted" not in system
        assert "1.0: Task 1" in system
        assert "10.0: Task 10" in system


class TestGitReturnCodeChecking:
    """Tests that git diff/ls-files failures are handled gracefully."""

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.subprocess")
    def test_git_diff_failure_skips_diff_files(
        self, mock_subprocess: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """When git diff fails, its output should be ignored (not staged)."""
        from colonyos.orchestrator import _run_sequential_implement

        single_task = textwrap.dedent("""\
            # Tasks
            - [ ] 1.0 Add feature
              depends_on: []
        """)
        repo, prd_rel, task_rel = _setup_repo(tmp_path, single_task)
        mock_run.return_value = _make_phase_result(success=True, cost=1.0)

        # git diff fails, but ls-files works
        diff_mock = MagicMock(returncode=128, stdout="bad.py\n", stderr="fatal: error")
        untracked_mock = MagicMock(returncode=0, stdout="new_file.py\n")
        add_mock = MagicMock(returncode=0, stdout="")
        commit_mock = MagicMock(returncode=0, stdout="")
        mock_subprocess.run.side_effect = [diff_mock, untracked_mock, add_mock, commit_mock]

        log = _make_run_log()
        config = ColonyConfig()

        result = _run_sequential_implement(
            log=log,
            repo_root=repo,
            config=config,
            branch_name="test-branch",
            prd_rel=prd_rel,
            task_rel=task_rel,
            _make_ui=lambda: None,
        )

        assert result is not None
        assert result.success is True
        # git add should only include untracked file, not the diff file
        add_call = mock_subprocess.run.call_args_list[2]
        staged_files = add_call[0][0][3:]  # after ["git", "add", "--"]
        assert "new_file.py" in staged_files
        assert "bad.py" not in staged_files
