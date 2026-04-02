from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import yaml

from colonyos.models import Persona, Phase, ProjectInfo

logger = logging.getLogger(__name__)

CONFIG_DIR = ".colonyos"
CONFIG_FILE = "config.yaml"
RUNS_DIR = "runs"

VALID_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})

# Phases that serve as safety gates and should not be downgraded to
# lightweight models without explicit awareness of the trade-off.
# Uses Phase enum values so that renaming an enum member causes an AttributeError
# rather than silently disabling the safety check.
SAFETY_CRITICAL_PHASES: frozenset[str] = frozenset(
    {Phase.REVIEW.value, Phase.DECISION.value, Phase.FIX.value}
)
_SAFETY_CRITICAL_PHASES = SAFETY_CRITICAL_PHASES

DEFAULTS: dict[str, object] = {
    "model": "opus",
    "budget": {
        "per_phase": 5.0,
        "per_run": 15.0,
        "max_duration_hours": 8.0,
        "max_total_usd": 500.0,
        "phase_timeout_seconds": 1800,
    },
    "phases": {"plan": True, "implement": True, "review": True, "deliver": True, "verify": True},
    "branch_prefix": "colonyos/",
    "prds_dir": "cOS_prds",
    "tasks_dir": "cOS_tasks",
    "reviews_dir": "cOS_reviews",
    "proposals_dir": "cOS_proposals",
    "max_fix_iterations": 2,
    "verify": {"max_fix_attempts": 2},
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
        "enabled": False,
        "max_parallel_agents": 3,
        "conflict_strategy": "auto",
        "merge_timeout_seconds": 60,
        "worktree_cleanup": True,
    },
    "router": {
        "enabled": True,
        "model": "haiku",
        "qa_model": "opus",
        "confidence_threshold": 0.7,
        "small_fix_threshold": 0.85,
        "qa_budget": 0.50,
    },
    "sweep": {
        "max_tasks": 5,
        "max_files_per_task": 5,
        "default_categories": ["bugs", "dead_code", "error_handling", "complexity", "consistency"],
    },
    "memory": {
        "enabled": True,
        "max_entries": 500,
        "max_inject_tokens": 1500,
        "capture_failures": True,
    },
    "retry": {
        "max_attempts": 3,
        "base_delay_seconds": 10.0,
        "max_delay_seconds": 120.0,
        "fallback_model": None,
    },
    "recovery": {
        "enabled": True,
        "max_phase_retries": 1,
        "max_task_retries": 1,
        "allow_nuke": True,
        "max_nuke_attempts": 1,
        "incident_char_cap": 4000,
    },
    "repo_map": {
        "enabled": True,
        "max_tokens": 4000,
        "max_files": 2000,
        "include_patterns": [],
        "exclude_patterns": [],
    },
    "daemon": {
        "daily_budget_usd": 500.0,
        "github_poll_interval_seconds": 120,
        "ceo_cooldown_minutes": 60,
        "cleanup_interval_hours": 24,
        "max_cleanup_items": 3,
        "heartbeat_interval_minutes": 240,
        "digest_hour_utc": 14,
        "max_consecutive_failures": 3,
        "circuit_breaker_cooldown_minutes": 30,
        "outcome_poll_interval_minutes": 30,
        "issue_labels": [],
        "allowed_control_user_ids": [],
        "allow_all_control_users": False,
        "auto_recover_dirty_worktree": True,
        "pipeline_timeout_seconds": 7200,
        "watchdog_stall_seconds": 1920,
        "dashboard_enabled": True,
        "dashboard_port": 8741,
        "dashboard_write_enabled": False,
        "pr_sync": {
            "enabled": False,
            "interval_minutes": 60,
            "max_sync_failures": 3,
        },
        "self_update": False,
        "self_update_command": "uv pip install .",
        "maintenance_budget_usd": 20.0,
        "max_ci_fix_items": 2,
        "branch_sync_enabled": True,
    },
}


def _as_str_dict(obj: object) -> dict[str, object]:
    if not isinstance(obj, dict):
        return {}
    m: Mapping[object, object] = cast(Mapping[object, object], obj)
    return {str(k): v for k, v in m.items()}


def _defaults_section(name: str) -> dict[str, object]:
    return _as_str_dict(DEFAULTS.get(name, {}))


def _coerce_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _coerce_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    return default


def _coerce_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return default


def _coerce_str_list(value: object, default: list[str] | None = None) -> list[str]:
    if default is None:
        default = []
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple)):
        return [str(x) for x in cast(Sequence[object], value)]
    return [str(value)]


def _as_str_str_dict(obj: object) -> dict[str, str]:
    return {k: str(v) for k, v in _as_str_dict(obj).items()}


def _as_persona_dict_list(obj: object) -> list[dict[str, object]]:
    if not isinstance(obj, list):
        return []
    out: list[dict[str, object]] = []
    for item in cast(list[object], obj):
        if isinstance(item, dict):
            out.append(_as_str_dict(cast(object, item)))
    return out


LIGHTWEIGHT_PHASE_TIMEOUT_SECONDS: int = 120
QA_PHASE_TIMEOUT_SECONDS: int = 300


@dataclass
class BudgetConfig:
    per_phase: float = 5.0
    per_run: float = 15.0
    max_duration_hours: float = 8.0
    max_total_usd: float = 500.0
    phase_timeout_seconds: int = 1800


@dataclass
class PhasesConfig:
    plan: bool = True
    implement: bool = True
    review: bool = True
    deliver: bool = True
    verify: bool = True


@dataclass
class VerifyConfig:
    """Configuration for the pre-delivery test verification phase."""

    max_fix_attempts: int = 2


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

    enabled: bool = False
    max_parallel_agents: int = 3
    conflict_strategy: str = "auto"
    merge_timeout_seconds: int = 60
    worktree_cleanup: bool = True


@dataclass
class PRReviewConfig:
    """Configuration for PR review comment auto-fix feature."""

    budget_per_pr: float = 5.0
    max_fix_rounds_per_pr: int = 3
    poll_interval_seconds: int = 60
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown_minutes: int = 15


@dataclass
class RouterConfig:
    """Configuration for the Intent Router Agent.

    The router classifies user input before running the full pipeline,
    enabling quick Q&A responses for questions and routing code changes
    to the appropriate execution path.
    """

    enabled: bool = True
    model: str = "haiku"
    qa_model: str = "opus"
    confidence_threshold: float = 0.7
    small_fix_threshold: float = 0.85
    qa_budget: float = 0.50


@dataclass
class RepoMapConfig:
    """Configuration for the repository map injected into agent prompts."""

    enabled: bool = True
    max_tokens: int = 4000
    max_files: int = 2000
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class MemoryConfig:
    """Configuration for the persistent memory system."""

    enabled: bool = True
    max_entries: int = 500
    max_inject_tokens: int = 1500
    capture_failures: bool = True


@dataclass
class RetryConfig:
    """Configuration for transient error (529/503) retry with exponential backoff."""

    max_attempts: int = 3
    base_delay_seconds: float = 10.0
    max_delay_seconds: float = 120.0
    fallback_model: str | None = None


@dataclass
class RecoveryConfig:
    """Configuration for automatic recovery and nuke escalation."""

    enabled: bool = True
    max_phase_retries: int = 1
    max_task_retries: int = 1
    allow_nuke: bool = True
    max_nuke_attempts: int = 1
    incident_char_cap: int = 4000


@dataclass
class SweepConfig:
    max_tasks: int = 5
    max_files_per_task: int = 5
    default_categories: list[str] = field(default_factory=lambda: ["bugs", "dead_code", "error_handling", "complexity", "consistency"])


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
    notification_mode: str = "daily"
    daily_thread_hour: int = 8
    daily_thread_timezone: str = "UTC"


_VALID_NOTIFICATION_MODES: frozenset[str] = frozenset({"daily", "per_item"})


