from dataclasses import FrozenInstanceError

import pytest

from colonyos.models import Persona, PersonaPack
from colonyos.persona_packs import PACKS, get_pack, pack_keys


class TestPersonaPackDataclass:
    def test_frozen_immutability(self):
        pack = PersonaPack(
            key="test",
            name="Test",
            description="A test pack",
            personas=(
                Persona(role="Eng", expertise="Code", perspective="Ships fast"),
            ),
        )
        with pytest.raises(FrozenInstanceError):
            pack.key = "changed"  # pyright: ignore[reportAttributeAccessIssue]

    def test_field_types(self):
        pack = PersonaPack(
            key="test",
            name="Test Pack",
            description="desc",
            personas=(
                Persona(role="R", expertise="E", perspective="P"),
            ),
        )
        assert isinstance(pack.key, str)
        assert isinstance(pack.name, str)
        assert isinstance(pack.description, str)
        assert isinstance(pack.personas, tuple)
        assert all(isinstance(p, Persona) for p in pack.personas)


class TestPackDefinitions:
    def test_packs_is_non_empty(self):
        assert len(PACKS) >= 4

    def test_all_packs_have_unique_keys(self):
        keys = [p.key for p in PACKS]
        assert len(keys) == len(set(keys))

    def test_all_packs_have_3_to_5_personas(self):
        for pack in PACKS:
            assert 3 <= len(pack.personas) <= 5, (
                f"Pack '{pack.key}' has {len(pack.personas)} personas"
            )

    def test_required_pack_keys_exist(self):
        keys = pack_keys()
        for expected in ("startup", "backend", "fullstack", "opensource"):
            assert expected in keys

    def test_all_personas_have_non_empty_fields(self):
        for pack in PACKS:
            for persona in pack.personas:
                assert persona.role, f"Empty role in pack '{pack.key}'"
                assert persona.expertise, f"Empty expertise in pack '{pack.key}'"
                assert persona.perspective, f"Empty perspective in pack '{pack.key}'"


class TestGetPack:
    def test_returns_correct_pack(self):
        pack = get_pack("startup")
        assert pack is not None
        assert pack.key == "startup"
        assert pack.name == "Startup Team"

    def test_returns_none_for_nonexistent(self):
        assert get_pack("nonexistent") is None


class TestPackKeys:
    def test_matches_packs(self):
        keys = pack_keys()
        assert keys == [p.key for p in PACKS]
