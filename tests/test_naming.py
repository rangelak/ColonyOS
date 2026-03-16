from datetime import datetime

import pytest

from colonyos.naming import (
    PlanningNames,
    planning_names,
    slugify,
    task_filename_from_prd,
    generate_timestamp,
)


class TestSlugify:
    def test_basic(self):
        assert slugify("Add Stripe Billing") == "add_stripe_billing"

    def test_special_chars(self):
        assert slugify("feat: add OAuth 2.0!") == "feat_add_oauth_2_0"

    def test_empty(self):
        assert slugify("") == "untitled"

    def test_consecutive_separators(self):
        assert slugify("a---b___c   d") == "a_b_c_d"

    def test_leading_trailing_stripped(self):
        assert slugify("  hello world  ") == "hello_world"


class TestPlanningNames:
    def test_generates_filenames(self):
        names = planning_names("Add auth", timestamp="20260316_120000")
        assert names.timestamp == "20260316_120000"
        assert names.slug == "add_auth"
        assert names.prd_filename == "20260316_120000_prd_add_auth.md"
        assert names.task_filename == "20260316_120000_tasks_add_auth.md"

    def test_auto_timestamp(self):
        names = planning_names("some feature")
        assert len(names.timestamp) == 15  # YYYYMMDD_HHMMSS
        assert names.prd_filename.startswith(names.timestamp)

    def test_frozen(self):
        names = planning_names("test", timestamp="20260101_000000")
        with pytest.raises(AttributeError):
            names.slug = "changed"


class TestTaskFilenameFromPrd:
    def test_valid(self):
        assert (
            task_filename_from_prd("20260316_120000_prd_add_auth.md")
            == "20260316_120000_tasks_add_auth.md"
        )

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="must match"):
            task_filename_from_prd("not_a_prd.md")


class TestGenerateTimestamp:
    def test_format(self):
        ts = generate_timestamp(datetime(2026, 3, 16, 12, 0, 0))
        assert ts == "20260316_120000"

    def test_auto(self):
        ts = generate_timestamp()
        assert len(ts) == 15