@dataclass
class PRSyncConfig:
    """Configuration for automatic PR sync with main."""

    enabled: bool = False
    interval_minutes: int = 60
    max_sync_failures: int = 3


@dataclass
class DaemonConfig:
    """Configuration for daemon mode (FR-12)."""

    daily_budget_usd: float | None = 500.0
    github_poll_interval_seconds: int = 120
    ceo_cooldown_minutes: int = 60
    cleanup_interval_hours: int = 24
    max_cleanup_items: int = 3
    heartbeat_interval_minutes: int = 240
    digest_hour_utc: int = 14
    max_consecutive_failures: int = 3
    circuit_breaker_cooldown_minutes: int = 30
    outcome_poll_interval_minutes: int = 30
    issue_labels: list[str] = field(default_factory=list)
    allowed_control_user_ids: list[str] = field(default_factory=list)
    allow_all_control_users: bool = False
    auto_recover_dirty_worktree: bool = True
    pipeline_timeout_seconds: int = 7200
    watchdog_stall_seconds: int = 1920
    dashboard_enabled: bool = True
    dashboard_port: int = 8741
    dashboard_write_enabled: bool = False
    pr_sync: PRSyncConfig = field(default_factory=PRSyncConfig)
    self_update: bool = False
    self_update_command: str = "uv pip install ."
    maintenance_budget_usd: float = 20.0
    max_ci_fix_items: int = 2
    branch_sync_enabled: bool = True


