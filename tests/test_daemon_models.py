"""Tests for daemon-related model changes (priority field, compute_priority)."""
from __future__ import annotations

from colonyos.models import (
    PRIORITY_BUG,
    PRIORITY_CEO,
    PRIORITY_CLEANUP,
    PRIORITY_FEATURE,
    QueueItem,
    QueueItemStatus,
    compute_priority,
)


class TestQueueItemPriority:
    def test_default_priority(self):
        item = QueueItem(id="t", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING)
        assert item.priority == 1

    def test_priority_in_to_dict(self):
        item = QueueItem(id="t", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING, priority=2)
        d = item.to_dict()
        assert d["priority"] == 2

    def test_priority_from_dict(self):
        d = {"id": "t", "source_type": "prompt", "source_value": "x", "status": "pending", "priority": 3}
        item = QueueItem.from_dict(d)
        assert item.priority == 3

    def test_backward_compat_no_priority(self):
        """Old schema v3 items without priority should default to 1."""
        d = {"id": "t", "source_type": "prompt", "source_value": "x", "status": "pending", "schema_version": 3}
        item = QueueItem.from_dict(d)
        assert item.priority == 1

    def test_schema_version_bumped(self):
        assert QueueItem.SCHEMA_VERSION == 4

    def test_roundtrip_with_priority(self):
        item = QueueItem(id="t", source_type="ceo", source_value="test", status=QueueItemStatus.PENDING, priority=2)
        d = item.to_dict()
        restored = QueueItem.from_dict(d)
        assert restored.priority == item.priority
        assert restored.source_type == "ceo"


class TestComputePriority:
    def test_ceo_is_p2(self):
        assert compute_priority("ceo") == PRIORITY_CEO == 2

    def test_cleanup_is_p3(self):
        assert compute_priority("cleanup") == PRIORITY_CLEANUP == 3

    def test_slack_default_is_p1(self):
        assert compute_priority("slack") == PRIORITY_FEATURE == 1

    def test_issue_default_is_p1(self):
        assert compute_priority("issue") == PRIORITY_FEATURE == 1

    def test_prompt_default_is_p1(self):
        assert compute_priority("prompt") == PRIORITY_FEATURE == 1

    def test_bug_label_promotes_to_p0(self):
        assert compute_priority("slack", ["bug"]) == PRIORITY_BUG == 0

    def test_bug_signal_in_label(self):
        assert compute_priority("issue", ["critical-fix"]) == PRIORITY_BUG

    def test_regression_label(self):
        assert compute_priority("slack", ["regression"]) == PRIORITY_BUG

    def test_non_bug_labels_stay_p1(self):
        assert compute_priority("issue", ["enhancement", "feature"]) == PRIORITY_FEATURE

    def test_empty_labels(self):
        assert compute_priority("slack", []) == PRIORITY_FEATURE

    def test_none_labels(self):
        assert compute_priority("issue", None) == PRIORITY_FEATURE

    def test_case_insensitive_bug_detection(self):
        assert compute_priority("slack", ["BUG"]) == PRIORITY_BUG
