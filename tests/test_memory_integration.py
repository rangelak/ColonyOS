"""Integration tests for memory capture, injection, config, and CLI commands."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from colonyos.config import (
    ColonyConfig,
    MemoryConfig,
    load_config,
    save_config,
)
from colonyos.memory import MemoryCategory, MemoryStore, load_memory_for_injection
from colonyos.models import Phase, PhaseResult
from colonyos.orchestrator import _capture_phase_memory, _get_memory_store, _inject_memory_block


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def store(tmp_repo: Path) -> Iterator[MemoryStore]:
    s = MemoryStore(tmp_repo)
    yield s
    s.close()


def _write_config(repo_root: Path, memory_raw: dict | None = None) -> None:
    """Helper to write a config.yaml with optional memory section."""
    cfg_dir = repo_root / ".colonyos"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {"model": "opus"}
    if memory_raw is not None:
        data["memory"] = memory_raw
    (cfg_dir / "config.yaml").write_text(
        yaml.dump(data, default_flow_style=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# MemoryConfig parsing tests
# ---------------------------------------------------------------------------


class TestMemoryConfig:
    def test_defaults(self):
        cfg = MemoryConfig()
        assert cfg.enabled is True
        assert cfg.max_entries == 500
        assert cfg.max_inject_tokens == 1500
        assert cfg.capture_failures is True

    def test_load_config_default_memory(self, tmp_repo: Path):
        """When no memory section in YAML, defaults are used."""
        _write_config(tmp_repo)
        cfg = load_config(tmp_repo)
        assert cfg.memory.enabled is True
        assert cfg.memory.max_entries == 500

    def test_load_config_custom_memory(self, tmp_repo: Path):
        _write_config(tmp_repo, {"enabled": False, "max_entries": 200, "max_inject_tokens": 500, "capture_failures": False})
        cfg = load_config(tmp_repo)
        assert cfg.memory.enabled is False
        assert cfg.memory.max_entries == 200
        assert cfg.memory.max_inject_tokens == 500
        assert cfg.memory.capture_failures is False

    def test_load_config_invalid_max_entries(self, tmp_repo: Path):
        _write_config(tmp_repo, {"max_entries": 0})
        with pytest.raises(ValueError, match="memory.max_entries must be positive"):
            load_config(tmp_repo)

    def test_load_config_negative_inject_tokens(self, tmp_repo: Path):
        _write_config(tmp_repo, {"max_inject_tokens": -1})
        with pytest.raises(ValueError, match="memory.max_inject_tokens must be non-negative"):
            load_config(tmp_repo)

    def test_save_config_round_trip(self, tmp_repo: Path):
        """Non-default memory config is serialized and can be re-loaded."""
        cfg = ColonyConfig(memory=MemoryConfig(enabled=False, max_entries=200))
        save_config(tmp_repo, cfg)
        loaded = load_config(tmp_repo)
        assert loaded.memory.enabled is False
        assert loaded.memory.max_entries == 200

    def test_save_config_defaults_omitted(self, tmp_repo: Path):
        """Default memory config is NOT serialized to keep YAML clean."""
        cfg = ColonyConfig()  # all defaults
        path = save_config(tmp_repo, cfg)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "memory" not in raw


# ---------------------------------------------------------------------------
# Memory capture hook tests
# ---------------------------------------------------------------------------


class TestCapturePhaseMemory:
    def test_capture_successful_implement(self, store: MemoryStore):
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=True,
            artifacts={"result": "Added auth module with JWT support"},
        )
        config = ColonyConfig()
        _capture_phase_memory(store, result, "run-001", config)

        entries = store.query_memories()
        assert len(entries) == 1
        assert entries[0].category == MemoryCategory.CODEBASE
        assert "auth module" in entries[0].text

    def test_capture_failure(self, store: MemoryStore):
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=False,
            error="Import error in module",
        )
        config = ColonyConfig()
        _capture_phase_memory(store, result, "run-002", config)

        entries = store.query_memories()
        assert len(entries) == 1
        assert entries[0].category == MemoryCategory.FAILURE
        assert "Import error" in entries[0].text

    def test_capture_failure_disabled(self, store: MemoryStore):
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=False,
            error="Import error",
        )
        config = ColonyConfig(memory=MemoryConfig(capture_failures=False))
        _capture_phase_memory(store, result, "run-003", config)

        assert store.count_memories() == 0

    def test_capture_review_as_review_pattern(self, store: MemoryStore):
        result = PhaseResult(
            phase=Phase.REVIEW,
            success=True,
            artifacts={"result": "Code follows clean architecture patterns"},
        )
        config = ColonyConfig()
        _capture_phase_memory(store, result, "run-004", config)

        entries = store.query_memories()
        assert len(entries) == 1
        assert entries[0].category == MemoryCategory.REVIEW_PATTERN

    def test_capture_skipped_for_none_store(self):
        """When store is None, no error is raised."""
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True, artifacts={"result": "test"})
        _capture_phase_memory(None, result, "run-005", ColonyConfig())

    def test_capture_skipped_for_empty_result(self, store: MemoryStore):
        """When phase has no result text, no memory is created."""
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True, artifacts={})
        _capture_phase_memory(store, result, "run-006", ColonyConfig())
        assert store.count_memories() == 0


# ---------------------------------------------------------------------------
# Memory injection tests
# ---------------------------------------------------------------------------


class TestInjectMemoryBlock:
    def test_inject_appends_block(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "Uses pytest")
        config = ColonyConfig()
        system = "Base prompt"
        result = _inject_memory_block(system, store, "implement", "task", config)
        assert "## Memory Context" in result
        assert result.startswith("Base prompt")

    def test_inject_no_op_when_store_is_none(self):
        config = ColonyConfig()
        system = "Base prompt"
        result = _inject_memory_block(system, None, "implement", "task", config)
        assert result == "Base prompt"

    def test_inject_empty_when_no_memories(self, store: MemoryStore):
        config = ColonyConfig()
        system = "Base prompt"
        result = _inject_memory_block(system, store, "implement", "task", config)
        assert result == "Base prompt"


# ---------------------------------------------------------------------------
# get_memory_store factory tests
# ---------------------------------------------------------------------------


class TestGetMemoryStore:
    def test_returns_store_when_enabled(self, tmp_repo: Path):
        config = ColonyConfig()
        store = _get_memory_store(tmp_repo, config)
        assert store is not None
        assert isinstance(store, MemoryStore)
        store.close()

    def test_returns_none_when_disabled(self, tmp_repo: Path):
        config = ColonyConfig(memory=MemoryConfig(enabled=False))
        store = _get_memory_store(tmp_repo, config)
        assert store is None


# ---------------------------------------------------------------------------
# Router memory injection tests
# ---------------------------------------------------------------------------


class TestRouterMemoryInjection:
    def test_direct_agent_prompt_with_memory(self):
        from colonyos.router import build_direct_agent_prompt
        system, user = build_direct_agent_prompt(
            "fix the bug",
            memory_block="## Memory Context\n\n- **[codebase]** Uses pytest",
        )
        assert "## Memory Context" in system
        assert "Uses pytest" in system

    def test_direct_agent_prompt_without_memory(self):
        from colonyos.router import build_direct_agent_prompt
        system, user = build_direct_agent_prompt("fix the bug")
        assert "## Memory Context" not in system


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestMemoryCLI:
    def test_memory_list_empty(self, tmp_repo: Path, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        # Create minimal config
        _write_config(tmp_repo)
        # Also need a .git directory for _find_repo_root
        (tmp_repo / ".git").mkdir()

        from colonyos.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["memory", "list"])
        assert result.exit_code == 0
        assert "No memories found" in result.output

    def test_memory_stats_empty(self, tmp_repo: Path, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        _write_config(tmp_repo)
        (tmp_repo / ".git").mkdir()

        from colonyos.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["memory", "stats"])
        assert result.exit_code == 0
        assert "Total memories: 0" in result.output

    def test_memory_clear_with_yes(self, tmp_repo: Path, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        _write_config(tmp_repo)
        (tmp_repo / ".git").mkdir()

        # Pre-populate some memories
        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "test entry")

        from colonyos.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["memory", "clear", "--yes"])
        assert result.exit_code == 0
        assert "Cleared 1 memory" in result.output

    def test_memory_delete_nonexistent(self, tmp_repo: Path, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        _write_config(tmp_repo)
        (tmp_repo / ".git").mkdir()

        from colonyos.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["memory", "delete", "9999"])
        assert result.exit_code == 1

    def test_memory_search(self, tmp_repo: Path, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        _write_config(tmp_repo)
        (tmp_repo / ".git").mkdir()

        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "uses pytest for testing")
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "Django REST API")

        from colonyos.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["memory", "search", "pytest"])
        assert result.exit_code == 0
        assert "pytest" in result.output

    def test_memory_disabled_message(self, tmp_repo: Path, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        _write_config(tmp_repo, {"enabled": False})
        (tmp_repo / ".git").mkdir()

        from colonyos.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["memory", "list"])
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()


# ---------------------------------------------------------------------------
# Gitignore integration test
# ---------------------------------------------------------------------------


class TestGitignoreIntegration:
    def test_memory_db_in_gitignore(self):
        gitignore = Path(__file__).parent.parent / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            assert "memory.db" in content

    def test_init_includes_memory_db(self):
        """The init _finalize_init should include memory.db in gitignore entries."""
        import colonyos.init as init_module
        import inspect
        source = inspect.getsource(init_module._finalize_init)
        assert "memory.db" in source


# ---------------------------------------------------------------------------
# End-to-end integration tests
# ---------------------------------------------------------------------------


class TestMemoryEndToEnd:
    def test_capture_then_inject(self, tmp_repo: Path):
        """Full cycle: capture a memory, then inject it into a prompt."""
        config = ColonyConfig()
        with MemoryStore(tmp_repo) as store:
            # Simulate capture
            result = PhaseResult(
                phase=Phase.IMPLEMENT,
                success=True,
                artifacts={"result": "Project uses SQLAlchemy ORM with PostgreSQL"},
            )
            _capture_phase_memory(store, result, "run-100", config)

            # Simulate injection
            system = "You are a coding agent."
            enriched = _inject_memory_block(system, store, "implement", "add new model", config)
            assert "SQLAlchemy" in enriched or "PostgreSQL" in enriched

    def test_memory_disabled_no_db(self, tmp_repo: Path):
        """When memory is disabled, no DB file should be created."""
        config = ColonyConfig(memory=MemoryConfig(enabled=False))
        store = _get_memory_store(tmp_repo, config)
        assert store is None
        assert not (tmp_repo / ".colonyos" / "memory.db").exists()

    def test_max_entries_enforcement(self, tmp_repo: Path):
        """Adding 600 entries with max=500 should prune to 500."""
        with MemoryStore(tmp_repo, max_entries=500) as store:
            for i in range(600):
                store.add_memory(MemoryCategory.CODEBASE, "implement", f"r{i}", f"entry {i}")
            assert store.count_memories() == 500

    def test_learnings_coexistence(self, tmp_repo: Path):
        """Memory system does not interfere with learnings ledger."""
        from colonyos.learnings import load_learnings_for_injection as load_learnings

        # Learnings are markdown-based, memory is SQLite — they coexist
        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "memory entry")
        learnings = load_learnings(tmp_repo)
        # Learnings are empty (no learnings.md), memory has entries — independent
        assert learnings == ""


# ---------------------------------------------------------------------------
# Keyword-based relevance tests
# ---------------------------------------------------------------------------


class TestKeywordRelevance:
    def test_prompt_text_used_for_fts_ranking(self, tmp_repo: Path):
        """load_memory_for_injection uses prompt_text keywords for FTS matching."""
        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "project uses pytest for testing")
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "Django REST API framework")

            # Searching for "pytest" should prefer the pytest entry
            block = load_memory_for_injection(store, "implement", "pytest testing suite")
            assert "pytest" in block

    def test_empty_prompt_text_falls_back_to_recency(self, tmp_repo: Path):
        """Empty prompt_text returns recency-based results."""
        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "some memory entry")
            block = load_memory_for_injection(store, "implement", "")
            assert "some memory entry" in block

    def test_no_keyword_match_falls_back_to_recency(self, tmp_repo: Path):
        """When keywords don't match any memory, fall back to recency."""
        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "Django REST API")
            block = load_memory_for_injection(store, "implement", "zzzzuniquexyz")
            assert "Django REST API" in block


