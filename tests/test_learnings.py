"""Tests for the cross-run learnings module."""

from pathlib import Path

import pytest

from colonyos.learnings import (
    LEDGER_HEADER,
    LearningEntry,
    append_learnings,
    count_learnings,
    format_learnings_section,
    learnings_path,
    load_learnings_for_injection,
    parse_learnings,
    prune_ledger,
)


SAMPLE_LEDGER = """\
# ColonyOS Learnings Ledger

## Run: run-20260301-abc
_Date: 2026-03-01 | Feature: Add auth_

- **[code-quality]** Always add docstrings to public functions
- **[testing]** Run pytest before committing changes
- **[security]** Validate user input at API boundaries

## Run: run-20260302-def
_Date: 2026-03-02 | Feature: Add logging_

- **[architecture]** Separate I/O from business logic
- **[style]** Use snake_case for all function names
"""


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


class TestParseLearnings:
    def test_parse_well_formed(self):
        sections = parse_learnings(SAMPLE_LEDGER)
        assert len(sections) == 2

        run_id, date, feature, entries = sections[0]
        assert run_id == "run-20260301-abc"
        assert date == "2026-03-01"
        assert feature == "Add auth"
        assert len(entries) == 3
        assert entries[0] == LearningEntry("code-quality", "Always add docstrings to public functions")
        assert entries[2] == LearningEntry("security", "Validate user input at API boundaries")

        run_id2, date2, feature2, entries2 = sections[1]
        assert run_id2 == "run-20260302-def"
        assert len(entries2) == 2

    def test_parse_empty(self):
        assert parse_learnings("") == []

    def test_parse_header_only(self):
        assert parse_learnings(LEDGER_HEADER) == []

    def test_parse_malformed_entries_skipped(self):
        content = """\
# ColonyOS Learnings Ledger

## Run: run-001
_Date: 2026-01-01 | Feature: test_

- **[code-quality]** Valid entry
- This is not a valid entry
- **[testing]** Another valid entry
"""
        sections = parse_learnings(content)
        assert len(sections) == 1
        assert len(sections[0][3]) == 2


class TestFormatLearningsSection:
    def test_format_section(self):
        entries = [
            LearningEntry("code-quality", "Add docstrings"),
            LearningEntry("testing", "Write tests first"),
        ]
        result = format_learnings_section("run-001", "2026-03-17", "Add feature", entries)
        assert "## Run: run-001" in result
        assert "_Date: 2026-03-17 | Feature: Add feature_" in result
        assert "- **[code-quality]** Add docstrings" in result
        assert "- **[testing]** Write tests first" in result


class TestAppendLearnings:
    def test_creates_file_if_missing(self, tmp_repo: Path):
        entries = [LearningEntry("code-quality", "New learning")]
        append_learnings(tmp_repo, "run-001", "2026-03-17", "Feature A", entries)

        path = learnings_path(tmp_repo)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "## Run: run-001" in content
        assert "- **[code-quality]** New learning" in content

    def test_appends_to_existing(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")

        entries = [LearningEntry("testing", "Totally new pattern")]
        append_learnings(tmp_repo, "run-003", "2026-03-17", "Feature C", entries)

        content = path.read_text(encoding="utf-8")
        sections = parse_learnings(content)
        assert len(sections) == 3

    def test_deduplication_skips_identical(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")

        entries = [
            LearningEntry("code-quality", "Always add docstrings to public functions"),
            LearningEntry("testing", "Brand new insight"),
        ]
        append_learnings(tmp_repo, "run-003", "2026-03-17", "Feature C", entries)

        content = path.read_text(encoding="utf-8")
        sections = parse_learnings(content)
        new_section = sections[-1]
        assert len(new_section[3]) == 1
        assert new_section[3][0].text == "Brand new insight"

    def test_deduplication_normalized(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")

        entries = [
            LearningEntry("code-quality", "  always  ADD  DOCSTRINGS  to  public  functions  "),
        ]
        append_learnings(tmp_repo, "run-003", "2026-03-17", "Feature C", entries)

        content = path.read_text(encoding="utf-8")
        sections = parse_learnings(content)
        assert len(sections) == 2  # no new section added since all deduped

    def test_all_duplicates_skips_write(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")
        original = path.read_text(encoding="utf-8")

        entries = [
            LearningEntry("code-quality", "Always add docstrings to public functions"),
        ]
        append_learnings(tmp_repo, "run-003", "2026-03-17", "Feature C", entries)

        assert path.read_text(encoding="utf-8") == original


class TestPruneLedger:
    def test_prune_oldest_sections(self):
        content = SAMPLE_LEDGER
        # SAMPLE_LEDGER has 5 entries total (3 + 2). Prune to max 3 should remove first section.
        result = prune_ledger(content, max_entries=3)
        sections = parse_learnings(result)
        assert len(sections) == 1
        assert sections[0][0] == "run-20260302-def"

    def test_no_prune_needed(self):
        result = prune_ledger(SAMPLE_LEDGER, max_entries=100)
        sections = parse_learnings(result)
        assert len(sections) == 2

    def test_prune_all(self):
        result = prune_ledger(SAMPLE_LEDGER, max_entries=0)
        sections = parse_learnings(result)
        assert len(sections) == 0
        assert LEDGER_HEADER in result


class TestLoadLearningsForInjection:
    def test_returns_empty_when_no_file(self, tmp_repo: Path):
        assert load_learnings_for_injection(tmp_repo) == ""

    def test_returns_recent_entries(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")

        result = load_learnings_for_injection(tmp_repo, max_entries=3)
        assert "- **[security]** Validate user input at API boundaries" in result
        assert "- **[architecture]** Separate I/O from business logic" in result
        assert "- **[style]** Use snake_case for all function names" in result
        # Should not contain the oldest entries
        assert "docstrings" not in result

    def test_returns_all_when_under_limit(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")

        result = load_learnings_for_injection(tmp_repo, max_entries=20)
        assert "docstrings" in result
        assert "snake_case" in result

    def test_empty_ledger(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(LEDGER_HEADER, encoding="utf-8")
        assert load_learnings_for_injection(tmp_repo) == ""


class TestCountLearnings:
    def test_count_entries(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(SAMPLE_LEDGER, encoding="utf-8")
        assert count_learnings(tmp_repo) == 5

    def test_count_no_file(self, tmp_repo: Path):
        assert count_learnings(tmp_repo) == 0

    def test_count_empty_ledger(self, tmp_repo: Path):
        path = learnings_path(tmp_repo)
        path.write_text(LEDGER_HEADER, encoding="utf-8")
        assert count_learnings(tmp_repo) == 0


class TestLearningsPath:
    def test_path(self, tmp_repo: Path):
        assert learnings_path(tmp_repo) == tmp_repo / ".colonyos" / "learnings.md"
