from pathlib import Path

import pytest
import yaml

import logging

from colonyos.config import (
    CIFixConfig,
    ColonyConfig,
    BudgetConfig,
    DEFAULTS,
    LearningsConfig,
    PhasesConfig,
    PostHogConfig,
    VALID_MODELS,
    _SAFETY_CRITICAL_PHASES,
    load_config,
    save_config,
)
from colonyos.models import Persona, Phase, ProjectInfo


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestLoadConfig:
    def test_returns_defaults_when_no_config(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.model == "sonnet"
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

    def test_loads_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
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
        (config_dir / "config.yaml").write_text(
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
        (config_dir / "config.yaml").write_text(
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
        (config_dir / "config.yaml").write_text(
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
        assert DEFAULTS["phases"]["review"] is True

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

        save_config(tmp_repo, original)
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
        save_config(tmp_repo, original)
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
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.ceo_persona is not None
        assert loaded.ceo_persona.role == "Growth CEO"
        assert loaded.vision == "Build the best tool"
        assert loaded.proposals_dir == "my_proposals"

    def test_roundtrip_without_ceo_persona(self, tmp_repo: Path):
        original = ColonyConfig(vision="Some vision")
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.ceo_persona is None
        assert loaded.vision == "Some vision"

    def test_reviews_dir_persisted(self, tmp_repo: Path):
        original = ColonyConfig(reviews_dir="custom_reviews")
        save_config(tmp_repo, original)

        config_path = tmp_repo / ".colonyos" / "config.yaml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert raw["reviews_dir"] == "custom_reviews"


class TestReviewerField:
    def test_defaults_to_false(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
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
        (config_dir / "config.yaml").write_text(
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
        save_config(tmp_repo, original)
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
        (config_dir / "config.yaml").write_text(
            yaml.dump({"auto_approve": True}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.auto_approve is True

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(auto_approve=True)
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.auto_approve is True

    def test_roundtrip_false(self, tmp_repo: Path):
        original = ColonyConfig(auto_approve=False)
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.auto_approve is False


class TestMaxFixIterations:
    def test_default_value(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.max_fix_iterations == 2

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"max_fix_iterations": 5}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.max_fix_iterations == 5

    def test_zero_disables_fix_loop(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"max_fix_iterations": 0}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.max_fix_iterations == 0

    def test_serialized_via_save_config(self, tmp_repo: Path):
        original = ColonyConfig(max_fix_iterations=3)
        save_config(tmp_repo, original)
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
        (config_dir / "config.yaml").write_text(
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
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.budget.max_duration_hours == 12.0
        assert loaded.budget.max_total_usd == 250.0

    def test_backward_compat_old_budget_section(self, tmp_repo: Path):
        """Old configs with only per_phase and per_run still work."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"budget": {"per_phase": 10.0, "per_run": 30.0}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.budget.per_phase == 10.0
        assert config.budget.per_run == 30.0
        assert config.budget.max_duration_hours == 8.0
        assert config.budget.max_total_usd == 500.0

    def test_defaults_dict_has_new_fields(self):
        assert DEFAULTS["budget"]["max_duration_hours"] == 8.0
        assert DEFAULTS["budget"]["max_total_usd"] == 500.0


class TestLearningsConfig:
    def test_default_values(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.learnings.enabled is True
        assert config.learnings.max_entries == 100

    def test_parsed_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"learnings": {"enabled": False, "max_entries": 50}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.learnings.enabled is False
        assert config.learnings.max_entries == 50

    def test_missing_section_falls_back_to_defaults(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.learnings.enabled is True
        assert config.learnings.max_entries == 100

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(learnings=LearningsConfig(enabled=False, max_entries=42))
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.learnings.enabled is False
        assert loaded.learnings.max_entries == 42

    def test_defaults_dict_has_learnings(self):
        assert DEFAULTS["learnings"]["enabled"] is True
        assert DEFAULTS["learnings"]["max_entries"] == 100


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
        (config_dir / "config.yaml").write_text(
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
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.phase_models == {}

    def test_load_config_rejects_invalid_model_in_phase_models(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"implement": "gpt4"},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid model 'gpt4'"):
            load_config(tmp_repo)

    def test_load_config_rejects_invalid_top_level_model(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "invalid-model"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid model 'invalid-model'"):
            load_config(tmp_repo)

    def test_load_config_rejects_invalid_phase_key(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"nonexistent": "opus"},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid phase key 'nonexistent'"):
            load_config(tmp_repo)

    def test_save_config_serializes_phase_models_when_nonempty(self, tmp_repo: Path):
        config = ColonyConfig(
            model="sonnet",
            phase_models={"implement": "opus", "deliver": "haiku"},
        )
        save_config(tmp_repo, config)
        raw = yaml.safe_load(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert raw["phase_models"] == {"implement": "opus", "deliver": "haiku"}

    def test_save_config_omits_phase_models_when_empty(self, tmp_repo: Path):
        config = ColonyConfig(model="sonnet", phase_models={})
        save_config(tmp_repo, config)
        raw = yaml.safe_load(
            (tmp_repo / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert "phase_models" not in raw

    def test_roundtrip_preserves_phase_models(self, tmp_repo: Path):
        original = ColonyConfig(
            model="sonnet",
            phase_models={"implement": "opus", "review": "sonnet", "deliver": "haiku"},
        )
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.phase_models == original.phase_models
        assert loaded.model == "sonnet"

    def test_backward_compat_no_config(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.phase_models == {}

    def test_warns_when_haiku_assigned_to_review(self, tmp_repo: Path, caplog):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
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

    def test_warns_when_haiku_assigned_to_decision(self, tmp_repo: Path, caplog):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"decision": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            load_config(tmp_repo)
        assert "'decision'" in caplog.text

    def test_warns_when_haiku_assigned_to_fix(self, tmp_repo: Path, caplog):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"fix": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            load_config(tmp_repo)
        assert "'fix'" in caplog.text

    def test_no_warning_when_haiku_assigned_to_learn(self, tmp_repo: Path, caplog):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"learn": "haiku"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            load_config(tmp_repo)
        assert "safety gate" not in caplog.text

    def test_no_warning_when_sonnet_assigned_to_review(self, tmp_repo: Path, caplog):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"review": "sonnet"},
            }),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="colonyos.config"):
            load_config(tmp_repo)
        assert "safety gate" not in caplog.text

    def test_safety_critical_phases_constant(self):
        assert _SAFETY_CRITICAL_PHASES == frozenset({"review", "decision", "fix"})

    def test_invalid_model_error_mentions_short_names(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "claude-opus-4-20250514"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="short names"):
            load_config(tmp_repo)

    def test_invalid_phase_model_error_mentions_short_names(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "model": "sonnet",
                "phase_models": {"implement": "claude-opus-4-20250514"},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="short names"):
            load_config(tmp_repo)


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
        (config_dir / "config.yaml").write_text(
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
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.ci_fix.enabled is False
        assert config.ci_fix.max_retries == 2

    def test_negative_retries_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"ci_fix": {"max_retries": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            load_config(tmp_repo)

    def test_negative_timeout_raises(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"ci_fix": {"wait_timeout": -1}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-negative"):
            load_config(tmp_repo)

    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            ci_fix=CIFixConfig(enabled=True, max_retries=5, wait_timeout=300),
        )
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.ci_fix.enabled is True
        assert loaded.ci_fix.max_retries == 5
        assert loaded.ci_fix.wait_timeout == 300

    def test_defaults_dict_has_ci_fix(self):
        assert DEFAULTS["ci_fix"]["enabled"] is False
        assert DEFAULTS["ci_fix"]["max_retries"] == 2
        assert DEFAULTS["ci_fix"]["wait_timeout"] == 600
        assert DEFAULTS["ci_fix"]["log_char_cap"] == 12_000


class TestPostHogConfig:
    def test_defaults_when_no_section(self, tmp_repo: Path):
        """PostHogConfig defaults to disabled when no posthog section in YAML."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet"}), encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.posthog.enabled is False

    def test_parsed_from_yaml(self, tmp_repo: Path):
        """PostHogConfig is parsed correctly from YAML."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet", "posthog": {"enabled": True}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.posthog.enabled is True

    def test_serialization_roundtrip(self, tmp_repo: Path):
        """PostHogConfig survives save → load round-trip."""
        original = ColonyConfig(posthog=PostHogConfig(enabled=True))
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.posthog.enabled is True

    def test_serialized_when_disabled(self, tmp_repo: Path):
        """PostHog section is omitted from YAML when disabled (matches ci_fix/slack pattern)."""
        original = ColonyConfig(posthog=PostHogConfig(enabled=False))
        save_config(tmp_repo, original)
        config_path = tmp_repo / ".colonyos" / "config.yaml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert "posthog" not in raw

    def test_serialized_when_enabled(self, tmp_repo: Path):
        """PostHog section is present in YAML when enabled."""
        original = ColonyConfig(posthog=PostHogConfig(enabled=True))
        save_config(tmp_repo, original)
        config_path = tmp_repo / ".colonyos" / "config.yaml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert "posthog" in raw
        assert raw["posthog"]["enabled"] is True

    def test_defaults_dict_has_posthog(self):
        assert DEFAULTS["posthog"]["enabled"] is False

    def test_backwards_compat_no_posthog_field(self, tmp_repo: Path):
        """Configs created before posthog was added still load."""
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"model": "sonnet", "budget": {"per_phase": 5.0, "per_run": 15.0}}),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.posthog.enabled is False


