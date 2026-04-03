"""Tests for ParallelImplementConfig configuration schema (Task 1.0)."""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from colonyos.config import (
    ColonyConfig,
    ParallelImplementConfig,
    load_config,
    save_config,
    DEFAULTS,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestParallelImplementConfigDefaults:
    """Tests for default values when parallel_implement section is missing."""

    def test_default_enabled(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.parallel_implement.enabled is False

    def test_default_max_parallel_agents(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.parallel_implement.max_parallel_agents == 3

    def test_default_conflict_strategy(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.parallel_implement.conflict_strategy == "auto"

    def test_default_merge_timeout_seconds(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.parallel_implement.merge_timeout_seconds == 60

    def test_default_worktree_cleanup(self, tmp_repo: Path) -> None:
        config = load_config(tmp_repo)
        assert config.parallel_implement.worktree_cleanup is True


class TestParallelImplementConfigParsing:
    """Tests for parsing parallel_implement from YAML."""

    def test_parsed_from_yaml(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "enabled": False,
                    "max_parallel_agents": 5,
                    "conflict_strategy": "fail",
                    "merge_timeout_seconds": 120,
                    "worktree_cleanup": False,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.parallel_implement.enabled is False
        assert config.parallel_implement.max_parallel_agents == 5
        assert config.parallel_implement.conflict_strategy == "fail"
        assert config.parallel_implement.merge_timeout_seconds == 120
        assert config.parallel_implement.worktree_cleanup is False

    def test_partial_yaml_uses_defaults(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "enabled": False,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.parallel_implement.enabled is False
        # Other fields should be defaults
        assert config.parallel_implement.max_parallel_agents == 3
        assert config.parallel_implement.conflict_strategy == "auto"


class TestParallelImplementConfigValidation:
    """Tests for validation of parallel_implement fields."""

    def test_invalid_max_parallel_agents_zero_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "max_parallel_agents": 0,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_parallel_agents must be positive"):
            load_config(tmp_repo)

    def test_invalid_max_parallel_agents_negative_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "max_parallel_agents": -1,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_parallel_agents must be positive"):
            load_config(tmp_repo)

    def test_invalid_conflict_strategy_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "conflict_strategy": "invalid",
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid conflict_strategy"):
            load_config(tmp_repo)

    def test_invalid_merge_timeout_zero_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "merge_timeout_seconds": 0,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="merge_timeout_seconds must be positive"):
            load_config(tmp_repo)

    def test_invalid_merge_timeout_negative_raises(self, tmp_repo: Path) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "merge_timeout_seconds": -10,
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="merge_timeout_seconds must be positive"):
            load_config(tmp_repo)


class TestParallelImplementConfigValidStrategies:
    """Tests that all valid conflict strategies are accepted."""

    @pytest.mark.parametrize("strategy", ["auto", "fail", "manual"])
    def test_valid_conflict_strategies_accepted(
        self, tmp_repo: Path, strategy: str
    ) -> None:
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "parallel_implement": {
                    "conflict_strategy": strategy,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.parallel_implement.conflict_strategy == strategy


class TestParallelImplementConfigRoundtrip:
    """Tests for save/load roundtrip."""

    def test_roundtrip(self, tmp_repo: Path) -> None:
        original = ColonyConfig(
            parallel_implement=ParallelImplementConfig(
                enabled=False,
                max_parallel_agents=8,
                conflict_strategy="fail",
                merge_timeout_seconds=90,
                worktree_cleanup=False,
            ),
        )
        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)
        assert loaded.parallel_implement.enabled is False
        assert loaded.parallel_implement.max_parallel_agents == 8
        assert loaded.parallel_implement.conflict_strategy == "fail"
        assert loaded.parallel_implement.merge_timeout_seconds == 90
        assert loaded.parallel_implement.worktree_cleanup is False

    def test_roundtrip_defaults_not_serialized_when_unchanged(
        self, tmp_repo: Path
    ) -> None:
        """When all values are defaults, section should not appear in YAML."""
        original = ColonyConfig()
        save_config(tmp_repo, original)
        config_path = tmp_repo / ".colonyos" / "config.yaml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        # parallel_implement should not be in the YAML if all defaults
        assert "parallel_implement" not in raw


class TestParallelImplementDefaults:
    """Tests that DEFAULTS dict has parallel_implement section."""

    def test_defaults_has_parallel_implement(self) -> None:
        assert "parallel_implement" in DEFAULTS
        pi = cast(dict[str, Any], DEFAULTS["parallel_implement"])
        assert pi["enabled"] is False
        assert pi["max_parallel_agents"] == 3
        assert pi["conflict_strategy"] == "auto"
        assert pi["merge_timeout_seconds"] == 60
        assert pi["worktree_cleanup"] is True
