from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    "ci_fix": {
        "enabled": False,
        "max_retries": 2,
        "wait_timeout": 600,
        "log_char_cap": 12_000,
    },
    "cleanup": {
        "branch_retention_days": 0,
        "artifact_retention_days": 30,
        "scan_max_lines": 500,
        "scan_max_functions": 20,
    },
    "parallel_implement": {
        "enabled": True,
        "max_parallel_agents": 3,
        "conflict_strategy": "auto",
        "merge_timeout_seconds": 60,
        "worktree_cleanup": True,
    },
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
class CIFixConfig:
    enabled: bool = False
    max_retries: int = 2
    wait_timeout: int = 600
    log_char_cap: int = 12_000


@dataclass
class CleanupConfig:
    branch_retention_days: int = 0
    artifact_retention_days: int = 30
    scan_max_lines: int = 500
    scan_max_functions: int = 20


VALID_CONFLICT_STRATEGIES: frozenset[str] = frozenset({"auto", "fail", "manual"})


@dataclass
class ParallelImplementConfig:
    """Configuration for parallel implement mode."""

    enabled: bool = True
    max_parallel_agents: int = 3
    conflict_strategy: str = "auto"
    merge_timeout_seconds: int = 60
    worktree_cleanup: bool = True


@dataclass
class SlackConfig:
    enabled: bool = False
    channels: list[str] = field(default_factory=list)
    trigger_mode: str = "mention"
    auto_approve: bool = False
    max_runs_per_hour: int = 3
    allowed_user_ids: list[str] = field(default_factory=list)
    triage_scope: str = ""
    daily_budget_usd: float | None = None
    max_queue_depth: int = 20
    triage_verbose: bool = False
    max_consecutive_failures: int = 3
    circuit_breaker_cooldown_minutes: int = 30
    max_fix_rounds_per_thread: int = 3


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
    directions_auto_update: bool = True
    max_fix_iterations: int = 2
    auto_approve: bool = False
    learnings: LearningsConfig = field(default_factory=LearningsConfig)
    ci_fix: CIFixConfig = field(default_factory=CIFixConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    parallel_implement: ParallelImplementConfig = field(default_factory=ParallelImplementConfig)

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


_VALID_TRIGGER_MODES: frozenset[str] = frozenset({"mention", "reaction", "slash_command"})


def _parse_slack_config(raw: dict) -> SlackConfig:
    """Parse the ``slack`` section from config.yaml."""
    if not raw:
        return SlackConfig()
    trigger_mode = raw.get("trigger_mode", "mention")
    if trigger_mode not in _VALID_TRIGGER_MODES:
        raise ValueError(
            f"Invalid slack trigger_mode '{trigger_mode}'. "
            f"Valid options: {sorted(_VALID_TRIGGER_MODES)}"
        )
    max_queue_depth = int(raw.get("max_queue_depth", 20))
    if max_queue_depth < 1:
        raise ValueError(
            f"slack.max_queue_depth must be positive, got {max_queue_depth}"
        )
    max_consecutive_failures = int(raw.get("max_consecutive_failures", 3))
    if max_consecutive_failures < 1:
        raise ValueError(
            f"slack.max_consecutive_failures must be positive, got {max_consecutive_failures}"
        )
    circuit_breaker_cooldown_minutes = int(raw.get("circuit_breaker_cooldown_minutes", 30))
    if circuit_breaker_cooldown_minutes < 1:
        raise ValueError(
            f"slack.circuit_breaker_cooldown_minutes must be positive, got {circuit_breaker_cooldown_minutes}"
        )
    max_fix_rounds_per_thread = int(raw.get("max_fix_rounds_per_thread", 3))
    if max_fix_rounds_per_thread < 1:
        raise ValueError(
            f"slack.max_fix_rounds_per_thread must be positive, got {max_fix_rounds_per_thread}"
        )
    max_runs_per_hour = int(raw.get("max_runs_per_hour", 3))
    if max_runs_per_hour < 1:
        raise ValueError(
            f"slack.max_runs_per_hour must be positive, got {max_runs_per_hour}"
        )
    daily_budget_raw = raw.get("daily_budget_usd")
    daily_budget_usd: float | None = None
    if daily_budget_raw is not None:
        daily_budget_usd = float(daily_budget_raw)
        if daily_budget_usd <= 0:
            raise ValueError(
                f"slack.daily_budget_usd must be positive, got {daily_budget_usd}"
            )
    allowed_user_ids_raw = list(raw.get("allowed_user_ids", []))
    enabled = bool(raw.get("enabled", False))
    auto_approve = bool(raw.get("auto_approve", False))

    return SlackConfig(
        enabled=enabled,
        channels=list(raw.get("channels", [])),
        trigger_mode=trigger_mode,
        auto_approve=auto_approve,
        max_runs_per_hour=max_runs_per_hour,
        allowed_user_ids=allowed_user_ids_raw,
        triage_scope=str(raw.get("triage_scope", "")),
        daily_budget_usd=daily_budget_usd,
        max_queue_depth=max_queue_depth,
        triage_verbose=bool(raw.get("triage_verbose", False)),
        max_consecutive_failures=max_consecutive_failures,
        circuit_breaker_cooldown_minutes=circuit_breaker_cooldown_minutes,
        max_fix_rounds_per_thread=max_fix_rounds_per_thread,
    )


def _parse_ci_fix_config(raw: dict) -> CIFixConfig:
    """Parse the ``ci_fix`` section from config.yaml."""
    if not raw:
        return CIFixConfig()
    max_retries = int(raw.get("max_retries", DEFAULTS["ci_fix"]["max_retries"]))
    if max_retries < 0:
        raise ValueError(
            f"ci_fix.max_retries must be non-negative, got {max_retries}"
        )
    wait_timeout = int(raw.get("wait_timeout", DEFAULTS["ci_fix"]["wait_timeout"]))
    if wait_timeout < 0:
        raise ValueError(
            f"ci_fix.wait_timeout must be non-negative, got {wait_timeout}"
        )
    log_char_cap = int(raw.get("log_char_cap", DEFAULTS["ci_fix"]["log_char_cap"]))
    if log_char_cap < 0:
        raise ValueError(
            f"ci_fix.log_char_cap must be non-negative, got {log_char_cap}"
        )
    return CIFixConfig(
        enabled=bool(raw.get("enabled", False)),
        max_retries=max_retries,
        wait_timeout=wait_timeout,
        log_char_cap=log_char_cap,
    )


def _parse_cleanup_config(raw: dict) -> CleanupConfig:
    """Parse the ``cleanup`` section from config.yaml."""
    if not raw:
        return CleanupConfig()
    branch_retention_days = int(raw.get("branch_retention_days", DEFAULTS["cleanup"]["branch_retention_days"]))
    if branch_retention_days < 0:
        raise ValueError(
            f"cleanup.branch_retention_days must be non-negative, got {branch_retention_days}"
        )
    artifact_retention_days = int(raw.get("artifact_retention_days", DEFAULTS["cleanup"]["artifact_retention_days"]))
    if artifact_retention_days < 0:
        raise ValueError(
            f"cleanup.artifact_retention_days must be non-negative, got {artifact_retention_days}"
        )
    scan_max_lines = int(raw.get("scan_max_lines", DEFAULTS["cleanup"]["scan_max_lines"]))
    if scan_max_lines < 1:
        raise ValueError(
            f"cleanup.scan_max_lines must be positive, got {scan_max_lines}"
        )
    scan_max_functions = int(raw.get("scan_max_functions", DEFAULTS["cleanup"]["scan_max_functions"]))
    if scan_max_functions < 1:
        raise ValueError(
            f"cleanup.scan_max_functions must be positive, got {scan_max_functions}"
        )
    return CleanupConfig(
        branch_retention_days=branch_retention_days,
        artifact_retention_days=artifact_retention_days,
        scan_max_lines=scan_max_lines,
        scan_max_functions=scan_max_functions,
    )


def _parse_parallel_implement_config(raw: dict) -> ParallelImplementConfig:
    """Parse the ``parallel_implement`` section from config.yaml."""
    if not raw:
        return ParallelImplementConfig()

    defaults = DEFAULTS["parallel_implement"]

    enabled = bool(raw.get("enabled", defaults["enabled"]))

    max_parallel_agents = int(raw.get("max_parallel_agents", defaults["max_parallel_agents"]))
    if max_parallel_agents < 1:
        raise ValueError(
            f"parallel_implement.max_parallel_agents must be positive, got {max_parallel_agents}"
        )

    conflict_strategy = str(raw.get("conflict_strategy", defaults["conflict_strategy"]))
    if conflict_strategy not in VALID_CONFLICT_STRATEGIES:
        raise ValueError(
            f"Invalid conflict_strategy '{conflict_strategy}'. "
            f"Valid options: {sorted(VALID_CONFLICT_STRATEGIES)}"
        )

    merge_timeout_seconds = int(raw.get("merge_timeout_seconds", defaults["merge_timeout_seconds"]))
    if merge_timeout_seconds < 1:
        raise ValueError(
            f"parallel_implement.merge_timeout_seconds must be positive, got {merge_timeout_seconds}"
        )

    worktree_cleanup = bool(raw.get("worktree_cleanup", defaults["worktree_cleanup"]))

    return ParallelImplementConfig(
        enabled=enabled,
        max_parallel_agents=max_parallel_agents,
        conflict_strategy=conflict_strategy,
        merge_timeout_seconds=merge_timeout_seconds,
        worktree_cleanup=worktree_cleanup,
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
        directions_auto_update=bool(raw.get("directions_auto_update", True)),
        max_fix_iterations=int(raw.get("max_fix_iterations", DEFAULTS["max_fix_iterations"])),
        auto_approve=bool(raw.get("auto_approve", False)),
        learnings=LearningsConfig(
            enabled=bool(raw.get("learnings", {}).get("enabled", DEFAULTS["learnings"]["enabled"])),
            max_entries=int(raw.get("learnings", {}).get("max_entries", DEFAULTS["learnings"]["max_entries"])),
        ),
        ci_fix=_parse_ci_fix_config(raw.get("ci_fix", {})),
        slack=_parse_slack_config(raw.get("slack", {})),
        cleanup=_parse_cleanup_config(raw.get("cleanup", {})),
        parallel_implement=_parse_parallel_implement_config(raw.get("parallel_implement", {})),
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

    if config.ci_fix.enabled or config.ci_fix.max_retries != DEFAULTS["ci_fix"]["max_retries"]:
        data["ci_fix"] = {
            "enabled": config.ci_fix.enabled,
            "max_retries": config.ci_fix.max_retries,
            "wait_timeout": config.ci_fix.wait_timeout,
            "log_char_cap": config.ci_fix.log_char_cap,
        }

    if config.slack.enabled or config.slack.channels:
        slack_data: dict[str, Any] = {
            "enabled": config.slack.enabled,
            "channels": list(config.slack.channels),
            "trigger_mode": config.slack.trigger_mode,
            "auto_approve": config.slack.auto_approve,
            "max_runs_per_hour": config.slack.max_runs_per_hour,
            "allowed_user_ids": list(config.slack.allowed_user_ids),
            "max_queue_depth": config.slack.max_queue_depth,
            "triage_verbose": config.slack.triage_verbose,
            "max_consecutive_failures": config.slack.max_consecutive_failures,
            "circuit_breaker_cooldown_minutes": config.slack.circuit_breaker_cooldown_minutes,
            "max_fix_rounds_per_thread": config.slack.max_fix_rounds_per_thread,
        }
        if config.slack.triage_scope:
            slack_data["triage_scope"] = config.slack.triage_scope
        if config.slack.daily_budget_usd is not None:
            slack_data["daily_budget_usd"] = config.slack.daily_budget_usd
        data["slack"] = slack_data

    cleanup_defaults = DEFAULTS["cleanup"]
    if (
        config.cleanup.branch_retention_days != cleanup_defaults["branch_retention_days"]
        or config.cleanup.artifact_retention_days != cleanup_defaults["artifact_retention_days"]
        or config.cleanup.scan_max_lines != cleanup_defaults["scan_max_lines"]
        or config.cleanup.scan_max_functions != cleanup_defaults["scan_max_functions"]
    ):
        data["cleanup"] = {
            "branch_retention_days": config.cleanup.branch_retention_days,
            "artifact_retention_days": config.cleanup.artifact_retention_days,
            "scan_max_lines": config.cleanup.scan_max_lines,
            "scan_max_functions": config.cleanup.scan_max_functions,
        }

    if config.ceo_persona:
        data["ceo_persona"] = {
            "role": config.ceo_persona.role,
            "expertise": config.ceo_persona.expertise,
            "perspective": config.ceo_persona.perspective,
        }

    if config.vision:
        data["vision"] = config.vision

    # Only serialize parallel_implement if values differ from defaults
    pi_defaults = DEFAULTS["parallel_implement"]
    if (
        config.parallel_implement.enabled != pi_defaults["enabled"]
        or config.parallel_implement.max_parallel_agents != pi_defaults["max_parallel_agents"]
        or config.parallel_implement.conflict_strategy != pi_defaults["conflict_strategy"]
        or config.parallel_implement.merge_timeout_seconds != pi_defaults["merge_timeout_seconds"]
        or config.parallel_implement.worktree_cleanup != pi_defaults["worktree_cleanup"]
    ):
        data["parallel_implement"] = {
            "enabled": config.parallel_implement.enabled,
            "max_parallel_agents": config.parallel_implement.max_parallel_agents,
            "conflict_strategy": config.parallel_implement.conflict_strategy,
            "merge_timeout_seconds": config.parallel_implement.merge_timeout_seconds,
            "worktree_cleanup": config.parallel_implement.worktree_cleanup,
        }

    if not config.directions_auto_update:
        data["directions_auto_update"] = False

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
