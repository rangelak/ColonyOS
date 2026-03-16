from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from colonyos_pm.models import HumanInterventionRecord, WorkflowArtifacts
from colonyos_pm.naming import generate_planning_names


class ArtifactStore(Protocol):
    def save_workflow_artifacts(self, artifacts: WorkflowArtifacts) -> dict[str, str]:
        ...

    def save_human_intervention(self, record: HumanInterventionRecord) -> str:
        ...


class LocalArtifactStore:
    """Filesystem-backed store used for v1 artifact output."""

    def __init__(
        self, base_dir: str = "generated/pm-workflow", tasks_dir: str = "tasks"
    ) -> None:
        self.base_dir = Path(base_dir)
        self.tasks_dir = Path(tasks_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _extract_prd_title(self, prd_markdown: str, work_id: str) -> str:
        for line in prd_markdown.splitlines():
            if line.startswith("# PRD:"):
                return line.removeprefix("# PRD:").strip() or work_id
        return work_id

    def save_workflow_artifacts(self, artifacts: WorkflowArtifacts) -> dict[str, str]:
        work_dir = self.base_dir / artifacts.work_id
        work_dir.mkdir(parents=True, exist_ok=True)

        prd_path = work_dir / "prd.md"
        prd_path.write_text(artifacts.prd_markdown, encoding="utf-8")

        bundle_path = work_dir / "artifact_bundle.json"
        bundle_path.write_text(
            json.dumps(asdict(artifacts), indent=2),
            encoding="utf-8",
        )

        prd_title = self._extract_prd_title(artifacts.prd_markdown, artifacts.work_id)
        planning_names = generate_planning_names(prd_title, title=prd_title)
        task_prd_path = self.tasks_dir / planning_names.prd_filename
        task_prd_path.write_text(artifacts.prd_markdown, encoding="utf-8")

        return {
            "work_dir": str(work_dir),
            "prd_path": str(prd_path),
            "bundle_path": str(bundle_path),
            "task_prd_path": str(task_prd_path),
        }

    def save_human_intervention(self, record: HumanInterventionRecord) -> str:
        memory_dir = self.base_dir / "human-memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        out_path = memory_dir / f"{record.work_id}.json"
        out_path.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
        return str(out_path)