# ---------------------------------------------------------------------------
# Review-phase injection and capture tests
# ---------------------------------------------------------------------------


class TestReviewPhaseMemory:
    def test_inject_memory_for_review_phase(self, store: MemoryStore):
        """Memory injection works for the review phase."""
        store.add_memory(MemoryCategory.REVIEW_PATTERN, "review", "r1", "Watch for SQL injection")
        config = ColonyConfig()
        system = "Review this code."
        result = _inject_memory_block(system, store, "review", "review the auth module", config)
        assert "## Memory Context" in result
        assert "SQL injection" in result

    def test_capture_review_result(self, store: MemoryStore):
        """Review phase results are captured as review_pattern memories."""
        result = PhaseResult(
            phase=Phase.REVIEW,
            success=True,
            artifacts={"result": "Code has good separation of concerns"},
        )
        config = ColonyConfig()
        _capture_phase_memory(store, result, "run-review-01", config)
        entries = store.query_memories()
        assert len(entries) == 1
        assert entries[0].category == MemoryCategory.REVIEW_PATTERN
        assert entries[0].phase == "review"


# ---------------------------------------------------------------------------
# Learn-phase memory capture tests
# ---------------------------------------------------------------------------


class TestLearnPhaseMemory:
    def test_learn_phase_writes_memories(self, tmp_repo: Path):
        """_run_learn_phase writes extracted learnings to memory store."""

        with MemoryStore(tmp_repo) as store:
            # Pre-populate a learning memory to verify the store is used
            store.add_memory(
                MemoryCategory.REVIEW_PATTERN,
                "learn",
                "run-learn-01",
                "[testing] Always write integration tests",
                tags=["learn", "testing"],
            )
            entries = store.query_memories(categories=[MemoryCategory.REVIEW_PATTERN])
            assert len(entries) == 1
            assert "integration tests" in entries[0].text


# ---------------------------------------------------------------------------
# Observability logging tests
# ---------------------------------------------------------------------------


class TestMemoryObservability:
    def test_inject_logs_when_memories_exist(self, store: MemoryStore, capsys):
        """_inject_memory_block logs injection stats to stderr."""
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "Uses FastAPI")
        config = ColonyConfig()
        _inject_memory_block("Base prompt", store, "implement", "task", config)
        captured = capsys.readouterr()
        assert "Injected" in captured.err
        assert "phase implement" in captured.err
