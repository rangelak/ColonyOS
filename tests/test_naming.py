from datetime import datetime

import pytest

from colonyos.naming import (
    PlanningNames,
    ProposalNames,
    ReviewArtifactPath,
    ReviewNames,
    decision_artifact_path,
    generate_timestamp,
    persona_review_artifact_path,
    planning_names,
    proposal_names,
    review_names,
    slugify,
    standalone_decision_artifact_path,
    summary_artifact_path,
    task_filename_from_prd,
    task_review_artifact_path,
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


class TestReviewNames:
    def test_generates_task_review_filenames(self):
        names = review_names("Add auth", task_count=3, timestamp="20260317_090000")
        assert names.timestamp == "20260317_090000"
        assert names.slug == "add_auth"
        assert len(names.task_review_filenames) == 3
        assert names.task_review_filenames[0] == "20260317_090000_review_task_1_add_auth.md"
        assert names.task_review_filenames[1] == "20260317_090000_review_task_2_add_auth.md"
        assert names.task_review_filenames[2] == "20260317_090000_review_task_3_add_auth.md"

    def test_generates_final_review_filename(self):
        names = review_names("Add auth", task_count=2, timestamp="20260317_090000")
        assert names.final_review_filename == "20260317_090000_review_final_add_auth.md"

    def test_auto_timestamp(self):
        names = review_names("feature", task_count=1)
        assert len(names.timestamp) == 15
        assert names.task_review_filenames[0].startswith(names.timestamp)

    def test_frozen(self):
        names = review_names("test", task_count=1, timestamp="20260101_000000")
        with pytest.raises(AttributeError):
            names.slug = "changed"

    def test_zero_tasks(self):
        names = review_names("test", task_count=0, timestamp="20260101_000000")
        assert names.task_review_filenames == ()
        assert names.final_review_filename == "20260101_000000_review_final_test.md"


class TestProposalNames:
    def test_generates_filename(self):
        names = proposal_names("Add webhooks", timestamp="20260317_120000")
        assert names.timestamp == "20260317_120000"
        assert names.slug == "add_webhooks"
        assert names.proposal_filename == "20260317_120000_proposal_add_webhooks.md"

    def test_auto_timestamp(self):
        names = proposal_names("some proposal")
        assert len(names.timestamp) == 15
        assert names.proposal_filename.startswith(names.timestamp)

    def test_frozen(self):
        names = proposal_names("test", timestamp="20260101_000000")
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


class TestReviewArtifactPath:
    def test_relative_path_joins_subdirectory_and_filename(self):
        path = ReviewArtifactPath(subdirectory="decisions", filename="test.md")
        assert path.relative_path == "decisions/test.md"

    def test_frozen(self):
        path = ReviewArtifactPath(subdirectory="decisions", filename="test.md")
        with pytest.raises(AttributeError):
            path.subdirectory = "changed"

    def test_nested_subdirectory(self):
        path = ReviewArtifactPath(subdirectory="reviews/engineer", filename="f.md")
        assert path.relative_path == "reviews/engineer/f.md"


class TestDecisionArtifactPath:
    def test_basic(self):
        result = decision_artifact_path("Add auth", timestamp="20260318_110000")
        assert result.subdirectory == "decisions"
        assert result.filename == "20260318_110000_decision_add_auth.md"
        assert result.relative_path == "decisions/20260318_110000_decision_add_auth.md"

    def test_auto_timestamp(self):
        result = decision_artifact_path("some feature")
        assert result.filename.endswith("_decision_some_feature.md")
        assert len(result.filename.split("_decision_")[0]) == 15

    def test_slug_sanitization(self):
        result = decision_artifact_path("feat: OAuth 2.0!", timestamp="20260318_110000")
        assert result.filename == "20260318_110000_decision_feat_oauth_2_0.md"


class TestPersonaReviewArtifactPath:
    def test_basic(self):
        result = persona_review_artifact_path(
            "Add auth", "staff_security_engineer", 1, timestamp="20260318_110000"
        )
        assert result.subdirectory == "reviews/staff_security_engineer"
        assert result.filename == "20260318_110000_round1_add_auth.md"

    def test_persona_slug_sanitization(self):
        result = persona_review_artifact_path(
            "Add auth", "Staff Security Engineer!", 2, timestamp="20260318_110000"
        )
        assert result.subdirectory == "reviews/staff_security_engineer"
        assert result.filename == "20260318_110000_round2_add_auth.md"

    def test_auto_timestamp(self):
        result = persona_review_artifact_path("feat", "engineer", 1)
        assert result.filename.endswith("_round1_feat.md")

    def test_relative_path(self):
        result = persona_review_artifact_path(
            "Add auth", "linus_torvalds", 3, timestamp="20260318_110000"
        )
        assert result.relative_path == "reviews/linus_torvalds/20260318_110000_round3_add_auth.md"


class TestTaskReviewArtifactPath:
    def test_basic(self):
        result = task_review_artifact_path("Add auth", 2, timestamp="20260318_110000")
        assert result.subdirectory == "reviews/tasks"
        assert result.filename == "20260318_110000_review_task_2_add_auth.md"

    def test_auto_timestamp(self):
        result = task_review_artifact_path("feat", 1)
        assert result.filename.endswith("_review_task_1_feat.md")


class TestStandaloneDecisionArtifactPath:
    def test_basic(self):
        result = standalone_decision_artifact_path(
            "feature-branch", timestamp="20260318_110000"
        )
        assert result.subdirectory == "decisions"
        assert result.filename == "20260318_110000_decision_standalone_feature_branch.md"

    def test_auto_timestamp(self):
        result = standalone_decision_artifact_path("my-branch")
        assert result.filename.endswith("_decision_standalone_my_branch.md")


class TestSummaryArtifactPath:
    def test_basic(self):
        result = summary_artifact_path("Add auth", timestamp="20260318_110000")
        assert result.subdirectory == "reviews"
        assert result.filename == "20260318_110000_summary_add_auth.md"

    def test_auto_timestamp(self):
        result = summary_artifact_path("some feature")
        assert result.filename.endswith("_summary_some_feature.md")
