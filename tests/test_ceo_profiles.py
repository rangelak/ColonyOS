"""Tests for CEO profile selection and parsing."""

from __future__ import annotations

import pytest

from colonyos.ceo_profiles import (
    CEO_PROFILES,
    get_ceo_profile,
    parse_custom_ceo_profiles,
)
from colonyos.models import Persona


class TestGetCeoProfile:
    """Tests for get_ceo_profile()."""

    def test_returns_persona(self) -> None:
        """Default call returns a Persona from the built-in profiles."""
        profile = get_ceo_profile()
        assert isinstance(profile, Persona)
        assert profile in CEO_PROFILES

    def test_name_match(self) -> None:
        """Passing a name prefix returns the matching profile."""
        profile = get_ceo_profile(name="First-Principles")
        assert profile.role == "First-Principles Engineering CEO"

    def test_name_match_case_insensitive(self) -> None:
        """Name matching is case-insensitive."""
        profile = get_ceo_profile(name="safety-conscious")
        assert "Safety" in profile.role

    def test_name_no_match_raises(self) -> None:
        """Non-matching name raises ValueError."""
        with pytest.raises(ValueError, match="No CEO profile matching"):
            get_ceo_profile(name="nonexistent-ceo-xyz")

    def test_exclude_avoids_role(self) -> None:
        """Exclude parameter avoids the specified role."""
        excluded_role = CEO_PROFILES[0].role
        # Run many times to ensure the excluded role is never returned
        for _ in range(50):
            profile = get_ceo_profile(exclude=excluded_role)
            assert profile.role != excluded_role

    def test_exclude_all_falls_back(self) -> None:
        """When exclude matches all candidates, fall back to full list."""
        # Create a single-profile custom list
        single = [Persona(role="Only One", expertise="x", perspective="y")]
        # Excluding the only profile should still return it
        profile = get_ceo_profile(exclude="Only One", custom_profiles=single)
        assert profile.role == "Only One"

    def test_custom_profiles(self) -> None:
        """Custom profiles replace defaults when provided."""
        custom = [
            Persona(role="Custom CEO", expertise="custom", perspective="custom"),
        ]
        profile = get_ceo_profile(custom_profiles=custom)
        assert profile.role == "Custom CEO"

    def test_builtin_profiles_count(self) -> None:
        """There should be exactly 8 built-in CEO profiles."""
        assert len(CEO_PROFILES) == 8

    def test_all_profiles_have_fields(self) -> None:
        """All built-in profiles should have non-empty role, expertise, perspective."""
        for p in CEO_PROFILES:
            assert p.role
            assert p.expertise
            assert p.perspective


class TestParseCustomCeoProfiles:
    """Tests for parse_custom_ceo_profiles()."""

    def test_parses_valid_entry(self) -> None:
        """Valid dict entries produce Persona objects."""
        raw: list[dict[str, object]] = [
            {"role": "Test CEO", "expertise": "testing", "perspective": "test everything"}
        ]
        result = parse_custom_ceo_profiles(raw)
        assert len(result) == 1
        assert result[0].role == "Test CEO"

    def test_skips_empty_role(self) -> None:
        """Entries with empty role are skipped."""
        raw: list[dict[str, object]] = [{"role": "", "expertise": "x", "perspective": "y"}]
        result = parse_custom_ceo_profiles(raw)
        assert len(result) == 0

    def test_sanitizes_values(self) -> None:
        """ANSI escape sequences are stripped from profile values."""
        raw: list[dict[str, object]] = [
            {"role": "\x1b[31mEvil CEO\x1b[0m", "expertise": "x", "perspective": "y"}
        ]
        result = parse_custom_ceo_profiles(raw)
        assert "\x1b" not in result[0].role
        assert "Evil CEO" in result[0].role

    def test_empty_list(self) -> None:
        """Empty input produces empty output."""
        assert parse_custom_ceo_profiles([]) == []

    def test_missing_keys_use_defaults(self) -> None:
        """Missing expertise/perspective default to empty strings."""
        raw: list[dict[str, object]] = [{"role": "Minimal CEO"}]
        result = parse_custom_ceo_profiles(raw)
        assert len(result) == 1
        assert result[0].expertise == ""
        assert result[0].perspective == ""
