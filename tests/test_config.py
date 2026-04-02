from pathlib import Path
from typing import cast

import pytest
import yaml

import logging

from colonyos.config import (
    CIFixConfig,
    ColonyConfig,
    BudgetConfig,
    DaemonConfig,
    DEFAULTS,
    LearningsConfig,
    PhasesConfig,
    PRSyncConfig,
    RecoveryConfig,
    RepoMapConfig,
    RetryConfig,
    RouterConfig,
    SlackConfig,
    VerifyConfig,
    VALID_MODELS,
    SAFETY_CRITICAL_PHASES,
    load_config,
    save_config,
)
from colonyos.models import Persona, Phase, ProjectInfo


def _as_str_mapping(obj: object) -> dict[str, object]:
    assert isinstance(obj, dict)
    return cast(dict[str, object], obj)


def _yaml_mapping_from_text(text: str) -> dict[str, object]:
    return _as_str_mapping(cast(object, yaml.safe_load(text)))


def _defaults_at(*keys: str) -> object:
    cur: object = DEFAULTS
    for k in keys:
        m = _as_str_mapping(cur)
        cur = m[k]
    return cur


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestLoadConfig:
    def test_returns_defaults_when_no_config(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.model == "opus"
        assert config.budget.per_phase == 5.0
        assert config.budget.per_run == 15.0
        assert config.phases.plan is True
        assert config.phases.implement is True
        assert config.phases.review is True
        assert config.phases.deliver is True
        assert config.prds_dir == "cOS_prds"
        assert config.tasks_dir == "cOS_tasks"
        assert config.reviews_dir == "cOS_reviews"
        assert config.personas == []
        assert config.project is None
        assert config.recovery.enabled is True
        assert config.recovery.max_phase_retries == 1
        assert config.recovery.allow_nuke is True

    def test_loads_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "project": {
                    "name": "TestApp",
                    "description": "A test",
                    "stack": "Python",
                },
                "personas": [
                    {
                        "role": "Engineer",
                        "expertise": "Backend",
                        "perspective": "Thinks about scale",
                    }
                ],
                "model": "opus",
                "budget": {"per_phase": 10.0, "per_run": 30.0},
                "phases": {"plan": True, "implement": True, "review": False, "deliver": False},
                "branch_prefix": "feat/",
                "prds_dir": "docs/prds",
                "tasks_dir": "docs/tasks",
                "reviews_dir": "docs/reviews",
            }),
            encoding="utf-8",
        )

        config = load_config(tmp_repo)
        assert config.project is not None
        assert config.project.name == "TestApp"
        assert config.project.stack == "Python"
        assert len(config.personas) == 1
        assert config.personas[0].role == "Engineer"
        assert config.model == "opus"
        assert config.budget.per_phase == 10.0
        assert config.phases.review is False
        assert config.phases.deliver is False
        assert config.prds_dir == "docs/prds"
        assert config.reviews_dir == "docs/reviews"

    def test_ignores_personas_without_role(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "personas": [
                    {"role": "", "expertise": "x", "perspective": "y"},
                    {"role": "Valid", "expertise": "x", "perspective": "y"},
                ]
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert len(config.personas) == 1
        assert config.personas[0].role == "Valid"

    def test_existing_config_without_review_fields_gets_defaults(self, tmp_repo: Path):
        """Existing configs missing review/reviews_dir fields get defaults."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phases": {"plan": True, "implement": True, "deliver": True},
                "prds_dir": "prds",
                "tasks_dir": "tasks",
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.phases.review is True
        assert config.reviews_dir == "cOS_reviews"
        # Existing explicit values preserved
        assert config.prds_dir == "prds"
        assert config.tasks_dir == "tasks"


    def test_loads_ceo_persona_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "ceo_persona": {
                    "role": "Growth CEO",
                    "expertise": "Growth hacking",
                    "perspective": "Move the needle",
                },
                "vision": "Become #1 dev tool",
                "proposals_dir": "custom_proposals",
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.ceo_persona is not None
        assert config.ceo_persona.role == "Growth CEO"
        assert config.vision == "Become #1 dev tool"
        assert config.proposals_dir == "custom_proposals"

    def test_defaults_for_new_fields(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.ceo_persona is None
        assert config.vision == ""
        assert config.proposals_dir == "cOS_proposals"


class TestDefaults:
    def test_defaults_have_cos_prefix(self):
        assert DEFAULTS["prds_dir"] == "cOS_prds"
        assert DEFAULTS["tasks_dir"] == "cOS_tasks"
        assert DEFAULTS["reviews_dir"] == "cOS_reviews"

    def test_defaults_have_review_phase(self):
        assert _defaults_at("phases", "review") is True

    def test_defaults_have_proposals_dir(self):
        assert DEFAULTS["proposals_dir"] == "cOS_proposals"


class TestSaveConfig:
    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            project=ProjectInfo(name="MyApp", description="desc", stack="Go"),
            personas=[
                Persona(role="Lead", expertise="Arch", perspective="Big picture", reviewer=True)
            ],
            model="opus",
            budget=BudgetConfig(per_phase=2.0, per_run=6.0),
            phases=PhasesConfig(plan=True, implement=False, review=True, deliver=True),
            branch_prefix="test/",
            prds_dir="p",
            tasks_dir="t",
            reviews_dir="r",
        )

        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)

        assert loaded.project is not None
        assert loaded.project.name == "MyApp"
        assert loaded.personas[0].role == "Lead"
        assert loaded.personas[0].reviewer is True
        assert loaded.model == "opus"
        assert loaded.budget.per_phase == 2.0
        assert loaded.phases.implement is False
        assert loaded.phases.review is True
        assert loaded.prds_dir == "p"
        assert loaded.reviews_dir == "r"

    def test_roundtrip_review_disabled(self, tmp_repo: Path):
        original = ColonyConfig(
            phases=PhasesConfig(review=False),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.phases.review is False

    def test_roundtrip_ceo_fields(self, tmp_repo: Path):
        original = ColonyConfig(
            ceo_persona=Persona(
                role="Growth CEO",
                expertise="Growth",
                perspective="Metrics",
            ),
            vision="Build the best tool",
            proposals_dir="my_proposals",
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.ceo_persona is not None
        assert loaded.ceo_persona.role == "Growth CEO"
        assert loaded.vision == "Build the best tool"
        assert loaded.proposals_dir == "my_proposals"

    def test_roundtrip_without_ceo_persona(self, tmp_repo: Path):
        original = ColonyConfig(vision="Some vision")
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.ceo_persona is None
        assert loaded.vision == "Some vision"

    def test_reviews_dir_persisted(self, tmp_repo: Path):
        original = ColonyConfig(reviews_dir="custom_reviews")
        _ = save_config(tmp_repo, original)

        config_path = tmp_repo / ".colonyos" / "config.yaml"
        raw = _yaml_mapping_from_text(config_path.read_text(encoding="utf-8"))
        assert raw["reviews_dir"] == "custom_reviews"

    def test_recovery_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            recovery=RecoveryConfig(
                enabled=True,
                max_phase_retries=2,
                allow_nuke=True,
                max_nuke_attempts=3,
                incident_char_cap=6000,
            )
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.recovery.max_phase_retries == 2
        assert loaded.recovery.allow_nuke is True
        assert loaded.recovery.max_nuke_attempts == 3
        assert loaded.recovery.incident_char_cap == 6000


class TestReviewerField:
    def test_defaults_to_false(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "personas": [
                    {"role": "Eng", "expertise": "x", "perspective": "y"},
                ]
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.personas[0].reviewer is False

    def test_parsed_when_true(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "personas": [
                    {"role": "Eng", "expertise": "x", "perspective": "y", "reviewer": True},
                ]
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.personas[0].reviewer is True

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            personas=[
                Persona(role="Reviewer", expertise="x", perspective="y", reviewer=True),
                Persona(role="Planner", expertise="x", perspective="y", reviewer=False),
            ],
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.personas[0].reviewer is True
        assert loaded.personas[1].reviewer is False


class TestAutoApprove:
    def test_defaults_to_false(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.auto_approve is False

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"auto_approve": True}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.auto_approve is True

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(auto_approve=True)
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.auto_approve is True

    def test_roundtrip_false(self, tmp_repo: Path):
        original = ColonyConfig(auto_approve=False)
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.auto_approve is False


class TestMaxFixIterations:
    def test_default_value(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.max_fix_iterations == 2

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"max_fix_iterations": 5}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.max_fix_iterations == 5

    def test_zero_disables_fix_loop(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"max_fix_iterations": 0}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.max_fix_iterations == 0

    def test_serialized_via_save_config(self, tmp_repo: Path):
        original = ColonyConfig(max_fix_iterations=3)
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.max_fix_iterations == 3

    def test_defaults_dict_has_max_fix_iterations(self):
        assert DEFAULTS["max_fix_iterations"] == 2


class TestBudgetConfigLongRunning:
    """Task 3.1: Tests for max_duration_hours and max_total_usd in BudgetConfig."""

    def test_defaults_when_fields_missing(self, tmp_repo: Path):
        """Backward compat: configs without new fields get defaults."""
        config = load_config(tmp_repo)
        assert config.budget.max_duration_hours == 8.0
        assert config.budget.max_total_usd == 500.0

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "budget": {
                    "per_phase": 5.0,
                    "per_run": 15.0,
                    "max_duration_hours": 24.0,
                    "max_total_usd": 1000.0,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.budget.max_duration_hours == 24.0
        assert config.budget.max_total_usd == 1000.0

    def test_roundtrip_save_load(self, tmp_repo: Path):
        original = ColonyConfig(
            budget=BudgetConfig(
                per_phase=5.0,
                per_run=15.0,
                max_duration_hours=12.0,
                max_total_usd=250.0,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.budget.max_duration_hours == 12.0
        assert loaded.budget.max_total_usd == 250.0

    def test_backward_compat_old_budget_section(self, tmp_repo: Path):
        """Old configs with only per_phase and per_run still work."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"budget": {"per_phase": 10.0, "per_run": 30.0}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.budget.per_phase == 10.0
        assert config.budget.per_run == 30.0
        assert config.budget.max_duration_hours == 8.0
        assert config.budget.max_total_usd == 500.0

    def test_defaults_dict_has_new_fields(self):
        assert _defaults_at("budget", "max_duration_hours") == 8.0
        assert _defaults_at("budget", "max_total_usd") == 500.0


class TestLearningsConfig:
    def test_default_values(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.learnings.enabled is True
        assert config.learnings.max_entries == 100

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"learnings": {"enabled": False, "max_entries": 50}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.learnings.enabled is False
        assert config.learnings.max_entries == 50

    def test_missing_section_falls_back_to_defaults(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.learnings.enabled is True
        assert config.learnings.max_entries == 100

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(learnings=LearningsConfig(enabled=False, max_entries=42))
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.learnings.enabled is False
        assert loaded.learnings.max_entries == 42

    def test_defaults_dict_has_learnings(self):
        assert _defaults_at("learnings", "enabled") is True
        assert _defaults_at("learnings", "max_entries") == 100


class TestPhaseModels:
    def test_valid_models_contains_expected_values(self):
        assert VALID_MODELS == frozenset({"opus", "sonnet", "haiku"})

    def test_get_model_returns_phase_specific(self):
        config = ColonyConfig(model="sonnet", phase_models={"implement": "opus"})
        assert config.get_model(Phase.IMPLEMENT) == "opus"

    def test_get_model_falls_back_to_global(self):
        config = ColonyConfig(model="sonnet", phase_models={"implement": "opus"})
        assert config.get_model(Phase.PLAN) == "sonnet"

    def test_get_model_falls_back_when_empty(self):
        config = ColonyConfig(model="opus", phase_models={})
        assert config.get_model(Phase.IMPLEMENT) == "opus"
        assert config.get_model(Phase.REVIEW) == "opus"

    def test_load_config_parses_phase_models(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"implement": "opus", "deliver": "haiku"},
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.phase_models == {"implement": "opus", "deliver": "haiku"}

    def test_load_config_defaults_to_empty_dict(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.phase_models == {}

    def test_load_config_rejects_invalid_model_in_phase_models(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"implement": "gpt4"},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid model 'gpt4'"):
            _ = load_config(tmp_repo)

    def test_load_config_rejects_invalid_top_level_model(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "invalid-model"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid model 'invalid-model'"):
            _ = load_config(tmp_repo)

    def test_load_config_rejects_invalid_phase_key(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"nonexistent": "opus"},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid phase key 'nonexistent'"):
            _ = load_config(tmp_repo)

    def test_save_config_serializes_phase_models_when_nonempty(self, tmp_repo: Path):
        config = ColonyConfig(
            model="sonnet",
            phase_models={"implement": "opus", "deliver": "haiku"},
        )
        _ = save_config(tmp_repo, config)
        raw = _yaml_mapping_from_text(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert raw["phase_models"] == {"implement": "opus", "deliver": "haiku"}

    def test_save_config_omits_phase_models_when_empty(self, tmp_repo: Path):
        config = ColonyConfig(model="sonnet", phase_models={})
        _ = save_config(tmp_repo, config)
        raw = _yaml_mapping_from_text(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert "phase_models" not in raw

    def test_roundtrip_preserves_phase_models(self, tmp_repo: Path):
        original = ColonyConfig(
            model="sonnet",
            phase_models={"implement": "opus", "review": "sonnet", "deliver": "haiku"},
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.phase_models == original.phase_models
        assert loaded.model == "sonnet"

    def test_backward_compat_no_config(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.phase_models == {}

    def test_warns_when_haiku_assigned_to_review(
        self, tmp_repo: Path, caplog: pytest.LogCaptureFixture
    ):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"review": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            config = load_config(tmp_repo)
        assert config.phase_models == {"review": "haiku"}
        assert "safety gate" in caplog.text
        assert "'review'" in caplog.text

    def test_warns_when_haiku_assigned_to_decision(
        self, tmp_repo: Path, caplog: pytest.LogCaptureFixture
    ):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"decision": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert "'decision'" in caplog.text

    def test_warns_when_haiku_assigned_to_fix(
        self, tmp_repo: Path, caplog: pytest.LogCaptureFixture
    ):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"fix": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert "'fix'" in caplog.text

    def test_no_warning_when_haiku_assigned_to_learn(
        self, tmp_repo: Path, caplog: pytest.LogCaptureFixture
    ):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"learn": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert "safety gate" not in caplog.text

    def test_no_warning_when_sonnet_assigned_to_review(
        self, tmp_repo: Path, caplog: pytest.LogCaptureFixture
    ):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"review": "sonnet"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert "safety gate" not in caplog.text

    def test_safety_critical_phases_constant(self):
        assert SAFETY_CRITICAL_PHASES == frozenset({"review", "decision", "fix"})

    def test_fix_phase_is_safety_critical_covers_verify_fix(self):
        """Phase.FIX is safety-critical, so the verify-fix agent (which reuses
        Phase.FIX) inherits the haiku-warning guard automatically — no
        separate entry is needed for verify-fix."""
        assert Phase.FIX.value in SAFETY_CRITICAL_PHASES

    def test_verify_phase_not_safety_critical(self):
        """Phase.VERIFY is a read-only test runner intentionally designed to
        use a lightweight model (haiku).  It must NOT be in the safety-critical
        set so that assigning haiku to verify does not trigger a warning."""
        assert Phase.VERIFY.value not in SAFETY_CRITICAL_PHASES

    def test_no_warning_when_haiku_assigned_to_verify(
        self, tmp_repo: Path, caplog: pytest.LogCaptureFixture
    ):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"verify": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert "safety gate" not in caplog.text

    def test_invalid_model_error_mentions_short_names(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "claude-opus-4-20250514"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="short names"):
            _ = load_config(tmp_repo)

    def test_invalid_phase_model_error_mentions_short_names(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"implement": "claude-opus-4-20250514"},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="short names"):
            _ = load_config(tmp_repo)


class TestCIFixConfig:
    def test_default_values(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.ci_fix.enabled is False
        assert config.ci_fix.max_retries == 2
        assert config.ci_fix.wait_timeout == 600
        assert config.ci_fix.log_char_cap == 12_000

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "ci_fix": {
                    "enabled": True,
                    "max_retries": 3,
                    "wait_timeout": 900,
                    "log_char_cap": 8000,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.ci_fix.enabled is True
        assert config.ci_fix.max_retries == 3
        assert config.ci_fix.wait_timeout == 900
        assert config.ci_fix.log_char_cap == 8000

    def test_missing_section_gets_defaults(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.ci_fix.enabled is False
        assert config.ci_fix.max_retries == 2

    def test_negative_retries_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"ci_fix": {"max_retries": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            _ = load_config(tmp_repo)

    def test_negative_timeout_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"ci_fix": {"wait_timeout": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            _ = load_config(tmp_repo)

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            ci_fix=CIFixConfig(enabled=True, max_retries=5, wait_timeout=300),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.ci_fix.enabled is True
        assert loaded.ci_fix.max_retries == 5
        assert loaded.ci_fix.wait_timeout == 300

    def test_defaults_dict_has_ci_fix(self):
        assert _defaults_at("ci_fix", "enabled") is False
        assert _defaults_at("ci_fix", "max_retries") == 2
        assert _defaults_at("ci_fix", "wait_timeout") == 600
        assert _defaults_at("ci_fix", "log_char_cap") == 12_000


class TestSlackConfigTriageFields:
    """Tests for new SlackConfig fields: triage_scope, daily_budget_usd,
    max_queue_depth, triage_verbose, max_consecutive_failures."""

    def test_defaults(self) -> None:
        config = SlackConfig()
        assert config.triage_scope == ""
        assert config.daily_budget_usd is None
        assert config.max_queue_depth == 20
        assert config.triage_verbose is False
        assert config.max_consecutive_failures == 3
        assert config.circuit_breaker_cooldown_minutes == 30

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "slack": {
                    "enabled": True,
                    "channels": ["C12345"],
                    "triage_scope": "Bug reports for Python backend",
                    "daily_budget_usd": 50.0,
                    "max_queue_depth": 10,
                    "triage_verbose": True,
                    "max_consecutive_failures": 5,
                    "circuit_breaker_cooldown_minutes": 60,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.triage_scope == "Bug reports for Python backend"
        assert config.slack.daily_budget_usd == 50.0
        assert config.slack.max_queue_depth == 10
        assert config.slack.triage_verbose is True
        assert config.slack.max_consecutive_failures == 5
        assert config.slack.circuit_breaker_cooldown_minutes == 60

    def test_missing_new_fields_use_defaults(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"enabled": True}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.triage_scope == ""
        assert config.slack.daily_budget_usd is None
        assert config.slack.max_queue_depth == 20
        assert config.slack.triage_verbose is False
        assert config.slack.max_consecutive_failures == 3
        assert config.slack.circuit_breaker_cooldown_minutes == 30

    def test_negative_daily_budget_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"daily_budget_usd": -5.0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="positive"):
            _ = load_config(tmp_repo)

    def test_zero_max_queue_depth_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"max_queue_depth": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="positive"):
            _ = load_config(tmp_repo)

    def test_roundtrip(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                channels=["C123"],
                triage_scope="bugs only",
                daily_budget_usd=25.0,
                max_queue_depth=15,
                triage_verbose=True,
                max_consecutive_failures=5,
                circuit_breaker_cooldown_minutes=45,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.slack.triage_scope == "bugs only"
        assert loaded.slack.daily_budget_usd == 25.0
        assert loaded.slack.max_queue_depth == 15
        assert loaded.slack.triage_verbose is True
        assert loaded.slack.max_consecutive_failures == 5
        assert loaded.slack.circuit_breaker_cooldown_minutes == 45


class TestDaemonConfigBudgetAndControl:
    def test_default_daily_budget_is_500(self) -> None:
        assert _defaults_at("daemon", "daily_budget_usd") == 500.0
        assert _defaults_at("daemon", "auto_recover_dirty_worktree") is True

    def test_parses_unlimited_daemon_budget(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"daily_budget_usd": "unlimited"}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.daily_budget_usd is None

    def test_roundtrip_allow_all_control_users(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=None,
                allow_all_control_users=True,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.daily_budget_usd is None
        assert loaded.daemon.allow_all_control_users is True

    def test_roundtrip_auto_recover_dirty_worktree(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(
                auto_recover_dirty_worktree=True,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.auto_recover_dirty_worktree is True

    def test_roundtrip_retry_ceo_profiles_and_max_log_files(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            retry=RetryConfig(
                max_attempts=5,
                base_delay_seconds=20.0,
                max_delay_seconds=300.0,
                fallback_model="sonnet",
            ),
            ceo_profiles=[
                Persona(
                    role="CEO One",
                    expertise="Strategy",
                    perspective="Move faster",
                    reviewer=True,
                )
            ],
            max_log_files=12,
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.retry.max_attempts == 5
        assert loaded.retry.base_delay_seconds == 20.0
        assert loaded.retry.max_delay_seconds == 300.0
        assert loaded.retry.fallback_model == "sonnet"
        assert len(loaded.ceo_profiles) == 1
        assert loaded.ceo_profiles[0].role == "CEO One"
        assert loaded.ceo_profiles[0].reviewer is True
        assert loaded.max_log_files == 12


class TestSlackMaxFixRoundsPerThread:
    """Tests for SlackConfig.max_fix_rounds_per_thread."""

    def test_default_value(self) -> None:
        config = SlackConfig()
        assert config.max_fix_rounds_per_thread == 3

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "slack": {
                    "enabled": True,
                    "max_fix_rounds_per_thread": 5,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.max_fix_rounds_per_thread == 5

    def test_invalid_zero_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "slack": {
                    "enabled": True,
                    "max_fix_rounds_per_thread": 0,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_fix_rounds_per_thread must be positive"):
            _ = load_config(tmp_repo)

    def test_invalid_negative_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "slack": {
                    "enabled": True,
                    "max_fix_rounds_per_thread": -1,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_fix_rounds_per_thread must be positive"):
            _ = load_config(tmp_repo)

    def test_roundtrip_via_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                channels=["C123"],
                max_fix_rounds_per_thread=7,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.slack.max_fix_rounds_per_thread == 7


class TestSlackMaxRunsPerHourValidation:
    """Tests for SlackConfig.max_runs_per_hour validation."""

    def test_default_value(self) -> None:
        config = SlackConfig()
        assert config.max_runs_per_hour == 3

    def test_zero_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"max_runs_per_hour": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_runs_per_hour must be positive"):
            _ = load_config(tmp_repo)

    def test_negative_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"max_runs_per_hour": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_runs_per_hour must be positive"):
            _ = load_config(tmp_repo)

    def test_valid_value_accepted(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"max_runs_per_hour": 10}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.max_runs_per_hour == 10


class TestSlackAutoApproveWarning:
    """Slack warnings moved to watch command; config parsing should not warn."""

    def test_auto_approve_true_no_config_warning(self, tmp_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"auto_approve": True}}),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert not any("auto_approve" in msg for msg in caplog.messages)

    def test_auto_approve_empty_allowlist_no_config_warning(self, tmp_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"auto_approve": True, "allowed_user_ids": []}}),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            _ = load_config(tmp_repo)
        assert not any("allowed_user_ids" in msg for msg in caplog.messages)


class TestRouterConfig:
    """Tests for RouterConfig dataclass and loading/saving."""

    def test_default_values(self) -> None:
        """RouterConfig has sensible defaults."""
        config = RouterConfig()
        assert config.enabled is True
        assert config.model == "haiku"
        assert config.qa_model == "opus"
        assert config.confidence_threshold == 0.7
        assert config.small_fix_threshold == 0.85
        assert config.qa_budget == 0.50

    def test_defaults_when_no_config(self, tmp_repo: Path) -> None:
        """When no config file exists, router gets defaults."""
        config = load_config(tmp_repo)
        assert config.router.enabled is True
        assert config.router.model == "haiku"
        assert config.router.qa_model == "opus"
        assert config.router.confidence_threshold == 0.7
        assert config.router.small_fix_threshold == 0.85
        assert config.router.qa_budget == 0.50

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        """RouterConfig is correctly parsed from YAML."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "enabled": False,
                    "model": "sonnet",
                    "qa_model": "opus",
                    "confidence_threshold": 0.8,
                    "small_fix_threshold": 0.9,
                    "qa_budget": 1.0,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.router.enabled is False
        assert config.router.model == "sonnet"
        assert config.router.qa_model == "opus"
        assert config.router.confidence_threshold == 0.8
        assert config.router.small_fix_threshold == 0.9
        assert config.router.qa_budget == 1.0

    def test_missing_section_gets_defaults(self, tmp_repo: Path) -> None:
        """Config without router section uses defaults."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.router.enabled is True
        assert config.router.model == "haiku"
        assert config.router.qa_model == "opus"
        assert config.router.confidence_threshold == 0.7
        assert config.router.small_fix_threshold == 0.85
        assert config.router.qa_budget == 0.50

    def test_partial_section_fills_missing_with_defaults(self, tmp_repo: Path) -> None:
        """Partial router section uses defaults for missing fields."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "enabled": False,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.router.enabled is False
        assert config.router.model == "haiku"  # default
        assert config.router.qa_model == "opus"
        assert config.router.confidence_threshold == 0.7  # default
        assert config.router.small_fix_threshold == 0.85
        assert config.router.qa_budget == 0.50  # default

    def test_invalid_model_raises(self, tmp_repo: Path) -> None:
        """Invalid model in router section raises ValueError."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "model": "gpt4",
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid router model 'gpt4'"):
            _ = load_config(tmp_repo)

    def test_negative_confidence_threshold_raises(self, tmp_repo: Path) -> None:
        """Negative confidence_threshold raises ValueError."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "confidence_threshold": -0.1,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="confidence_threshold must be between 0 and 1"):
            _ = load_config(tmp_repo)

    def test_confidence_threshold_above_one_raises(self, tmp_repo: Path) -> None:
        """confidence_threshold > 1 raises ValueError."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "confidence_threshold": 1.5,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="confidence_threshold must be between 0 and 1"):
            _ = load_config(tmp_repo)

    def test_small_fix_threshold_above_one_raises(self, tmp_repo: Path) -> None:
        """small_fix_threshold > 1 raises ValueError."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "small_fix_threshold": 1.1,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="small_fix_threshold must be between 0 and 1"):
            _ = load_config(tmp_repo)

    def test_negative_qa_budget_raises(self, tmp_repo: Path) -> None:
        """Negative qa_budget raises ValueError."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "qa_budget": -0.5,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="qa_budget must be positive"):
            _ = load_config(tmp_repo)

    def test_zero_qa_budget_raises(self, tmp_repo: Path) -> None:
        """Zero qa_budget raises ValueError."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "router": {
                    "qa_budget": 0,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="qa_budget must be positive"):
            _ = load_config(tmp_repo)

    def test_roundtrip(self, tmp_repo: Path) -> None:
        """RouterConfig survives save/load roundtrip."""
        original = ColonyConfig(
            router=RouterConfig(
                enabled=False,
                model="sonnet",
                qa_model="sonnet",
                confidence_threshold=0.85,
                small_fix_threshold=0.9,
                qa_budget=0.75,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.router.enabled is False
        assert loaded.router.model == "sonnet"
        assert loaded.router.qa_model == "sonnet"
        assert loaded.router.confidence_threshold == 0.85
        assert loaded.router.small_fix_threshold == 0.9
        assert loaded.router.qa_budget == 0.75

    def test_roundtrip_with_defaults(self, tmp_repo: Path) -> None:
        """RouterConfig with defaults survives roundtrip (may not be serialized)."""
        original = ColonyConfig(router=RouterConfig())
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.router.enabled is True
        assert loaded.router.model == "haiku"
        assert loaded.router.qa_model == "opus"
        assert loaded.router.confidence_threshold == 0.7
        assert loaded.router.small_fix_threshold == 0.85
        assert loaded.router.qa_budget == 0.50

    def test_defaults_dict_has_router(self) -> None:
        """DEFAULTS dict has router section."""
        assert "router" in DEFAULTS
        assert _defaults_at("router", "enabled") is True
        assert _defaults_at("router", "model") == "haiku"
        assert _defaults_at("router", "qa_model") == "opus"
        assert _defaults_at("router", "confidence_threshold") == 0.7
        assert _defaults_at("router", "small_fix_threshold") == 0.85
        assert _defaults_at("router", "qa_budget") == 0.50

    def test_serialization_omits_defaults(self, tmp_repo: Path) -> None:
        """When RouterConfig has all defaults, it may not be serialized."""
        original = ColonyConfig(router=RouterConfig())
        _ = save_config(tmp_repo, original)
        raw = _yaml_mapping_from_text(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        # With default values, router section should not be serialized
        assert "router" not in raw

    def test_serialization_includes_non_defaults(self, tmp_repo: Path) -> None:
        """When RouterConfig has non-default values, it is serialized."""
        original = ColonyConfig(
            router=RouterConfig(
                enabled=False,
                model="sonnet",
                qa_model="sonnet",
                confidence_threshold=0.9,
                small_fix_threshold=0.95,
                qa_budget=1.0,
            ),
        )
        _ = save_config(tmp_repo, original)
        raw = _yaml_mapping_from_text(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert "router" in raw
        router = _as_str_mapping(raw["router"])
        assert router["enabled"] is False
        assert router["model"] == "sonnet"
        assert router["qa_model"] == "sonnet"
        assert router["confidence_threshold"] == 0.9
        assert router["small_fix_threshold"] == 0.95
        assert router["qa_budget"] == 1.0


class TestRetryConfig:
    def test_default_values(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.retry.max_attempts == 3
        assert config.retry.base_delay_seconds == 10.0
        assert config.retry.max_delay_seconds == 120.0
        assert config.retry.fallback_model is None

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "retry": {
                    "max_attempts": 5,
                    "base_delay_seconds": 20.0,
                    "max_delay_seconds": 300.0,
                    "fallback_model": "sonnet",
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.retry.max_attempts == 5
        assert config.retry.base_delay_seconds == 20.0
        assert config.retry.max_delay_seconds == 300.0
        assert config.retry.fallback_model == "sonnet"

    def test_missing_section_uses_defaults(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.retry.max_attempts == 3
        assert config.retry.base_delay_seconds == 10.0
        assert config.retry.max_delay_seconds == 120.0
        assert config.retry.fallback_model is None

    def test_partial_override(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"max_attempts": 5}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.retry.max_attempts == 5
        assert config.retry.base_delay_seconds == 10.0  # default preserved

    def test_invalid_fallback_model_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"fallback_model": "gpt-4"}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid retry fallback_model"):
            _ = load_config(tmp_repo)

    def test_max_attempts_zero_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"max_attempts": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must be positive"):
            _ = load_config(tmp_repo)

    def test_negative_base_delay_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"base_delay_seconds": -1.0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            _ = load_config(tmp_repo)

    def test_negative_max_delay_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"max_delay_seconds": -5.0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            _ = load_config(tmp_repo)

    def test_fallback_model_none_is_valid(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"fallback_model": None}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.retry.fallback_model is None

    def test_all_valid_models_accepted_as_fallback(self, tmp_repo: Path):
        for model in VALID_MODELS:
            config_dir = tmp_repo / ".colonyos"
            config_dir.mkdir(exist_ok=True)
            _ = (config_dir / "config.yaml").write_text(
                yaml.dump({"retry": {"fallback_model": model}}),
                encoding="utf-8",
            )
            config = load_config(tmp_repo)
            assert config.retry.fallback_model == model

    def test_high_max_attempts_accepted_with_warning(self, tmp_repo: Path):
        """max_attempts > 10 is accepted (not rejected) but logs a warning."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir(exist_ok=True)
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"max_attempts": 20}}),
            encoding="utf-8",
        )
        # Should NOT raise — value is accepted
        config = load_config(tmp_repo)
        assert config.retry.max_attempts == 20

    def test_max_attempts_10_no_warning(self, tmp_repo: Path):
        """max_attempts=10 should not trigger any warning."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir(exist_ok=True)
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"retry": {"max_attempts": 10}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.retry.max_attempts == 10

    def test_defaults_dict_has_retry_section(self):
        assert "retry" in DEFAULTS
        assert _defaults_at("retry", "max_attempts") == 3
        assert _defaults_at("retry", "base_delay_seconds") == 10.0
        assert _defaults_at("retry", "max_delay_seconds") == 120.0
        assert _defaults_at("retry", "fallback_model") is None


class TestRecoveryConfig:
    def test_default_max_task_retries(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.recovery.max_task_retries == 1

    def test_max_task_retries_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"recovery": {"max_task_retries": 2}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.recovery.max_task_retries == 2

    def test_max_task_retries_zero_disables_retry(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"recovery": {"max_task_retries": 0}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.recovery.max_task_retries == 0

    def test_negative_max_task_retries_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"recovery": {"max_task_retries": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            _ = load_config(tmp_repo)

    def test_max_task_retries_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            recovery=RecoveryConfig(
                max_task_retries=3,
            )
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.recovery.max_task_retries == 3

    def test_defaults_dict_has_max_task_retries(self):
        assert _defaults_at("recovery", "max_task_retries") == 1


class TestDaemonOutcomePollInterval:
    """Tests for DaemonConfig.outcome_poll_interval_minutes."""

    def test_default_value_is_30(self) -> None:
        config = DaemonConfig()
        assert config.outcome_poll_interval_minutes == 30

    def test_defaults_dict_has_outcome_poll_interval(self) -> None:
        assert _defaults_at("daemon", "outcome_poll_interval_minutes") == 30

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"outcome_poll_interval_minutes": 15}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.outcome_poll_interval_minutes == 15

    def test_validation_zero_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"outcome_poll_interval_minutes": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="outcome_poll_interval_minutes must be positive"):
            _ = load_config(tmp_repo)

    def test_validation_negative_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"outcome_poll_interval_minutes": -5}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="outcome_poll_interval_minutes must be positive"):
            _ = load_config(tmp_repo)

    def test_roundtrip_via_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(outcome_poll_interval_minutes=45),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.outcome_poll_interval_minutes == 45


class TestPhaseTimeoutConfig:
    """Tests for budget.phase_timeout_seconds config field."""

    def test_default_value(self) -> None:
        assert _defaults_at("budget", "phase_timeout_seconds") == 1800
        assert BudgetConfig().phase_timeout_seconds == 1800

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"budget": {"phase_timeout_seconds": 900}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.budget.phase_timeout_seconds == 900

    def test_validation_too_low_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"budget": {"phase_timeout_seconds": 10}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="phase_timeout_seconds must be >= 30"):
            _ = load_config(tmp_repo)

    def test_roundtrip_via_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(budget=BudgetConfig(phase_timeout_seconds=600))
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.budget.phase_timeout_seconds == 600


class TestPipelineTimeoutConfig:
    """Tests for daemon.pipeline_timeout_seconds config field."""

    def test_default_value(self) -> None:
        assert _defaults_at("daemon", "pipeline_timeout_seconds") == 7200
        assert DaemonConfig().pipeline_timeout_seconds == 7200

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"pipeline_timeout_seconds": 3600}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.pipeline_timeout_seconds == 3600

    def test_validation_too_low_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"pipeline_timeout_seconds": 30}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="pipeline_timeout_seconds must be >= 60"):
            _ = load_config(tmp_repo)

    def test_roundtrip_via_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(pipeline_timeout_seconds=3600),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.pipeline_timeout_seconds == 3600


class TestWatchdogStallSecondsConfig:
    """Tests for daemon.watchdog_stall_seconds config field."""

    def test_default_value(self) -> None:
        assert _defaults_at("daemon", "watchdog_stall_seconds") == 1920
        assert DaemonConfig().watchdog_stall_seconds == 1920

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"watchdog_stall_seconds": 3600}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.watchdog_stall_seconds == 3600

    def test_minimum_floor_clamps_to_120(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"watchdog_stall_seconds": 30}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.watchdog_stall_seconds == 120

    def test_exactly_120_is_accepted(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"watchdog_stall_seconds": 120}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.watchdog_stall_seconds == 120

    def test_roundtrip_via_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(watchdog_stall_seconds=2400),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.watchdog_stall_seconds == 2400


class TestDashboardWriteEnabledConfig:
    """Tests for daemon.dashboard_write_enabled config field."""

    def test_default_is_false(self) -> None:
        assert DaemonConfig().dashboard_write_enabled is False

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"dashboard_write_enabled": True}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.dashboard_write_enabled is True

    def test_roundtrip(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(dashboard_write_enabled=True),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.dashboard_write_enabled is True


class TestRepoMapConfig:
    """Tests for repo_map configuration section."""

    def test_default_values(self) -> None:
        cfg = RepoMapConfig()
        assert cfg.enabled is True
        assert cfg.max_tokens == 4000
        assert cfg.max_files == 2000
        assert cfg.include_patterns == []
        assert cfg.exclude_patterns == []

    def test_defaults_when_no_config(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.repo_map.enabled is True
        assert config.repo_map.max_tokens == 4000
        assert config.repo_map.max_files == 2000
        assert config.repo_map.include_patterns == []
        assert config.repo_map.exclude_patterns == []

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "repo_map": {
                    "enabled": False,
                    "max_tokens": 8000,
                    "max_files": 500,
                    "include_patterns": ["src/**/*.py"],
                    "exclude_patterns": ["tests/**"],
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.repo_map.enabled is False
        assert config.repo_map.max_tokens == 8000
        assert config.repo_map.max_files == 500
        assert config.repo_map.include_patterns == ["src/**/*.py"]
        assert config.repo_map.exclude_patterns == ["tests/**"]

    def test_partial_yaml_uses_defaults(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"repo_map": {"max_tokens": 6000}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.repo_map.enabled is True
        assert config.repo_map.max_tokens == 6000
        assert config.repo_map.max_files == 2000
        assert config.repo_map.include_patterns == []

    def test_validation_max_tokens_positive(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"repo_map": {"max_tokens": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            _ = load_config(tmp_repo)

    def test_validation_max_files_positive(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"repo_map": {"max_files": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_files must be positive"):
            _ = load_config(tmp_repo)

    def test_roundtrip(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            repo_map=RepoMapConfig(
                enabled=False,
                max_tokens=8000,
                max_files=500,
                include_patterns=["src/**/*.py"],
                exclude_patterns=["tests/**"],
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.repo_map.enabled is False
        assert loaded.repo_map.max_tokens == 8000
        assert loaded.repo_map.max_files == 500
        assert loaded.repo_map.include_patterns == ["src/**/*.py"]
        assert loaded.repo_map.exclude_patterns == ["tests/**"]

    def test_save_omits_when_defaults(self, tmp_repo: Path) -> None:
        """save_config should not serialize repo_map when all values are defaults."""
        original = ColonyConfig()
        _ = save_config(tmp_repo, original)
        raw = _yaml_mapping_from_text(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert "repo_map" not in raw


class TestPRSyncConfig:
    """Tests for PRSyncConfig parsing, defaults, validation, and serialization."""

    def test_default_values(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.daemon.pr_sync.enabled is False
        assert config.daemon.pr_sync.interval_minutes == 60
        assert config.daemon.pr_sync.max_sync_failures == 3

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "daemon": {
                    "pr_sync": {
                        "enabled": True,
                        "interval_minutes": 30,
                        "max_sync_failures": 5,
                    },
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.pr_sync.enabled is True
        assert config.daemon.pr_sync.interval_minutes == 30
        assert config.daemon.pr_sync.max_sync_failures == 5

    def test_missing_section_gets_defaults(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"daily_budget_usd": 100.0}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.pr_sync.enabled is False
        assert config.daemon.pr_sync.interval_minutes == 60
        assert config.daemon.pr_sync.max_sync_failures == 3

    def test_interval_minutes_below_one_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"pr_sync": {"interval_minutes": 0}}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="pr_sync.interval_minutes must be >= 1"):
            _ = load_config(tmp_repo)

    def test_max_sync_failures_below_one_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"pr_sync": {"max_sync_failures": 0}}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="pr_sync.max_sync_failures must be >= 1"):
            _ = load_config(tmp_repo)

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            daemon=DaemonConfig(
                pr_sync=PRSyncConfig(
                    enabled=True, interval_minutes=45, max_sync_failures=7
                ),
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.pr_sync.enabled is True
        assert loaded.daemon.pr_sync.interval_minutes == 45
        assert loaded.daemon.pr_sync.max_sync_failures == 7

    def test_non_default_values_included_in_save(self, tmp_repo: Path):
        original = ColonyConfig(
            daemon=DaemonConfig(
                pr_sync=PRSyncConfig(enabled=True, interval_minutes=30),
            ),
        )
        _ = save_config(tmp_repo, original)
        config_path = tmp_repo / ".colonyos" / "config.yaml"
        saved_data = _yaml_mapping_from_text(config_path.read_text(encoding="utf-8"))
        assert "daemon" in saved_data
        daemon = _as_str_mapping(saved_data["daemon"])
        assert "pr_sync" in daemon
        pr_sync = _as_str_mapping(daemon["pr_sync"])
        assert pr_sync["enabled"] is True
        assert pr_sync["interval_minutes"] == 30

    def test_defaults_dict_has_pr_sync(self):
        assert "pr_sync" in _as_str_mapping(DEFAULTS["daemon"])
        assert _defaults_at("daemon", "pr_sync", "enabled") is False
        assert _defaults_at("daemon", "pr_sync", "interval_minutes") == 60
        assert _defaults_at("daemon", "pr_sync", "max_sync_failures") == 3


class TestSlackDailyThreadConfig:
    """Tests for SlackConfig daily thread fields: notification_mode,
    daily_thread_hour, daily_thread_timezone."""

    def test_defaults(self) -> None:
        config = SlackConfig()
        assert config.notification_mode == "daily"
        assert config.daily_thread_hour == 8
        assert config.daily_thread_timezone == "UTC"

    def test_per_item_mode(self) -> None:
        config = SlackConfig(notification_mode="per_item")
        assert config.notification_mode == "per_item"

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "slack": {
                    "enabled": True,
                    "channels": ["C12345"],
                    "notification_mode": "per_item",
                    "daily_thread_hour": 9,
                    "daily_thread_timezone": "America/New_York",
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.notification_mode == "per_item"
        assert config.slack.daily_thread_hour == 9
        assert config.slack.daily_thread_timezone == "America/New_York"

    def test_daily_mode_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "slack": {
                    "enabled": True,
                    "channels": ["C12345"],
                    "notification_mode": "daily",
                    "daily_thread_hour": 0,
                    "daily_thread_timezone": "Europe/London",
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.notification_mode == "daily"
        assert config.slack.daily_thread_hour == 0
        assert config.slack.daily_thread_timezone == "Europe/London"

    def test_invalid_notification_mode_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"notification_mode": "weekly"}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid slack notification_mode"):
            _ = load_config(tmp_repo)

    def test_daily_thread_hour_negative_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"daily_thread_hour": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="daily_thread_hour must be 0-23"):
            _ = load_config(tmp_repo)

    def test_daily_thread_hour_24_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"daily_thread_hour": 24}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="daily_thread_hour must be 0-23"):
            _ = load_config(tmp_repo)

    def test_invalid_timezone_falls_back_to_utc(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"daily_thread_timezone": "Not/A/Timezone"}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.daily_thread_timezone == "UTC"

    def test_roundtrip_via_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                channels=["C123"],
                notification_mode="per_item",
                daily_thread_hour=14,
                daily_thread_timezone="Asia/Tokyo",
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.slack.notification_mode == "per_item"
        assert loaded.slack.daily_thread_hour == 14
        assert loaded.slack.daily_thread_timezone == "Asia/Tokyo"

    def test_defaults_when_omitted_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"slack": {"enabled": True, "channels": ["C123"]}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.slack.notification_mode == "daily"
        assert config.slack.daily_thread_hour == 8
        assert config.slack.daily_thread_timezone == "UTC"


class TestVerifyConfig:
    """Tests for VerifyConfig dataclass and its integration into PhasesConfig/DEFAULTS."""

    def test_verify_config_defaults(self) -> None:
        vc = VerifyConfig()
        assert vc.max_fix_attempts == 2

    def test_verify_config_custom_value(self) -> None:
        vc = VerifyConfig(max_fix_attempts=5)
        assert vc.max_fix_attempts == 5

    def test_phases_config_verify_defaults_true(self) -> None:
        pc = PhasesConfig()
        assert pc.verify is True

    def test_phases_config_verify_can_be_disabled(self) -> None:
        pc = PhasesConfig(verify=False)
        assert pc.verify is False

    def test_defaults_phases_verify_is_true(self) -> None:
        assert _defaults_at("phases", "verify") is True

    def test_defaults_verify_section_exists(self) -> None:
        assert "verify" in DEFAULTS
        assert _defaults_at("verify", "max_fix_attempts") == 2

    def test_colony_config_has_verify(self) -> None:
        cc = ColonyConfig()
        assert isinstance(cc.verify, VerifyConfig)
        assert cc.verify.max_fix_attempts == 2

    def test_load_config_defaults_verify(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.phases.verify is True
        assert config.verify.max_fix_attempts == 2

    def test_load_config_verify_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "phases": {"verify": False},
                "verify": {"max_fix_attempts": 4},
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.phases.verify is False
        assert config.verify.max_fix_attempts == 4

    def test_load_config_verify_invalid_max_fix_attempts(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"verify": {"max_fix_attempts": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="verify.max_fix_attempts must be positive"):
            _ = load_config(tmp_repo)

    def test_roundtrip_verify_config(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            phases=PhasesConfig(verify=False),
            verify=VerifyConfig(max_fix_attempts=5),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.phases.verify is False
        assert loaded.verify.max_fix_attempts == 5


class TestDaemonMaintenanceConfig:
    """Tests for daemon maintenance configuration fields (task 1.1)."""

    def test_default_self_update_is_false(self) -> None:
        cfg = DaemonConfig()
        assert cfg.self_update is False

    def test_default_self_update_command(self) -> None:
        cfg = DaemonConfig()
        assert cfg.self_update_command == "uv pip install ."

    def test_default_maintenance_budget_usd(self) -> None:
        cfg = DaemonConfig()
        assert cfg.maintenance_budget_usd == 20.0

    def test_default_max_ci_fix_items(self) -> None:
        cfg = DaemonConfig()
        assert cfg.max_ci_fix_items == 2

    def test_default_branch_sync_enabled(self) -> None:
        cfg = DaemonConfig()
        assert cfg.branch_sync_enabled is True

    def test_defaults_in_defaults_dict(self) -> None:
        d = _as_str_mapping(DEFAULTS["daemon"])
        assert d["self_update"] is False
        assert d["self_update_command"] == "uv pip install ."
        assert d["maintenance_budget_usd"] == 20.0
        assert d["max_ci_fix_items"] == 2
        assert d["branch_sync_enabled"] is True

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({
                "daemon": {
                    "self_update": True,
                    "self_update_command": "pip install -e .",
                    "maintenance_budget_usd": 50.0,
                    "max_ci_fix_items": 5,
                    "branch_sync_enabled": False,
                }
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.self_update is True
        assert config.daemon.self_update_command == "pip install -e ."
        assert config.daemon.maintenance_budget_usd == 50.0
        assert config.daemon.max_ci_fix_items == 5
        assert config.daemon.branch_sync_enabled is False

    def test_defaults_when_omitted_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"daily_budget_usd": 100.0}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.daemon.self_update is False
        assert config.daemon.self_update_command == "uv pip install ."
        assert config.daemon.maintenance_budget_usd == 20.0
        assert config.daemon.max_ci_fix_items == 2
        assert config.daemon.branch_sync_enabled is True

    def test_maintenance_budget_must_be_positive(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"maintenance_budget_usd": -5.0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="maintenance_budget_usd"):
            _ = load_config(tmp_repo)

    def test_maintenance_budget_zero_rejected(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"maintenance_budget_usd": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="maintenance_budget_usd"):
            _ = load_config(tmp_repo)

    def test_max_ci_fix_items_must_be_positive(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        _ = (config_dir / "config.yaml").write_text(
            yaml.dump({"daemon": {"max_ci_fix_items": 0}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_ci_fix_items"):
            _ = load_config(tmp_repo)

    def test_roundtrip_save_load(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            daemon=DaemonConfig(
                self_update=True,
                self_update_command="pip install .",
                maintenance_budget_usd=30.0,
                max_ci_fix_items=4,
                branch_sync_enabled=False,
            ),
        )
        _ = save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.daemon.self_update is True
        assert loaded.daemon.self_update_command == "pip install ."
        assert loaded.daemon.maintenance_budget_usd == 30.0
        assert loaded.daemon.max_ci_fix_items == 4
        assert loaded.daemon.branch_sync_enabled is False
