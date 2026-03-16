import json
from datetime import datetime

import pytest

from colonyos_pm.naming import (
    generate_planning_names,
    generate_timestamp,
    main,
    normalize_feature_slug,
    task_filename_from_prd_path,
    validate_timestamp,
)


class TestPlanningNames:
    def test_normalize_feature_slug(self) -> None:
        assert normalize_feature_slug(" Billing & Auth: V2 ") == "billing_auth_v2"

    def test_generate_timestamp_from_datetime(self) -> None:
        timestamp = generate_timestamp(datetime(2026, 3, 16, 11, 11, 29))
        assert timestamp == "20260316_111129"

    def test_generate_planning_names_uses_supplied_timestamp(self) -> None:
        planning_names = generate_planning_names(
            "Billing Reconciliation",
            title="Billing Reconciliation",
            timestamp="20260316_111129",
        )

        assert planning_names.prd_filename == "20260316_111129_prd_billing_reconciliation.md"
        assert planning_names.task_filename == "20260316_111129_tasks_billing_reconciliation.md"
        assert planning_names.changelog_heading == "## 20260316_111129 — Billing Reconciliation"

    def test_task_filename_from_prd_path(self) -> None:
        task_filename = task_filename_from_prd_path(
            "tasks/20260316_111129_prd_billing_reconciliation.md"
        )
        assert task_filename == "20260316_111129_tasks_billing_reconciliation.md"

    def test_validate_timestamp_rejects_invalid_input(self) -> None:
        with pytest.raises(ValueError):
            validate_timestamp("2026-03-16 11:11:29")


class TestNamingCli:
    def test_bundle_command_outputs_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(
            [
                "bundle",
                "Billing Reconciliation",
                "--title",
                "Billing Reconciliation",
                "--timestamp",
                "20260316_111129",
            ]
        )

        output = json.loads(capsys.readouterr().out)
        assert output["prd_filename"] == "20260316_111129_prd_billing_reconciliation.md"
        assert output["task_filename"] == "20260316_111129_tasks_billing_reconciliation.md"

    def test_task_from_prd_command_outputs_filename(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(
            [
                "task-from-prd",
                "tasks/20260316_111129_prd_billing_reconciliation.md",
            ]
        )

        assert (
            capsys.readouterr().out.strip()
            == "20260316_111129_tasks_billing_reconciliation.md"
        )