@dataclass
class ColonyConfig:
    project: ProjectInfo | None = None
    personas: list[Persona] = field(default_factory=list)
    model: str = "opus"
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
    user_directions: str = ""
    directions_auto_update: bool = True
    max_fix_iterations: int = 2
    auto_approve: bool = False
    learnings: LearningsConfig = field(default_factory=LearningsConfig)
    ci_fix: CIFixConfig = field(default_factory=CIFixConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    pr_review: PRReviewConfig = field(default_factory=PRReviewConfig)
    parallel_implement: ParallelImplementConfig = field(default_factory=ParallelImplementConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    sweep: SweepConfig = field(default_factory=SweepConfig)
    repo_map: RepoMapConfig = field(default_factory=RepoMapConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    ceo_profiles: list[Persona] = field(default_factory=list)
    max_log_files: int = 50

    def get_model(self, phase: Phase) -> str:
        """Return the model for a phase, falling back to the global default."""
        return self.phase_models.get(phase.value, self.model)


def _parse_personas(raw: list[dict[str, object]]) -> list[Persona]:
    return [
        Persona(
            role=_coerce_str(p.get("role"), ""),
            expertise=_coerce_str(p.get("expertise"), ""),
            perspective=_coerce_str(p.get("perspective"), ""),
            reviewer=bool(p.get("reviewer", False)),
        )
        for p in raw
        if p.get("role")
    ]


def _parse_persona(raw: dict[str, object]) -> Persona | None:
    if not raw.get("role"):
        return None
    return Persona(
        role=_coerce_str(raw.get("role"), ""),
        expertise=_coerce_str(raw.get("expertise"), ""),
        perspective=_coerce_str(raw.get("perspective"), ""),
        reviewer=bool(raw.get("reviewer", False)),
    )


def _parse_project(raw: dict[str, object]) -> ProjectInfo | None:
    if not raw.get("name"):
        return None
    return ProjectInfo(
        name=_coerce_str(raw.get("name"), ""),
        description=_coerce_str(raw.get("description"), ""),
        stack=_coerce_str(raw.get("stack"), ""),
    )


_VALID_TRIGGER_MODES: frozenset[str] = frozenset({"mention", "reaction", "slash_command", "all"})


def _parse_slack_config(raw: dict[str, object]) -> SlackConfig:
    """Parse the ``slack`` section from config.yaml."""
    if not raw:
        return SlackConfig()
    trigger_mode = _coerce_str(raw.get("trigger_mode"), "mention")
    if trigger_mode not in _VALID_TRIGGER_MODES:
        raise ValueError(
            f"Invalid slack trigger_mode '{trigger_mode}'. Valid options: {sorted(_VALID_TRIGGER_MODES)}"
        )
    max_queue_depth = _coerce_int(raw.get("max_queue_depth"), 20)
    if max_queue_depth < 1:
        raise ValueError(
            f"slack.max_queue_depth must be positive, got {max_queue_depth}"
        )
    max_consecutive_failures = _coerce_int(raw.get("max_consecutive_failures"), 3)
    if max_consecutive_failures < 1:
        raise ValueError(
            f"slack.max_consecutive_failures must be positive, got {max_consecutive_failures}"
        )
    circuit_breaker_cooldown_minutes = _coerce_int(raw.get("circuit_breaker_cooldown_minutes"), 30)
    if circuit_breaker_cooldown_minutes < 1:
        raise ValueError(
            f"slack.circuit_breaker_cooldown_minutes must be positive, got {circuit_breaker_cooldown_minutes}"
        )
    max_fix_rounds_per_thread = _coerce_int(raw.get("max_fix_rounds_per_thread"), 3)
    if max_fix_rounds_per_thread < 1:
        raise ValueError(
            f"slack.max_fix_rounds_per_thread must be positive, got {max_fix_rounds_per_thread}"
        )
    max_runs_per_hour = _coerce_int(raw.get("max_runs_per_hour"), 3)
    if max_runs_per_hour < 1:
        raise ValueError(
            f"slack.max_runs_per_hour must be positive, got {max_runs_per_hour}"
        )
    daily_budget_raw = raw.get("daily_budget_usd")
    daily_budget_usd: float | None = None
    if daily_budget_raw is not None:
        daily_budget_usd = _coerce_float(daily_budget_raw, 0.0)
        if daily_budget_usd <= 0:
            raise ValueError(
                f"slack.daily_budget_usd must be positive, got {daily_budget_usd}"
            )
    allowed_user_ids_raw = _coerce_str_list(raw.get("allowed_user_ids"), [])
    enabled = bool(raw.get("enabled", False))
    auto_approve = bool(raw.get("auto_approve", False))

    notification_mode = _coerce_str(raw.get("notification_mode"), "daily")
    if notification_mode not in _VALID_NOTIFICATION_MODES:
        raise ValueError(
            f"Invalid slack notification_mode '{notification_mode}'. Valid options: {sorted(_VALID_NOTIFICATION_MODES)}"
        )

    daily_thread_hour = _coerce_int(raw.get("daily_thread_hour"), 8)
    if daily_thread_hour < 0 or daily_thread_hour > 23:
        raise ValueError(
            f"slack.daily_thread_hour must be 0-23, got {daily_thread_hour}"
        )

    daily_thread_timezone = _coerce_str(raw.get("daily_thread_timezone"), "UTC")
    try:
        _ = ZoneInfo(daily_thread_timezone)
    except Exception:
        logger.warning(
            "Invalid timezone '%s', falling back to UTC",
            daily_thread_timezone,
        )
        daily_thread_timezone = "UTC"

    return SlackConfig(
        enabled=enabled,
        channels=_coerce_str_list(raw.get("channels"), []),
        trigger_mode=trigger_mode,
        auto_approve=auto_approve,
        max_runs_per_hour=max_runs_per_hour,
        allowed_user_ids=allowed_user_ids_raw,
        triage_scope=_coerce_str(raw.get("triage_scope"), ""),
        daily_budget_usd=daily_budget_usd,
        max_queue_depth=max_queue_depth,
        triage_verbose=bool(raw.get("triage_verbose", False)),
        max_consecutive_failures=max_consecutive_failures,
        circuit_breaker_cooldown_minutes=circuit_breaker_cooldown_minutes,
        max_fix_rounds_per_thread=max_fix_rounds_per_thread,
        notification_mode=notification_mode,
        daily_thread_hour=daily_thread_hour,
        daily_thread_timezone=daily_thread_timezone,
    )


def _parse_verify_config(raw: dict[str, object]) -> VerifyConfig:
    """Parse the ``verify`` section from config.yaml."""
    if not raw:
        return VerifyConfig()
    vd = _defaults_section("verify")
    fb = _coerce_int(vd.get("max_fix_attempts"), 2)
    max_fix_attempts = _coerce_int(raw.get("max_fix_attempts", fb), fb)
    if max_fix_attempts < 1:
        raise ValueError(
            f"verify.max_fix_attempts must be positive, got {max_fix_attempts}"
        )
    return VerifyConfig(max_fix_attempts=max_fix_attempts)


def _parse_ci_fix_config(raw: dict[str, object]) -> CIFixConfig:
    """Parse the ``ci_fix`` section from config.yaml."""
    if not raw:
        return CIFixConfig()
    ci_fix_defaults = _defaults_section("ci_fix")
    mr_fb = _coerce_int(ci_fix_defaults.get("max_retries"), 2)
    max_retries = _coerce_int(raw.get("max_retries", mr_fb), mr_fb)
    if max_retries < 0:
        raise ValueError(
            f"ci_fix.max_retries must be non-negative, got {max_retries}"
        )
    wt_fb = _coerce_int(ci_fix_defaults.get("wait_timeout"), 600)
    wait_timeout = _coerce_int(raw.get("wait_timeout", wt_fb), wt_fb)
    if wait_timeout < 0:
        raise ValueError(
            f"ci_fix.wait_timeout must be non-negative, got {wait_timeout}"
        )
    lc_fb = _coerce_int(ci_fix_defaults.get("log_char_cap"), 12_000)
    log_char_cap = _coerce_int(raw.get("log_char_cap", lc_fb), lc_fb)
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


def _parse_pr_review_config(raw: dict[str, object]) -> PRReviewConfig:
    """Parse the ``pr_review`` section from config.yaml."""
    if not raw:
        return PRReviewConfig()
    budget_per_pr = _coerce_float(raw.get("budget_per_pr"), 5.0)
    if budget_per_pr <= 0:
        raise ValueError(
            f"pr_review.budget_per_pr must be positive, got {budget_per_pr}"
        )
    max_fix_rounds_per_pr = _coerce_int(raw.get("max_fix_rounds_per_pr"), 3)
    if max_fix_rounds_per_pr < 1:
        raise ValueError(
            f"pr_review.max_fix_rounds_per_pr must be positive, got {max_fix_rounds_per_pr}"
        )
    poll_interval_seconds = _coerce_int(raw.get("poll_interval_seconds"), 60)
    if poll_interval_seconds < 1:
        raise ValueError(
            f"pr_review.poll_interval_seconds must be positive, got {poll_interval_seconds}"
        )
    circuit_breaker_threshold = _coerce_int(raw.get("circuit_breaker_threshold"), 3)
    if circuit_breaker_threshold < 1:
        raise ValueError(
            f"pr_review.circuit_breaker_threshold must be positive, got {circuit_breaker_threshold}"
        )
    circuit_breaker_cooldown_minutes = _coerce_int(raw.get("circuit_breaker_cooldown_minutes"), 15)
    if circuit_breaker_cooldown_minutes < 1:
        raise ValueError(
            f"pr_review.circuit_breaker_cooldown_minutes must be positive, got {circuit_breaker_cooldown_minutes}"
        )
    return PRReviewConfig(
        budget_per_pr=budget_per_pr,
        max_fix_rounds_per_pr=max_fix_rounds_per_pr,
        poll_interval_seconds=poll_interval_seconds,
        circuit_breaker_threshold=circuit_breaker_threshold,
        circuit_breaker_cooldown_minutes=circuit_breaker_cooldown_minutes,
    )


def _parse_cleanup_config(raw: dict[str, object]) -> CleanupConfig:
    """Parse the ``cleanup`` section from config.yaml."""
    if not raw:
        return CleanupConfig()
    cd = _defaults_section("cleanup")
    br_fb = _coerce_int(cd.get("branch_retention_days"), 0)
    branch_retention_days = _coerce_int(raw.get("branch_retention_days", br_fb), br_fb)
    if branch_retention_days < 0:
        raise ValueError(
            f"cleanup.branch_retention_days must be non-negative, got {branch_retention_days}"
        )
    ar_fb = _coerce_int(cd.get("artifact_retention_days"), 30)
    artifact_retention_days = _coerce_int(raw.get("artifact_retention_days", ar_fb), ar_fb)
    if artifact_retention_days < 0:
        raise ValueError(
            f"cleanup.artifact_retention_days must be non-negative, got {artifact_retention_days}"
        )
    sml_fb = _coerce_int(cd.get("scan_max_lines"), 500)
    scan_max_lines = _coerce_int(raw.get("scan_max_lines", sml_fb), sml_fb)
    if scan_max_lines < 1:
        raise ValueError(
            f"cleanup.scan_max_lines must be positive, got {scan_max_lines}"
        )
    smf_fb = _coerce_int(cd.get("scan_max_functions"), 20)
    scan_max_functions = _coerce_int(raw.get("scan_max_functions", smf_fb), smf_fb)
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


def _parse_parallel_implement_config(raw: dict[str, object]) -> ParallelImplementConfig:
    """Parse the ``parallel_implement`` section from config.yaml."""
    if not raw:
        return ParallelImplementConfig()

    defaults = _defaults_section("parallel_implement")

    enabled = bool(raw.get("enabled", defaults.get("enabled")))

    if "enabled" in raw and raw["enabled"] is True:
        logger.warning(
            "parallel_implement.enabled is True — parallel mode risks merge conflicts when tasks "
            + "touch overlapping files. Consider using sequential mode (the default) for safer, "
            + "incremental implementation."
        )

    mpa_fb = _coerce_int(defaults.get("max_parallel_agents"), 3)
    max_parallel_agents = _coerce_int(raw.get("max_parallel_agents", mpa_fb), mpa_fb)
    if max_parallel_agents < 1:
        raise ValueError(
            f"parallel_implement.max_parallel_agents must be positive, got {max_parallel_agents}"
        )

    cs_fb = _coerce_str(defaults.get("conflict_strategy"), "auto")
    conflict_strategy = _coerce_str(raw.get("conflict_strategy", cs_fb), cs_fb)
    if conflict_strategy not in VALID_CONFLICT_STRATEGIES:
        raise ValueError(
            f"Invalid conflict_strategy '{conflict_strategy}'. Valid options: {sorted(VALID_CONFLICT_STRATEGIES)}"
        )

    mts_fb = _coerce_int(defaults.get("merge_timeout_seconds"), 60)
    merge_timeout_seconds = _coerce_int(raw.get("merge_timeout_seconds", mts_fb), mts_fb)
    if merge_timeout_seconds < 1:
        raise ValueError(
            f"parallel_implement.merge_timeout_seconds must be positive, got {merge_timeout_seconds}"
        )

    wc_fb = bool(defaults.get("worktree_cleanup", True))
    worktree_cleanup = bool(raw.get("worktree_cleanup", wc_fb))

    return ParallelImplementConfig(
        enabled=enabled,
        max_parallel_agents=max_parallel_agents,
        conflict_strategy=conflict_strategy,
        merge_timeout_seconds=merge_timeout_seconds,
        worktree_cleanup=worktree_cleanup,
    )


def _parse_router_config(raw: dict[str, object]) -> RouterConfig:
    """Parse the ``router`` section from config.yaml."""
    if not raw:
        return RouterConfig()

    defaults = _defaults_section("router")

    enabled = bool(raw.get("enabled", defaults.get("enabled", False)))

    m_fb = _coerce_str(defaults.get("model"), "haiku")
    model = _coerce_str(raw.get("model", m_fb), m_fb)
    if model not in VALID_MODELS:
        raise ValueError(
            f"Invalid router model '{model}'. Valid options: {sorted(VALID_MODELS)}. Note: use short names (e.g. 'haiku') not full model IDs."
        )

    qm_fb = _coerce_str(defaults.get("qa_model"), "opus")
    qa_model = _coerce_str(raw.get("qa_model", qm_fb), qm_fb)
    if qa_model not in VALID_MODELS:
        raise ValueError(
            f"Invalid router qa_model '{qa_model}'. Valid options: {sorted(VALID_MODELS)}. Note: use short names (e.g. 'sonnet') not full model IDs."
        )

    ct_fb = _coerce_float(defaults.get("confidence_threshold"), 0.7)
    confidence_threshold = _coerce_float(raw.get("confidence_threshold", ct_fb), ct_fb)
    if confidence_threshold < 0 or confidence_threshold > 1:
        raise ValueError(
            f"router.confidence_threshold must be between 0 and 1, got {confidence_threshold}"
        )

    sft_fb = _coerce_float(defaults.get("small_fix_threshold"), 0.85)
    small_fix_threshold = _coerce_float(raw.get("small_fix_threshold", sft_fb), sft_fb)
    if small_fix_threshold < 0 or small_fix_threshold > 1:
        raise ValueError(
            f"router.small_fix_threshold must be between 0 and 1, got {small_fix_threshold}"
        )

    qb_fb = _coerce_float(defaults.get("qa_budget"), 0.50)
    qa_budget = _coerce_float(raw.get("qa_budget", qb_fb), qb_fb)
    if qa_budget <= 0:
        raise ValueError(
            f"router.qa_budget must be positive, got {qa_budget}"
        )

    return RouterConfig(
        enabled=enabled,
        model=model,
        qa_model=qa_model,
        confidence_threshold=confidence_threshold,
        small_fix_threshold=small_fix_threshold,
        qa_budget=qa_budget,
    )


def _parse_repo_map_config(raw: dict[str, object]) -> RepoMapConfig:
    """Parse the ``repo_map`` section from config.yaml."""
    if not raw:
        return RepoMapConfig()
    defaults = _defaults_section("repo_map")
    enabled = bool(raw.get("enabled", defaults.get("enabled", False)))
    mt_fb = _coerce_int(defaults.get("max_tokens"), 4000)
    max_tokens = _coerce_int(raw.get("max_tokens", mt_fb), mt_fb)
    if max_tokens < 1:
        raise ValueError(f"repo_map.max_tokens must be positive, got {max_tokens}")
    mf_fb = _coerce_int(defaults.get("max_files"), 2000)
    max_files = _coerce_int(raw.get("max_files", mf_fb), mf_fb)
    if max_files < 1:
        raise ValueError(f"repo_map.max_files must be positive, got {max_files}")
    inc_def = _coerce_str_list(defaults.get("include_patterns"), [])
    exc_def = _coerce_str_list(defaults.get("exclude_patterns"), [])
    include_patterns = _coerce_str_list(raw.get("include_patterns"), inc_def)
    exclude_patterns = _coerce_str_list(raw.get("exclude_patterns"), exc_def)
    return RepoMapConfig(
        enabled=enabled,
        max_tokens=max_tokens,
        max_files=max_files,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )


def _parse_memory_config(raw: dict[str, object]) -> MemoryConfig:
    """Parse the ``memory`` section from config.yaml."""
    if not raw:
        return MemoryConfig()
    defaults = _defaults_section("memory")
    enabled = bool(raw.get("enabled", defaults.get("enabled", False)))
    me_fb = _coerce_int(defaults.get("max_entries"), 500)
    max_entries = _coerce_int(raw.get("max_entries", me_fb), me_fb)
    if max_entries < 1:
        raise ValueError(f"memory.max_entries must be positive, got {max_entries}")
    mit_fb = _coerce_int(defaults.get("max_inject_tokens"), 1500)
    max_inject_tokens = _coerce_int(raw.get("max_inject_tokens", mit_fb), mit_fb)
    if max_inject_tokens < 0:
        raise ValueError(
            f"memory.max_inject_tokens must be non-negative, got {max_inject_tokens}"
        )
    capture_failures = bool(raw.get("capture_failures", defaults.get("capture_failures", True)))
    return MemoryConfig(
        enabled=enabled,
        max_entries=max_entries,
        max_inject_tokens=max_inject_tokens,
        capture_failures=capture_failures,
    )


def _parse_retry_config(raw: dict[str, object]) -> RetryConfig:
    """Parse the ``retry`` section from config.yaml."""
    if not raw:
        return RetryConfig()
    defaults = _defaults_section("retry")
    ma_fb = _coerce_int(defaults.get("max_attempts"), 3)
    max_attempts = _coerce_int(raw.get("max_attempts", ma_fb), ma_fb)
    if max_attempts < 1:
        raise ValueError(
            f"retry.max_attempts must be positive, got {max_attempts}"
        )
    if max_attempts > 10:
        logger.warning(
            "retry.max_attempts=%d is unusually high (max recommended: 10). Combined with fallback, "
            + "this could result in up to %d total attempts.",
            max_attempts,
            max_attempts * 2,
        )
    bd_fb = _coerce_float(defaults.get("base_delay_seconds"), 10.0)
    base_delay_seconds = _coerce_float(raw.get("base_delay_seconds", bd_fb), bd_fb)
    if base_delay_seconds < 0:
        raise ValueError(
            f"retry.base_delay_seconds must be non-negative, got {base_delay_seconds}"
        )
    md_fb = _coerce_float(defaults.get("max_delay_seconds"), 120.0)
    max_delay_seconds = _coerce_float(raw.get("max_delay_seconds", md_fb), md_fb)
    if max_delay_seconds < 0:
        raise ValueError(
            f"retry.max_delay_seconds must be non-negative, got {max_delay_seconds}"
        )
    fallback_model_raw = raw.get("fallback_model", defaults.get("fallback_model"))
    fallback_model: str | None = None
    if fallback_model_raw is not None:
        fallback_model = _coerce_str(fallback_model_raw, "")
        if fallback_model not in VALID_MODELS:
            raise ValueError(
                f"Invalid retry fallback_model '{fallback_model}'. Valid options: {sorted(VALID_MODELS)}. Note: use short names (e.g. 'sonnet') not full model IDs."
            )
    return RetryConfig(
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        fallback_model=fallback_model,
    )


def _parse_recovery_config(raw: dict[str, object]) -> RecoveryConfig:
    """Parse the ``recovery`` section from config.yaml."""
    if not raw:
        return RecoveryConfig()
    defaults = _defaults_section("recovery")
    enabled = bool(raw.get("enabled", defaults.get("enabled", False)))
    mpr_fb = _coerce_int(defaults.get("max_phase_retries"), 1)
    max_phase_retries = _coerce_int(raw.get("max_phase_retries", mpr_fb), mpr_fb)
    if max_phase_retries < 0:
        raise ValueError(
            f"recovery.max_phase_retries must be non-negative, got {max_phase_retries}"
        )
    mtr_fb = _coerce_int(defaults.get("max_task_retries"), 1)
    max_task_retries = _coerce_int(raw.get("max_task_retries", mtr_fb), mtr_fb)
    if max_task_retries < 0:
        raise ValueError(
            f"recovery.max_task_retries must be non-negative, got {max_task_retries}"
        )
    allow_nuke = bool(raw.get("allow_nuke", defaults.get("allow_nuke", True)))
    mna_fb = _coerce_int(defaults.get("max_nuke_attempts"), 1)
    max_nuke_attempts = _coerce_int(raw.get("max_nuke_attempts", mna_fb), mna_fb)
    if max_nuke_attempts < 0:
        raise ValueError(
            f"recovery.max_nuke_attempts must be non-negative, got {max_nuke_attempts}"
        )
    icc_fb = _coerce_int(defaults.get("incident_char_cap"), 4000)
    incident_char_cap = _coerce_int(raw.get("incident_char_cap", icc_fb), icc_fb)
    if incident_char_cap < 200:
        raise ValueError(
            f"recovery.incident_char_cap must be at least 200, got {incident_char_cap}"
        )
    return RecoveryConfig(
        enabled=enabled,
        max_phase_retries=max_phase_retries,
        max_task_retries=max_task_retries,
        allow_nuke=allow_nuke,
        max_nuke_attempts=max_nuke_attempts,
        incident_char_cap=incident_char_cap,
    )


def _parse_pr_sync_config(raw: dict[str, object]) -> PRSyncConfig:
    """Parse the ``pr_sync`` section from the daemon config."""
    if not raw:
        return PRSyncConfig()
    d = _defaults_section("daemon")
    pr_raw = d.get("pr_sync")
    pr = _as_str_dict(pr_raw if pr_raw is not None else {})
    im_fb = _coerce_int(pr.get("interval_minutes"), 60)
    interval_minutes = _coerce_int(raw.get("interval_minutes", im_fb), im_fb)
    if interval_minutes < 1:
        raise ValueError(
            f"pr_sync.interval_minutes must be >= 1, got {interval_minutes}"
        )
    msf_fb = _coerce_int(pr.get("max_sync_failures"), 3)
    max_sync_failures = _coerce_int(raw.get("max_sync_failures", msf_fb), msf_fb)
    if max_sync_failures < 1:
        raise ValueError(
            f"pr_sync.max_sync_failures must be >= 1, got {max_sync_failures}"
        )
    en_fb = bool(pr.get("enabled", False))
    return PRSyncConfig(
        enabled=bool(raw.get("enabled", en_fb)),
        interval_minutes=interval_minutes,
        max_sync_failures=max_sync_failures,
    )


def _parse_daemon_config(raw: dict[str, object]) -> DaemonConfig:
    """Parse the ``daemon`` section from config.yaml."""
    if not raw:
        return DaemonConfig()
    d = _defaults_section("daemon")

    def _int(key: str) -> int:
        fb = _coerce_int(d.get(key), 0)
        return _coerce_int(raw.get(key, fb), fb)

    def _require_positive(name: str, val: float | int) -> None:
        if val < 1:
            raise ValueError(
                f"daemon.{name} must be positive, got {val}"
            )

    daily_budget_raw = raw.get("daily_budget_usd", d.get("daily_budget_usd"))
    daily_budget_usd: float | None
    if daily_budget_raw is None:
        daily_budget_usd = None
    elif isinstance(daily_budget_raw, str):
        normalized = daily_budget_raw.strip().lower()
        if normalized in {"unlimited", "none", "null", "infinite", "inf"}:
            daily_budget_usd = None
        else:
            daily_budget_usd = _coerce_float(daily_budget_raw, 0.0)
    else:
        daily_budget_usd = _coerce_float(daily_budget_raw, 0.0)
    if daily_budget_usd is not None and daily_budget_usd <= 0:
        raise ValueError(
            f"daemon.daily_budget_usd must be positive, got {daily_budget_usd}"
        )

    poll_interval = _int("github_poll_interval_seconds")
    if poll_interval < 10:
        raise ValueError(
            f"daemon.github_poll_interval_seconds must be >= 10, got {poll_interval}"
        )

    ceo_cooldown = _int("ceo_cooldown_minutes")
    _require_positive("ceo_cooldown_minutes", ceo_cooldown)

    cleanup_hours = _int("cleanup_interval_hours")
    _require_positive("cleanup_interval_hours", cleanup_hours)

    max_cleanup = _int("max_cleanup_items")
    _require_positive("max_cleanup_items", max_cleanup)

    heartbeat_mins = _int("heartbeat_interval_minutes")
    _require_positive("heartbeat_interval_minutes", heartbeat_mins)

    digest_hour = _int("digest_hour_utc")
    if digest_hour < 0 or digest_hour > 23:
        raise ValueError(
            f"daemon.digest_hour_utc must be 0-23, got {digest_hour}"
        )

    max_failures = _int("max_consecutive_failures")
    _require_positive("max_consecutive_failures", max_failures)

    cb_cooldown = _int("circuit_breaker_cooldown_minutes")
    _require_positive("circuit_breaker_cooldown_minutes", cb_cooldown)

    outcome_poll = _int("outcome_poll_interval_minutes")
    _require_positive("outcome_poll_interval_minutes", outcome_poll)

    pipeline_timeout = _int("pipeline_timeout_seconds")
    if pipeline_timeout < 60:
        raise ValueError(
            f"daemon.pipeline_timeout_seconds must be >= 60, got {pipeline_timeout}"
        )

    watchdog_stall = _int("watchdog_stall_seconds")
    if watchdog_stall < 120:
        logger.warning(
            "daemon.watchdog_stall_seconds=%d is below minimum 120; clamping to 120",
            watchdog_stall,
        )
        watchdog_stall = 120

    mb_fb = _coerce_float(d.get("maintenance_budget_usd"), 20.0)
    maintenance_budget = _coerce_float(raw.get("maintenance_budget_usd", mb_fb), mb_fb)
    if maintenance_budget <= 0:
        raise ValueError(
            f"daemon.maintenance_budget_usd must be positive, got {maintenance_budget}"
        )

    max_ci_fix = _int("max_ci_fix_items")
    _require_positive("max_ci_fix_items", max_ci_fix)

    return DaemonConfig(
        daily_budget_usd=daily_budget_usd,
        github_poll_interval_seconds=poll_interval,
        ceo_cooldown_minutes=ceo_cooldown,
        cleanup_interval_hours=cleanup_hours,
        max_cleanup_items=max_cleanup,
        heartbeat_interval_minutes=heartbeat_mins,
        digest_hour_utc=digest_hour,
        max_consecutive_failures=max_failures,
        circuit_breaker_cooldown_minutes=cb_cooldown,
        outcome_poll_interval_minutes=outcome_poll,
        issue_labels=_coerce_str_list(
            raw.get("issue_labels"), _coerce_str_list(d.get("issue_labels"), [])
        ),
        allowed_control_user_ids=_coerce_str_list(
            raw.get("allowed_control_user_ids"), _coerce_str_list(d.get("allowed_control_user_ids"), [])
        ),
        allow_all_control_users=bool(
            raw.get("allow_all_control_users", d.get("allow_all_control_users", False))
        ),
        auto_recover_dirty_worktree=bool(
            raw.get("auto_recover_dirty_worktree", d.get("auto_recover_dirty_worktree", True))
        ),
        pipeline_timeout_seconds=pipeline_timeout,
        watchdog_stall_seconds=watchdog_stall,
        dashboard_enabled=bool(raw.get("dashboard_enabled", True)),
        dashboard_port=_coerce_int(raw.get("dashboard_port"), 8741),
        dashboard_write_enabled=bool(raw.get("dashboard_write_enabled", False)),
        pr_sync=_parse_pr_sync_config(_as_str_dict(raw.get("pr_sync", {}))),
        self_update=bool(raw.get("self_update", d.get("self_update", False))),
        self_update_command=_coerce_str(
            raw.get("self_update_command"), _coerce_str(d.get("self_update_command"), "uv pip install .")
        ),
        maintenance_budget_usd=maintenance_budget,
        max_ci_fix_items=max_ci_fix,
        branch_sync_enabled=bool(
            raw.get("branch_sync_enabled", d.get("branch_sync_enabled", True))
        ),
    )


def _parse_sweep_config(raw: dict[str, object]) -> SweepConfig:
    """Parse the ``sweep`` section from config.yaml."""
    if not raw:
        return SweepConfig()
    defaults = _defaults_section("sweep")
    mt_fb = _coerce_int(defaults.get("max_tasks"), 5)
    max_tasks = _coerce_int(raw.get("max_tasks", mt_fb), mt_fb)
    if max_tasks < 1:
        raise ValueError(f"sweep.max_tasks must be positive, got {max_tasks}")
    mfpt_fb = _coerce_int(defaults.get("max_files_per_task"), 5)
    max_files_per_task = _coerce_int(raw.get("max_files_per_task", mfpt_fb), mfpt_fb)
    if max_files_per_task < 1:
        raise ValueError(f"sweep.max_files_per_task must be positive, got {max_files_per_task}")
    dc_def = _coerce_str_list(defaults.get("default_categories"), [])
    default_categories = _coerce_str_list(raw.get("default_categories"), dc_def)
    return SweepConfig(
        max_tasks=max_tasks,
        max_files_per_task=max_files_per_task,
        default_categories=default_categories,
    )


def _parse_phase_timeout(budget_raw: dict[str, object]) -> int:
    bd = _defaults_section("budget")
    pt_fb = _coerce_int(bd.get("phase_timeout_seconds"), 1800)
    val = _coerce_int(budget_raw.get("phase_timeout_seconds", pt_fb), pt_fb)
    if val < 30:
        raise ValueError(
            f"budget.phase_timeout_seconds must be >= 30, got {val}"
        )
    return val


def load_config(repo_root: Path) -> ColonyConfig:
    config_path = repo_root / CONFIG_DIR / CONFIG_FILE
    if not config_path.exists():
        return ColonyConfig()

    raw_obj: object = cast(object, yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    raw = _as_str_dict(raw_obj)

    budget_raw = _as_str_dict(raw.get("budget", {}))
    phases_raw = _as_str_dict(raw.get("phases", {}))

    model_val = _coerce_str(raw.get("model"), _coerce_str(DEFAULTS.get("model"), "opus"))
    if model_val not in VALID_MODELS:
        raise ValueError(
            f"Invalid model '{model_val}'. Valid options: {sorted(VALID_MODELS)}. Note: use short names (e.g. 'opus') not full model IDs (e.g. 'claude-opus-4-20250514')."
        )

    phase_models_raw = _as_str_str_dict(raw.get("phase_models", {}))
    valid_phase_values = {p.value for p in Phase}
    for phase_key, model_name in phase_models_raw.items():
        if phase_key not in valid_phase_values:
            raise ValueError(
                f"Invalid phase key '{phase_key}' in phase_models. Valid phases: {sorted(valid_phase_values)}"
            )
        if model_name not in VALID_MODELS:
            raise ValueError(
                f"Invalid model '{model_name}' for phase '{phase_key}' in phase_models. Valid options: {sorted(VALID_MODELS)}. Note: use short names (e.g. 'opus') not full model IDs (e.g. 'claude-opus-4-20250514')."
            )

    for phase_key, model_name in phase_models_raw.items():
        if phase_key in SAFETY_CRITICAL_PHASES and model_name == "haiku":
            logger.warning(
                "Phase '%s' is assigned model 'haiku'. This phase serves as a safety gate in the pipeline — "
                + "using a lightweight model may reduce review quality. Consider using 'sonnet' or 'opus'.",
                phase_key,
            )

    ceo_persona_raw = raw.get("ceo_persona")
    ceo_persona = (
        _parse_persona(_as_str_dict(cast(object, ceo_persona_raw)))
        if isinstance(ceo_persona_raw, dict)
        else None
    )

    bd = _defaults_section("budget")
    pp_fb = _coerce_float(bd.get("per_phase"), 5.0)
    pr_fb = _coerce_float(bd.get("per_run"), 15.0)
    mdh_fb = _coerce_float(bd.get("max_duration_hours"), 8.0)
    mtu_fb = _coerce_float(bd.get("max_total_usd"), 500.0)

    ld = _defaults_section("learnings")
    learn_raw = _as_str_dict(raw.get("learnings", {}))
    me_l_fb = _coerce_int(ld.get("max_entries"), 100)

    return ColonyConfig(
        project=_parse_project(_as_str_dict(raw.get("project", {}))),
        personas=_parse_personas(_as_persona_dict_list(raw.get("personas", []))),
        model=model_val,
        phase_models=phase_models_raw,
        budget=BudgetConfig(
            per_phase=_coerce_float(budget_raw.get("per_phase", pp_fb), pp_fb),
            per_run=_coerce_float(budget_raw.get("per_run", pr_fb), pr_fb),
            max_duration_hours=_coerce_float(budget_raw.get("max_duration_hours", mdh_fb), mdh_fb),
            max_total_usd=_coerce_float(budget_raw.get("max_total_usd", mtu_fb), mtu_fb),
            phase_timeout_seconds=_parse_phase_timeout(budget_raw),
        ),
        phases=PhasesConfig(
            plan=bool(phases_raw.get("plan", True)),
            implement=bool(phases_raw.get("implement", True)),
            review=bool(phases_raw.get("review", True)),
            deliver=bool(phases_raw.get("deliver", True)),
            verify=bool(phases_raw.get("verify", True)),
        ),
        branch_prefix=_coerce_str(raw.get("branch_prefix"), _coerce_str(DEFAULTS.get("branch_prefix"), "colonyos/")),
        prds_dir=_coerce_str(raw.get("prds_dir"), _coerce_str(DEFAULTS.get("prds_dir"), "cOS_prds")),
        tasks_dir=_coerce_str(raw.get("tasks_dir"), _coerce_str(DEFAULTS.get("tasks_dir"), "cOS_tasks")),
        reviews_dir=_coerce_str(raw.get("reviews_dir"), _coerce_str(DEFAULTS.get("reviews_dir"), "cOS_reviews")),
        proposals_dir=_coerce_str(raw.get("proposals_dir"), _coerce_str(DEFAULTS.get("proposals_dir"), "cOS_proposals")),
        ceo_persona=ceo_persona,
        vision=_coerce_str(raw.get("vision"), ""),
        user_directions=_coerce_str(raw.get("user_directions"), ""),
        directions_auto_update=bool(raw.get("directions_auto_update", True)),
        max_fix_iterations=_coerce_int(raw.get("max_fix_iterations"), _coerce_int(DEFAULTS.get("max_fix_iterations"), 2)),
        auto_approve=bool(raw.get("auto_approve", False)),
        learnings=LearningsConfig(
            enabled=bool(learn_raw.get("enabled", ld.get("enabled", True))),
            max_entries=_coerce_int(learn_raw.get("max_entries", me_l_fb), me_l_fb),
        ),
        ci_fix=_parse_ci_fix_config(_as_str_dict(raw.get("ci_fix", {}))),
        slack=_parse_slack_config(_as_str_dict(raw.get("slack", {}))),
        cleanup=_parse_cleanup_config(_as_str_dict(raw.get("cleanup", {}))),
        pr_review=_parse_pr_review_config(_as_str_dict(raw.get("pr_review", {}))),
        parallel_implement=_parse_parallel_implement_config(_as_str_dict(raw.get("parallel_implement", {}))),
        router=_parse_router_config(_as_str_dict(raw.get("router", {}))),
        sweep=_parse_sweep_config(_as_str_dict(raw.get("sweep", {}))),
        repo_map=_parse_repo_map_config(_as_str_dict(raw.get("repo_map", {}))),
        memory=_parse_memory_config(_as_str_dict(raw.get("memory", {}))),
        retry=_parse_retry_config(_as_str_dict(raw.get("retry", {}))),
        verify=_parse_verify_config(_as_str_dict(raw.get("verify", {}))),
        recovery=_parse_recovery_config(_as_str_dict(raw.get("recovery", {}))),
        daemon=_parse_daemon_config(_as_str_dict(raw.get("daemon", {}))),
        ceo_profiles=_parse_personas(_as_persona_dict_list(raw.get("ceo_profiles", []))),
        max_log_files=_coerce_int(raw.get("max_log_files"), 50),
    )


def save_config(repo_root: Path, config: ColonyConfig) -> Path:
    config_dir = repo_root / CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    vd = _defaults_section("verify")
    cd = _defaults_section("ci_fix")
    cld = _defaults_section("cleanup")
    rd = _defaults_section("retry")
    pid = _defaults_section("parallel_implement")
    router_d = _defaults_section("router")
    sweep_d = _defaults_section("sweep")
    rmd = _defaults_section("repo_map")
    memd = _defaults_section("memory")
    recd = _defaults_section("recovery")
    dd = _defaults_section("daemon")
    pr_def = _as_str_dict(dd.get("pr_sync"))

    data: dict[str, object] = {}

    def _persona_to_dict(persona: Persona) -> dict[str, str | bool]:
        return {
            "role": persona.role,
            "expertise": persona.expertise,
            "perspective": persona.perspective,
            "reviewer": persona.reviewer,
        }

    if config.project:
        data["project"] = {
            "name": config.project.name,
            "description": config.project.description,
            "stack": config.project.stack,
        }

    if config.personas:
        data["personas"] = [_persona_to_dict(p) for p in config.personas]

    data["model"] = config.model
    if config.phase_models:
        data["phase_models"] = dict(config.phase_models)
    data["budget"] = {
        "per_phase": config.budget.per_phase,
        "per_run": config.budget.per_run,
        "max_duration_hours": config.budget.max_duration_hours,
        "max_total_usd": config.budget.max_total_usd,
        "phase_timeout_seconds": config.budget.phase_timeout_seconds,
    }
    data["phases"] = {
        "plan": config.phases.plan,
        "implement": config.phases.implement,
        "review": config.phases.review,
        "deliver": config.phases.deliver,
        "verify": config.phases.verify,
    }
    data["branch_prefix"] = config.branch_prefix
    data["prds_dir"] = config.prds_dir
    data["tasks_dir"] = config.tasks_dir
    data["reviews_dir"] = config.reviews_dir
    data["proposals_dir"] = config.proposals_dir

    data["max_fix_iterations"] = config.max_fix_iterations
    data["auto_approve"] = config.auto_approve

    if config.verify.max_fix_attempts != _coerce_int(vd.get("max_fix_attempts"), 2):
        data["verify"] = {
            "max_fix_attempts": config.verify.max_fix_attempts,
        }

    data["learnings"] = {
        "enabled": config.learnings.enabled,
        "max_entries": config.learnings.max_entries,
    }

    if config.ci_fix.enabled or config.ci_fix.max_retries != _coerce_int(cd.get("max_retries"), 2):
        data["ci_fix"] = {
            "enabled": config.ci_fix.enabled,
            "max_retries": config.ci_fix.max_retries,
            "wait_timeout": config.ci_fix.wait_timeout,
            "log_char_cap": config.ci_fix.log_char_cap,
        }

    if config.slack.enabled or config.slack.channels:
        slack_data: dict[str, object] = {
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
            "notification_mode": config.slack.notification_mode,
            "daily_thread_hour": config.slack.daily_thread_hour,
            "daily_thread_timezone": config.slack.daily_thread_timezone,
        }
        if config.slack.triage_scope:
            slack_data["triage_scope"] = config.slack.triage_scope
        if config.slack.daily_budget_usd is not None:
            slack_data["daily_budget_usd"] = config.slack.daily_budget_usd
        data["slack"] = slack_data

    if (
        config.cleanup.branch_retention_days != _coerce_int(cld.get("branch_retention_days"), 0)
        or config.cleanup.artifact_retention_days != _coerce_int(cld.get("artifact_retention_days"), 30)
        or config.cleanup.scan_max_lines != _coerce_int(cld.get("scan_max_lines"), 500)
        or config.cleanup.scan_max_functions != _coerce_int(cld.get("scan_max_functions"), 20)
    ):
        data["cleanup"] = {
            "branch_retention_days": config.cleanup.branch_retention_days,
            "artifact_retention_days": config.cleanup.artifact_retention_days,
            "scan_max_lines": config.cleanup.scan_max_lines,
            "scan_max_functions": config.cleanup.scan_max_functions,
        }

    # Only persist pr_review if non-default values are set
    if (
        config.pr_review.budget_per_pr != 5.0
        or config.pr_review.max_fix_rounds_per_pr != 3
        or config.pr_review.poll_interval_seconds != 60
        or config.pr_review.circuit_breaker_threshold != 3
        or config.pr_review.circuit_breaker_cooldown_minutes != 15
    ):
        data["pr_review"] = {
            "budget_per_pr": config.pr_review.budget_per_pr,
            "max_fix_rounds_per_pr": config.pr_review.max_fix_rounds_per_pr,
            "poll_interval_seconds": config.pr_review.poll_interval_seconds,
            "circuit_breaker_threshold": config.pr_review.circuit_breaker_threshold,
            "circuit_breaker_cooldown_minutes": config.pr_review.circuit_breaker_cooldown_minutes,
        }

    if config.ceo_persona:
        data["ceo_persona"] = _persona_to_dict(config.ceo_persona)

    if (
        config.retry.max_attempts != _coerce_int(rd.get("max_attempts"), 3)
        or config.retry.base_delay_seconds != _coerce_float(rd.get("base_delay_seconds"), 10.0)
        or config.retry.max_delay_seconds != _coerce_float(rd.get("max_delay_seconds"), 120.0)
        or config.retry.fallback_model != rd.get("fallback_model")
    ):
        data["retry"] = {
            "max_attempts": config.retry.max_attempts,
            "base_delay_seconds": config.retry.base_delay_seconds,
            "max_delay_seconds": config.retry.max_delay_seconds,
            "fallback_model": config.retry.fallback_model,
        }

    if config.vision:
        data["vision"] = config.vision

    if config.user_directions:
        data["user_directions"] = config.user_directions

    # Only serialize parallel_implement if values differ from defaults
    if (
        config.parallel_implement.enabled != bool(pid.get("enabled", False))
        or config.parallel_implement.max_parallel_agents != _coerce_int(pid.get("max_parallel_agents"), 3)
        or config.parallel_implement.conflict_strategy != _coerce_str(pid.get("conflict_strategy"), "auto")
        or config.parallel_implement.merge_timeout_seconds != _coerce_int(pid.get("merge_timeout_seconds"), 60)
        or config.parallel_implement.worktree_cleanup != bool(pid.get("worktree_cleanup", True))
    ):
        data["parallel_implement"] = {
            "enabled": config.parallel_implement.enabled,
            "max_parallel_agents": config.parallel_implement.max_parallel_agents,
            "conflict_strategy": config.parallel_implement.conflict_strategy,
            "merge_timeout_seconds": config.parallel_implement.merge_timeout_seconds,
            "worktree_cleanup": config.parallel_implement.worktree_cleanup,
        }

    # Only serialize router if values differ from defaults
    if (
        config.router.enabled != bool(router_d.get("enabled", True))
        or config.router.model != _coerce_str(router_d.get("model"), "haiku")
        or config.router.qa_model != _coerce_str(router_d.get("qa_model"), "opus")
        or config.router.confidence_threshold != _coerce_float(router_d.get("confidence_threshold"), 0.7)
        or config.router.small_fix_threshold != _coerce_float(router_d.get("small_fix_threshold"), 0.85)
        or config.router.qa_budget != _coerce_float(router_d.get("qa_budget"), 0.50)
    ):
        data["router"] = {
            "enabled": config.router.enabled,
            "model": config.router.model,
            "qa_model": config.router.qa_model,
            "confidence_threshold": config.router.confidence_threshold,
            "small_fix_threshold": config.router.small_fix_threshold,
            "qa_budget": config.router.qa_budget,
        }

    # Only serialize sweep if values differ from defaults
    sweep_dc_def = _coerce_str_list(sweep_d.get("default_categories"), [])
    if (
        config.sweep.max_tasks != _coerce_int(sweep_d.get("max_tasks"), 5)
        or config.sweep.max_files_per_task != _coerce_int(sweep_d.get("max_files_per_task"), 5)
        or list(config.sweep.default_categories) != sweep_dc_def
    ):
        data["sweep"] = {
            "max_tasks": config.sweep.max_tasks,
            "max_files_per_task": config.sweep.max_files_per_task,
            "default_categories": list(config.sweep.default_categories),
        }

    # Only serialize repo_map if values differ from defaults
    rm_inc_def = _coerce_str_list(rmd.get("include_patterns"), [])
    rm_exc_def = _coerce_str_list(rmd.get("exclude_patterns"), [])
    if (
        config.repo_map.enabled != bool(rmd.get("enabled", True))
        or config.repo_map.max_tokens != _coerce_int(rmd.get("max_tokens"), 4000)
        or config.repo_map.max_files != _coerce_int(rmd.get("max_files"), 2000)
        or list(config.repo_map.include_patterns) != rm_inc_def
        or list(config.repo_map.exclude_patterns) != rm_exc_def
    ):
        data["repo_map"] = {
            "enabled": config.repo_map.enabled,
            "max_tokens": config.repo_map.max_tokens,
            "max_files": config.repo_map.max_files,
            "include_patterns": list(config.repo_map.include_patterns),
            "exclude_patterns": list(config.repo_map.exclude_patterns),
        }

    # Only serialize memory if values differ from defaults
    if (
        config.memory.enabled != bool(memd.get("enabled", True))
        or config.memory.max_entries != _coerce_int(memd.get("max_entries"), 500)
        or config.memory.max_inject_tokens != _coerce_int(memd.get("max_inject_tokens"), 1500)
        or config.memory.capture_failures != bool(memd.get("capture_failures", True))
    ):
        data["memory"] = {
            "enabled": config.memory.enabled,
            "max_entries": config.memory.max_entries,
            "max_inject_tokens": config.memory.max_inject_tokens,
            "capture_failures": config.memory.capture_failures,
        }

    if (
        config.recovery.enabled != bool(recd.get("enabled", True))
        or config.recovery.max_phase_retries != _coerce_int(recd.get("max_phase_retries"), 1)
        or config.recovery.max_task_retries != _coerce_int(recd.get("max_task_retries"), 1)
        or config.recovery.allow_nuke != bool(recd.get("allow_nuke", True))
        or config.recovery.max_nuke_attempts != _coerce_int(recd.get("max_nuke_attempts"), 1)
        or config.recovery.incident_char_cap != _coerce_int(recd.get("incident_char_cap"), 4000)
    ):
        data["recovery"] = {
            "enabled": config.recovery.enabled,
            "max_phase_retries": config.recovery.max_phase_retries,
            "max_task_retries": config.recovery.max_task_retries,
            "allow_nuke": config.recovery.allow_nuke,
            "max_nuke_attempts": config.recovery.max_nuke_attempts,
            "incident_char_cap": config.recovery.incident_char_cap,
        }

    if (
        config.daemon.daily_budget_usd != dd.get("daily_budget_usd")
        or config.daemon.github_poll_interval_seconds != _coerce_int(dd.get("github_poll_interval_seconds"), 120)
        or config.daemon.ceo_cooldown_minutes != _coerce_int(dd.get("ceo_cooldown_minutes"), 60)
        or config.daemon.cleanup_interval_hours != _coerce_int(dd.get("cleanup_interval_hours"), 24)
        or config.daemon.max_cleanup_items != _coerce_int(dd.get("max_cleanup_items"), 3)
        or config.daemon.heartbeat_interval_minutes != _coerce_int(dd.get("heartbeat_interval_minutes"), 240)
        or config.daemon.digest_hour_utc != _coerce_int(dd.get("digest_hour_utc"), 14)
        or config.daemon.max_consecutive_failures != _coerce_int(dd.get("max_consecutive_failures"), 3)
        or config.daemon.circuit_breaker_cooldown_minutes != _coerce_int(dd.get("circuit_breaker_cooldown_minutes"), 30)
        or config.daemon.outcome_poll_interval_minutes != _coerce_int(dd.get("outcome_poll_interval_minutes"), 30)
        or config.daemon.issue_labels
        or config.daemon.allowed_control_user_ids
        or config.daemon.allow_all_control_users
        or config.daemon.auto_recover_dirty_worktree != bool(dd.get("auto_recover_dirty_worktree", True))
        or config.daemon.pipeline_timeout_seconds != _coerce_int(dd.get("pipeline_timeout_seconds"), 7200)
        or config.daemon.watchdog_stall_seconds != _coerce_int(dd.get("watchdog_stall_seconds"), 1920)
        or config.daemon.dashboard_enabled != bool(dd.get("dashboard_enabled", True))
        or config.daemon.dashboard_port != _coerce_int(dd.get("dashboard_port"), 8741)
        or config.daemon.dashboard_write_enabled != bool(dd.get("dashboard_write_enabled", False))
        or config.daemon.pr_sync.enabled != bool(pr_def.get("enabled", False))
        or config.daemon.pr_sync.interval_minutes != _coerce_int(pr_def.get("interval_minutes"), 60)
        or config.daemon.pr_sync.max_sync_failures != _coerce_int(pr_def.get("max_sync_failures"), 3)
        or config.daemon.self_update != bool(dd.get("self_update", False))
        or config.daemon.self_update_command != _coerce_str(dd.get("self_update_command"), "uv pip install .")
        or config.daemon.maintenance_budget_usd != _coerce_float(dd.get("maintenance_budget_usd"), 20.0)
        or config.daemon.max_ci_fix_items != _coerce_int(dd.get("max_ci_fix_items"), 2)
        or config.daemon.branch_sync_enabled != bool(dd.get("branch_sync_enabled", True))
    ):
        daemon_data: dict[str, object] = {
            "daily_budget_usd": config.daemon.daily_budget_usd,
            "github_poll_interval_seconds": config.daemon.github_poll_interval_seconds,
            "ceo_cooldown_minutes": config.daemon.ceo_cooldown_minutes,
            "cleanup_interval_hours": config.daemon.cleanup_interval_hours,
            "max_cleanup_items": config.daemon.max_cleanup_items,
            "heartbeat_interval_minutes": config.daemon.heartbeat_interval_minutes,
            "digest_hour_utc": config.daemon.digest_hour_utc,
            "max_consecutive_failures": config.daemon.max_consecutive_failures,
            "circuit_breaker_cooldown_minutes": config.daemon.circuit_breaker_cooldown_minutes,
            "outcome_poll_interval_minutes": config.daemon.outcome_poll_interval_minutes,
            "issue_labels": list(config.daemon.issue_labels),
            "allowed_control_user_ids": list(config.daemon.allowed_control_user_ids),
            "allow_all_control_users": config.daemon.allow_all_control_users,
            "auto_recover_dirty_worktree": config.daemon.auto_recover_dirty_worktree,
            "pipeline_timeout_seconds": config.daemon.pipeline_timeout_seconds,
            "watchdog_stall_seconds": config.daemon.watchdog_stall_seconds,
            "dashboard_enabled": config.daemon.dashboard_enabled,
            "dashboard_port": config.daemon.dashboard_port,
            "dashboard_write_enabled": config.daemon.dashboard_write_enabled,
            "pr_sync": {
                "enabled": config.daemon.pr_sync.enabled,
                "interval_minutes": config.daemon.pr_sync.interval_minutes,
                "max_sync_failures": config.daemon.pr_sync.max_sync_failures,
            },
            "self_update": config.daemon.self_update,
            "self_update_command": config.daemon.self_update_command,
            "maintenance_budget_usd": config.daemon.maintenance_budget_usd,
            "max_ci_fix_items": config.daemon.max_ci_fix_items,
            "branch_sync_enabled": config.daemon.branch_sync_enabled,
        }
        data["daemon"] = daemon_data

    if not config.directions_auto_update:
        data["directions_auto_update"] = False

    if config.ceo_profiles:
        data["ceo_profiles"] = [_persona_to_dict(profile) for profile in config.ceo_profiles]

    if config.max_log_files != 50:
        data["max_log_files"] = config.max_log_files

    config_path = config_dir / CONFIG_FILE
    _ = config_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return config_path


def config_dir_path(repo_root: Path) -> Path:
    return repo_root / CONFIG_DIR


def runs_dir_path(repo_root: Path) -> Path:
    return repo_root / CONFIG_DIR / RUNS_DIR
