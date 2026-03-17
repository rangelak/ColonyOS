from unittest.mock import patch, call

import pytest
import click

from colonyos.models import Persona
from colonyos.init import select_persona_pack, _collect_personas_with_packs
from colonyos.persona_packs import PACKS


class TestSelectPersonaPack:
    def test_returns_pack_personas_when_pack_selected(self):
        # User picks pack 1 (startup), then confirms
        inputs = iter(["1", "y"])
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.return_value = 1
            mock_click.confirm.return_value = True
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            result = select_persona_pack()

        assert result is not None
        assert len(result) == len(PACKS[0].personas)
        assert result[0].role == PACKS[0].personas[0].role

    def test_returns_none_when_custom_selected(self):
        custom_index = len(PACKS) + 1
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.return_value = custom_index
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            result = select_persona_pack()

        assert result is None

    def test_returns_none_when_pack_not_confirmed(self):
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.return_value = 1
            mock_click.confirm.return_value = False
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            result = select_persona_pack()

        assert result is None

    def test_all_packs_selectable(self):
        for i, pack in enumerate(PACKS, 1):
            with patch("colonyos.init.click") as mock_click:
                mock_click.prompt.return_value = i
                mock_click.confirm.return_value = True
                mock_click.echo = click.echo
                mock_click.IntRange = click.IntRange
                result = select_persona_pack()

            assert result is not None
            assert len(result) == len(pack.personas)


class TestCollectPersonasWithPacks:
    def test_pack_selected_no_custom_additions(self):
        with patch("colonyos.init.select_persona_pack") as mock_select, \
             patch("colonyos.init.click") as mock_click:
            mock_select.return_value = list(PACKS[0].personas)
            mock_click.confirm.return_value = False  # No custom additions
            result = _collect_personas_with_packs()

        assert result == list(PACKS[0].personas)

    def test_pack_selected_with_custom_additions(self):
        extra_persona = Persona(
            role="Custom Role",
            expertise="Custom Expertise",
            perspective="Custom Perspective",
        )
        pack_personas = list(PACKS[0].personas)

        with patch("colonyos.init.select_persona_pack") as mock_select, \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.collect_personas") as mock_collect:
            mock_select.return_value = pack_personas
            mock_click.confirm.return_value = True  # Yes, add custom
            mock_collect.return_value = pack_personas + [extra_persona]
            result = _collect_personas_with_packs()

        mock_collect.assert_called_once_with(existing=pack_personas)
        assert len(result) == len(pack_personas) + 1

    def test_custom_selected_falls_through_to_collect(self):
        existing = [Persona(role="Existing", expertise="E", perspective="P")]

        with patch("colonyos.init.select_persona_pack") as mock_select, \
             patch("colonyos.init.collect_personas") as mock_collect:
            mock_select.return_value = None  # Custom selected
            mock_collect.return_value = existing
            result = _collect_personas_with_packs(existing)

        mock_collect.assert_called_once_with(existing)
        assert result == existing
