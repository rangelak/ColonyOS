from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from colonyos.models import Persona, Phase, ProjectInfo

logger = logging.getLogger(__name__)

CONFIG_DIR = ".colonyos"
CONFIG_FILE = "config.yaml"
RUNS_DIR = "runs"

VALID_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})

# Phases that serve as safety gates and should not be downgraded to
# lightweight models without explicit awareness of the trade-off.
_SAFETY_CRITICAL_PHASES: frozenset[str] = frozenset({"review", "decision", "fix"})

DEFAULTS = {
    "model": "sonnet",
    "budget": {
        "per_phase": 5.0,
        "per_run": 15.0,
        "max_duration_hours": 8.0,
        "max_total_usd": 500.0,
    },
    "phases": {"plan": True, "implement": True, "review": True, "deliver": True},
    "branch_prefix": "colonyos/",
    "prds_dir": "cOS_prds",
    "tasks_dir": "cOS_tasks",
    "reviews_dir": "cOS_reviews",
    "proposals_dir": "cOS_proposals",
    "max_fix_iterations": 2,
    "learnings": {"enabled": True, "max_entries": 100},
}


@dataclass
class BudgetConfig:
    per_phase: float = 5.0
    per_run: float = 15.0
    max_duration_hours: float = 8.0
    max_total_usd: float = 500.0


@dataclass
class PhasesConfig:
    plan: bool = True
    implement: bool = True
    review: bool = True
    deliver: bool = True


@dataclass
class LearningsConfig:
    enabled: bool = True
    max_entries: int = 100


@dataclass
class ColonyConfig:
    project: ProjectInfo | None = None
    personas: list[Persona] = field(default_factory=list)
    model: str = "sonnet"
    phase_models: dict[str, str] = field(default_factory=dict)
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
    auto_approve: bool = False
    learnings: LearningsConfig = field(default_factory=LearningsConfig)

    def get_model(self, phase: Phase) -> str:
        """Return the model for a phase, falling back to the global default."""
        return self.phase_models.get(phase.value, self.model)


def _parse_personas(raw: list[dict]) -> list[Persona]:
    return [
        Persona(
            role=p.get("role", ""),
            expertise=p.get("expertise", ""),
            perspective=p.get("perspective", ""),
            reviewer=bool(p.get("reviewer", False)),
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
        reviewer=bool(raw.get("reviewer", False)),
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

    # Validate top-level model
    model_val = raw.get("model", DEFAULTS["model"])
    if model_val not in VALID_MODELS:
        raise ValueError(
            f"Invalid model '{model_val}'. Valid options: {sorted(VALID_MODELS)}. "
            f"Note: use short names (e.g. 'opus') not full model IDs "
            f"(e.g. 'claude-opus-4-20250514')."
        )

    # Parse and validate phase_models
    phase_models_raw: dict[str, str] = raw.get("phase_models", {})
    valid_phase_values = {p.value for p in Phase}
    for phase_key, model_name in phase_models_raw.items():
        if phase_key not in valid_phase_values:
            raise ValueError(
                f"Invalid phase key '{phase_key}' in phase_models. "
                f"Valid phases: {sorted(valid_phase_values)}"
            )
        if model_name not in VALID_MODELS:
            raise ValueError(
                f"Invalid model '{model_name}' for phase '{phase_key}' in phase_models. "
                f"Valid options: {sorted(VALID_MODELS)}. "
                f"Note: use short names (e.g. 'opus') not full model IDs "
                f"(e.g. 'claude-opus-4-20250514')."
            )

    # Warn when lightweight models are assigned to safety-critical phases
    for phase_key, model_name in phase_models_raw.items():
        if phase_key in _SAFETY_CRITICAL_PHASES and model_name == "haiku":
            logger.warning(
                "Phase '%s' is assigned model 'haiku'. This phase serves as a "
                "safety gate in the pipeline — using a lightweight model may "
                "reduce review quality. Consider using 'sonnet' or 'opus'.",
                phase_key,
            )

    return ColonyConfig(
        project=_parse_project(raw.get("project", {})),
        personas=_parse_personas(raw.get("personas", [])),
        model=model_val,
        phase_models=phase_models_raw,
        budget=BudgetConfig(
            per_phase=float(budget_raw.get("per_phase", DEFAULTS["budget"]["per_phase"])),
            per_run=float(budget_raw.get("per_run", DEFAULTS["budget"]["per_run"])),
            max_duration_hours=float(budget_raw.get("max_duration_hours", DEFAULTS["budget"]["max_duration_hours"])),
            max_total_usd=float(budget_raw.get("max_total_usd", DEFAULTS["budget"]["max_total_usd"])),
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
        auto_approve=bool(raw.get("auto_approve", False)),
        learnings=LearningsConfig(
            enabled=bool(raw.get("learnings", {}).get("enabled", DEFAULTS["learnings"]["enabled"])),
            max_entries=int(raw.get("learnings", {}).get("max_entries", DEFAULTS["learnings"]["max_entries"])),
        ),
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
                "reviewer": p.reviewer,
            }
            for p in config.personas
        ]

    data["model"] = config.model
    if config.phase_models:
        data["phase_models"] = dict(config.phase_models)
    data["budget"] = {
        "per_phase": config.budget.per_phase,
        "per_run": config.budget.per_run,
        "max_duration_hours": config.budget.max_duration_hours,
        "max_total_usd": config.budget.max_total_usd,
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
    data["auto_approve"] = config.auto_approve
    data["learnings"] = {
        "enabled": config.learnings.enabled,
        "max_entries": config.learnings.max_entries,
    }

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
