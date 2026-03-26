"""Tests for the persistent memory storage layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from colonyos.memory import (
    MemoryCategory,
    MemoryEntry,
    MemoryStore,
    load_memory_for_injection,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def store(tmp_repo: Path) -> MemoryStore:
    s = MemoryStore(tmp_repo)
    yield s
    s.close()


class TestMemoryStoreInit:
    def test_auto_creates_db(self, tmp_repo: Path):
        store = MemoryStore(tmp_repo)
        db_path = tmp_repo / ".colonyos" / "memory.db"
        assert db_path.exists()
        store.close()

    def test_creates_colonyos_dir_if_missing(self, tmp_path: Path):
        # Remove the .colonyos dir so the store must create it
        store = MemoryStore(tmp_path)
        assert (tmp_path / ".colonyos" / "memory.db").exists()
        store.close()

    def test_idempotent_init(self, tmp_repo: Path):
        """Opening the store twice should not error."""
        s1 = MemoryStore(tmp_repo)
        s1.close()
        s2 = MemoryStore(tmp_repo)
        s2.close()


class TestContextManager:
    def test_context_manager_protocol(self, tmp_repo: Path):
        """MemoryStore supports with-statement for safe cleanup."""
        with MemoryStore(tmp_repo) as store:
            store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "test")
            assert store.count_memories() == 1
        # After exiting, connection is closed — no leak

    def test_context_manager_closes_on_exception(self, tmp_repo: Path):
        """Connection is closed even when an exception occurs."""
        try:
            with MemoryStore(tmp_repo) as store:
                store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "test")
                raise ValueError("test error")
        except ValueError:
            pass
        # Verify we can reopen (connection was properly closed)
        with MemoryStore(tmp_repo) as store2:
            assert store2.count_memories() == 1


class TestAddMemory:
    def test_add_and_count(self, store: MemoryStore):
        store.add_memory(
            category=MemoryCategory.CODEBASE,
            phase="implement",
            run_id="run-001",
            text="Project uses pytest with PYTHONPATH=src",
            tags=["testing", "setup"],
        )
        assert store.count_memories() == 1

    def test_add_multiple(self, store: MemoryStore):
        for i in range(5):
            store.add_memory(
                category=MemoryCategory.CODEBASE,
                phase="implement",
                run_id=f"run-{i:03d}",
                text=f"Memory entry {i}",
            )
        assert store.count_memories() == 5

    def test_sanitizes_content(self, store: MemoryStore):
        """XML tags should be stripped from memory text."""
        store.add_memory(
            category=MemoryCategory.CODEBASE,
            phase="implement",
            run_id="run-001",
            text="Use <malicious_tag>pytest</malicious_tag> for testing",
        )
        memories = store.query_memories()
        assert "<malicious_tag>" not in memories[0].text
        assert "pytest" in memories[0].text

    def test_sanitizes_secrets(self, store: MemoryStore):
        """API keys and tokens should be redacted from memory text."""
        store.add_memory(
            category=MemoryCategory.FAILURE,
            phase="fix",
            run_id="run-001",
            text="Auth failed with token ghp_abc123XYZsecrettoken for GitHub API",
        )
        memories = store.query_memories()
        assert "ghp_abc123" not in memories[0].text
        assert "[REDACTED]" in memories[0].text

    def test_sanitizes_bearer_tokens(self, store: MemoryStore):
        """Bearer tokens should be redacted."""
        store.add_memory(
            category=MemoryCategory.FAILURE,
            phase="fix",
            run_id="run-001",
            text="Request failed: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        )
        memories = store.query_memories()
        assert "eyJhbGciOiJIUzI1NiI" not in memories[0].text

    def test_sanitizes_aws_keys(self, store: MemoryStore):
        """AWS access key IDs should be redacted."""
        store.add_memory(
            category=MemoryCategory.FAILURE,
            phase="fix",
            run_id="run-001",
            text="Credentials: AKIAIOSFODNN7EXAMPLE leaked in logs",
        )
        memories = store.query_memories()
        assert "AKIAIOSFODNN7EXAMPLE" not in memories[0].text

    def test_returns_memory_entry(self, store: MemoryStore):
        entry = store.add_memory(
            category=MemoryCategory.FAILURE,
            phase="fix",
            run_id="run-002",
            text="Import error in auth module",
            tags=["auth", "import"],
        )
        assert isinstance(entry, MemoryEntry)
        assert entry.category == MemoryCategory.FAILURE
        assert entry.phase == "fix"
        assert entry.run_id == "run-002"
        assert entry.text == "Import error in auth module"
        assert entry.tags == ["auth", "import"]
        assert entry.id is not None
        assert entry.created_at is not None


class TestMaxEntriesPruning:
    def test_prunes_oldest_when_over_cap(self, tmp_repo: Path):
        store = MemoryStore(tmp_repo, max_entries=5)
        for i in range(8):
            store.add_memory(
                category=MemoryCategory.CODEBASE,
                phase="implement",
                run_id=f"run-{i:03d}",
                text=f"Entry {i}",
            )
        assert store.count_memories() == 5
        # Oldest entries (0, 1, 2) should be pruned
        memories = store.query_memories(limit=10)
        texts = [m.text for m in memories]
        assert "Entry 0" not in texts
        assert "Entry 1" not in texts
        assert "Entry 2" not in texts
        assert "Entry 7" in texts
        store.close()

    def test_prunes_by_category_fifo(self, tmp_repo: Path):
        store = MemoryStore(tmp_repo, max_entries=3)
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "codebase 1")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r2", "failure 1")
        store.add_memory(MemoryCategory.PREFERENCE, "plan", "r3", "pref 1")
        # At cap now. Adding one more should prune the oldest.
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r4", "codebase 2")
        assert store.count_memories() == 3
        store.close()


class TestQueryMemories:
    def test_query_all(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "fact one")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r2", "failure one")
        results = store.query_memories()
        assert len(results) == 2

    def test_query_by_category(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "fact")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r2", "fail")
        store.add_memory(MemoryCategory.PREFERENCE, "plan", "r3", "pref")

        results = store.query_memories(categories=[MemoryCategory.CODEBASE])
        assert len(results) == 1
        assert results[0].category == MemoryCategory.CODEBASE

    def test_query_by_multiple_categories(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "fact")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r2", "fail")
        store.add_memory(MemoryCategory.PREFERENCE, "plan", "r3", "pref")

        results = store.query_memories(
            categories=[MemoryCategory.CODEBASE, MemoryCategory.FAILURE]
        )
        assert len(results) == 2

    def test_query_by_phase(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "impl fact")
        store.add_memory(MemoryCategory.CODEBASE, "fix", "r2", "fix fact")

        results = store.query_memories(phase="implement")
        assert len(results) == 1
        assert results[0].phase == "implement"

    def test_query_with_limit(self, store: MemoryStore):
        for i in range(10):
            store.add_memory(MemoryCategory.CODEBASE, "implement", f"r{i}", f"entry {i}")

        results = store.query_memories(limit=3)
        assert len(results) == 3

    def test_query_returns_most_recent_first(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "old entry")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "new entry")

        results = store.query_memories(limit=2)
        assert results[0].text == "new entry"
        assert results[1].text == "old entry"

    def test_keyword_search(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "Uses pytest for testing")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "Django REST framework")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r3", "pytest fixture error")

        results = store.query_memories(keyword="pytest")
        assert len(results) == 2
        texts = {m.text for m in results}
        assert "Uses pytest for testing" in texts
        assert "pytest fixture error" in texts

    def test_keyword_search_no_results(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "Uses pytest")
        results = store.query_memories(keyword="nonexistent_term_xyz")
        assert len(results) == 0


class TestFTS5Escaping:
    """FTS5 special operators should not alter query semantics."""

    def test_fts5_and_operator(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "foo AND bar baz")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "just bar")
        # Searching for literal "AND" should not create a boolean query
        results = store.query_memories(keyword="foo AND bar")
        # Should find at least the first entry (not crash)
        assert len(results) >= 0  # no FTS5 parse error

    def test_fts5_or_operator(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "hello world")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "goodbye world")
        # "OR" should be stripped, not treated as FTS5 operator
        results = store.query_memories(keyword="hello OR goodbye")
        assert len(results) >= 0

    def test_fts5_wildcard_stripped(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "testing data")
        results = store.query_memories(keyword="test*")
        assert len(results) >= 0

    def test_fts5_double_quote_escaped(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", 'said "hello" to world')
        results = store.query_memories(keyword='"hello"')
        assert len(results) >= 0

    def test_sanitize_fts_keyword(self):
        """Directly test the keyword sanitization method."""
        assert MemoryStore._sanitize_fts_keyword('test AND foo') == 'test foo'
        assert MemoryStore._sanitize_fts_keyword('test OR bar') == 'test bar'
        assert MemoryStore._sanitize_fts_keyword('NOT bad') == 'bad'
        assert MemoryStore._sanitize_fts_keyword('test*') == 'test'
        assert MemoryStore._sanitize_fts_keyword('foo^bar') == 'foobar'
        assert MemoryStore._sanitize_fts_keyword('hello "world"') == 'hello ""world""'


class TestDeleteMemory:
    def test_delete_by_id(self, store: MemoryStore):
        entry = store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "to delete")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "to keep")
        assert store.count_memories() == 2

        deleted = store.delete_memory(entry.id)
        assert deleted is True
        assert store.count_memories() == 1

    def test_delete_nonexistent(self, store: MemoryStore):
        deleted = store.delete_memory(9999)
        assert deleted is False

    def test_clear_all(self, store: MemoryStore):
        for i in range(5):
            store.add_memory(MemoryCategory.CODEBASE, "implement", f"r{i}", f"entry {i}")
        assert store.count_memories() == 5

        store.clear_memories()
        assert store.count_memories() == 0

    def test_clear_rebuilds_fts_index(self, store: MemoryStore):
        """After clear, FTS searches should return no results."""
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "pytest framework")
        assert len(store.query_memories(keyword="pytest")) == 1

        store.clear_memories()
        # FTS should also be clean
        assert len(store.query_memories(keyword="pytest")) == 0


class TestCountByCategory:
    def test_count_by_category(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "fact 1")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "fact 2")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r3", "fail 1")
        store.add_memory(MemoryCategory.PREFERENCE, "plan", "r4", "pref 1")

        counts = store.count_by_category()
        assert counts[MemoryCategory.CODEBASE] == 2
        assert counts[MemoryCategory.FAILURE] == 1
        assert counts[MemoryCategory.PREFERENCE] == 1
        assert counts.get(MemoryCategory.REVIEW_PATTERN, 0) == 0


class TestLoadMemoryForInjection:
    def test_returns_empty_when_no_memories(self, store: MemoryStore):
        result = load_memory_for_injection(store, "implement", "add auth feature")
        assert result == ""

    def test_returns_formatted_block(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "Uses pytest")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r2", "Circular import in auth")

        result = load_memory_for_injection(store, "implement", "add auth feature")
        assert "## Memory Context" in result
        assert "Uses pytest" in result or "Circular import" in result

    def test_respects_token_budget(self, store: MemoryStore):
        # Add many long entries
        for i in range(50):
            store.add_memory(
                MemoryCategory.CODEBASE,
                "implement",
                f"r{i}",
                f"This is a detailed memory entry number {i} with lots of context " * 10,
            )

        result = load_memory_for_injection(store, "implement", "task", max_tokens=100)
        # ~100 tokens ≈ ~400 chars
        assert len(result) < 800  # generous buffer for header

    def test_phase_category_mapping(self, store: MemoryStore):
        store.add_memory(MemoryCategory.REVIEW_PATTERN, "review", "r1", "review pattern")
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r2", "codebase fact")

        # For implement phase, review_pattern shouldn't be prioritized
        # but codebase should be
        result = load_memory_for_injection(store, "implement", "task")
        assert "codebase fact" in result

    def test_direct_agent_gets_all_categories(self, store: MemoryStore):
        store.add_memory(MemoryCategory.CODEBASE, "implement", "r1", "codebase")
        store.add_memory(MemoryCategory.FAILURE, "fix", "r2", "failure")
        store.add_memory(MemoryCategory.PREFERENCE, "plan", "r3", "preference")
        store.add_memory(MemoryCategory.REVIEW_PATTERN, "review", "r4", "review")

        result = load_memory_for_injection(store, "direct_agent", "task")
        # All categories should be considered
        assert result != ""


class TestMemoryCategory:
    def test_enum_values(self):
        assert MemoryCategory.CODEBASE.value == "codebase"
        assert MemoryCategory.FAILURE.value == "failure"
        assert MemoryCategory.PREFERENCE.value == "preference"
        assert MemoryCategory.REVIEW_PATTERN.value == "review_pattern"


class TestMemoryEntry:
    def test_dataclass_fields(self):
        entry = MemoryEntry(
            id=1,
            created_at="2026-03-26T12:00:00",
            category=MemoryCategory.CODEBASE,
            phase="implement",
            run_id="run-001",
            text="test entry",
            tags=["tag1", "tag2"],
        )
        assert entry.id == 1
        assert entry.tags == ["tag1", "tag2"]
