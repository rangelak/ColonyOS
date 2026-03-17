from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from colonyos.models import Persona, ProjectInfo

CONFIG_DIR = ".colonyos"
CONFIG_FILE = "config.yaml"
RUNS_DIR = "runs"

DEFAULTS = {
    "model": "sonnet",
    "budget": {"per_phase": 5.0, "per_run": 15.0},
    "phases": {"plan": True, "implement": True, "review": True, "deliver": True},
    "branch_prefix": "colonyos/",
    "prds_dir": "cOS_prds",
    "tasks_dir": "cOS_tasks",
    "reviews_dir": "cOS_reviews",
    "proposals_dir": "cOS_proposals",
    "max_fix_iterations": 2,
}


@dataclass
class BudgetConfig:
    per_phase: float = 5.0
    per_run: float = 15.0


@dataclass
class PhasesConfig:
    plan: bool = True
    implement: bool = True
    review: bool = True
    deliver: bool = True


@dataclass
class ColonyConfig:
    project: ProjectInfo | None = None
    personas: list[Persona] = field(default_factory=list)
    model: str = "sonnet"
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    phases: PhasesConfig = field(default_factory=PhasesConfig)
    branch_prefix: str = "colonyos/"
    prds_dir: str = "cOS_prds"
    tasks_dir: str = "cOS_tasks"
    reviews_dir: str = "cOS_reviews"
    proposals_dir: str = "cOS_proposals"
    ceo_persona: Persona | None = None
    vision: str = ""
    max_fix_iterations: int = 2


def _parse_personas(raw: list[dict]) -> list[Persona]:
    return [
        Persona(
            role=p.get("role", ""),
            expertise=p.get("expertise", ""),
            perspective=p.get("perspective", ""),
        )
        for p in raw
        if p.get("role")
    ]


def _parse_persona(raw: dict) -> Persona | None:
    if not raw.get("role"):
        return None
    return Persona(
        role=raw.get("role", ""),
        expertise=raw.get("expertise", ""),
        perspective=raw.get("perspective", ""),
    )


def _parse_project(raw: dict) -> ProjectInfo | None:
    if not raw.get("name"):
        return None
    return ProjectInfo(
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        stack=raw.get("stack", ""),
    )


def load_config(repo_root: Path) -> ColonyConfig:
    config_path = repo_root / CONFIG_DIR / CONFIG_FILE
    if not config_path.exists():
        return ColonyConfig()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    budget_raw = raw.get("budget", {})
    phases_raw = raw.get("phases", {})

    return ColonyConfig(
        project=_parse_project(raw.get("project", {})),
        personas=_parse_personas(raw.get("personas", [])),
        model=raw.get("model", DEFAULTS["model"]),
        budget=BudgetConfig(
            per_phase=float(budget_raw.get("per_phase", DEFAULTS["budget"]["per_phase"])),
            per_run=float(budget_raw.get("per_run", DEFAULTS["budget"]["per_run"])),
        ),
        phases=PhasesConfig(
            plan=bool(phases_raw.get("plan", True)),
            implement=bool(phases_raw.get("implement", True)),
            review=bool(phases_raw.get("review", True)),
            deliver=bool(phases_raw.get("deliver", True)),
        ),
        branch_prefix=raw.get("branch_prefix", DEFAULTS["branch_prefix"]),
        prds_dir=raw.get("prds_dir", DEFAULTS["prds_dir"]),
        tasks_dir=raw.get("tasks_dir", DEFAULTS["tasks_dir"]),
        reviews_dir=raw.get("reviews_dir", DEFAULTS["reviews_dir"]),
        proposals_dir=raw.get("proposals_dir", DEFAULTS["proposals_dir"]),
        ceo_persona=_parse_persona(raw.get("ceo_persona")) if raw.get("ceo_persona") else None,
        vision=raw.get("vision", ""),
        max_fix_iterations=int(raw.get("max_fix_iterations", DEFAULTS["max_fix_iterations"])),
    )


def save_config(repo_root: Path, config: ColonyConfig) -> Path:
    config_dir = repo_root / CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    data: dict = {}

    if config.project:
        data["project"] = {
            "name": config.project.name,
            "description": config.project.description,
            "stack": config.project.stack,
        }

    if config.personas:
        data["personas"] = [
            {
                "role": p.role,
                "expertise": p.expertise,
                "perspective": p.perspective,
            }
            for p in config.personas
        ]

    data["model"] = config.model
    data["budget"] = {
        "per_phase": config.budget.per_phase,
        "per_run": config.budget.per_run,
    }
    data["phases"] = {
        "plan": config.phases.plan,
        "implement": config.phases.implement,
        "review": config.phases.review,
        "deliver": config.phases.deliver,
    }
    data["branch_prefix"] = config.branch_prefix
    data["prds_dir"] = config.prds_dir
    data["tasks_dir"] = config.tasks_dir
    data["reviews_dir"] = config.reviews_dir
    data["proposals_dir"] = config.proposals_dir

    data["max_fix_iterations"] = config.max_fix_iterations

    if config.ceo_persona:
        data["ceo_persona"] = {
            "role": config.ceo_persona.role,
            "expertise": config.ceo_persona.expertise,
            "perspective": config.ceo_persona.perspective,
        }

    if config.vision:
        data["vision"] = config.vision

    config_path = config_dir / CONFIG_FILE
    config_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return config_path


def config_dir_path(repo_root: Path) -> Path:
    return repo_root / CONFIG_DIR


def runs_dir_path(repo_root: Path) -> Path:
    return repo_root / CONFIG_DIR / RUNS_DIR
