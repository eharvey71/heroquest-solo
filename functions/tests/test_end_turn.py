import pytest

from engine.end_turn import NotHeroPhaseError, resolve_end_turn


def test_hero_phase_transitions_to_zargon():
    result = resolve_end_turn({"phase": "hero"})
    assert result.new_phase == "zargon"
    assert result.log


def test_rejects_non_hero_phase():
    with pytest.raises(NotHeroPhaseError):
        resolve_end_turn({"phase": "zargon"})


def test_rejects_missing_phase():
    with pytest.raises(NotHeroPhaseError):
        resolve_end_turn({})
