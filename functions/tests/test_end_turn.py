import pytest

from engine.end_turn import NotHeroPhaseError, resolve_end_turn


def _heroes(n):
    return [{"id": f"hero{i}", "name": f"Hero {i}", "pos": [0, i], "active": True} for i in range(n)]


def test_hero_phase_transitions_to_zargon():
    result = resolve_end_turn({"phase": "hero"})
    assert result.new_phase == "zargon"
    assert result.new_segment == 1
    assert result.log


def test_multi_hero_party_always_hands_off_to_zargon():
    result = resolve_end_turn({"phase": "hero", "heroes": _heroes(3), "heroPhaseSegment": 1})
    assert result.new_phase == "zargon"
    assert result.new_segment == 1


def test_lone_hero_first_end_turn_stays_in_hero_phase():
    result = resolve_end_turn({"phase": "hero", "heroes": _heroes(1), "heroPhaseSegment": 1})
    assert result.new_phase == "hero"
    assert result.new_segment == 2
    assert result.log  # narrates the second action


def test_lone_hero_second_end_turn_hands_off_and_resets_segment():
    result = resolve_end_turn({"phase": "hero", "heroes": _heroes(1), "heroPhaseSegment": 2})
    assert result.new_phase == "zargon"
    assert result.new_segment == 1


def test_lone_hero_legacy_doc_without_segment_field_acts_as_segment_one():
    result = resolve_end_turn({"phase": "hero", "heroes": _heroes(1)})
    assert result.new_phase == "hero"
    assert result.new_segment == 2


def test_rejects_non_hero_phase():
    with pytest.raises(NotHeroPhaseError):
        resolve_end_turn({"phase": "zargon"})


def test_rejects_missing_phase():
    with pytest.raises(NotHeroPhaseError):
        resolve_end_turn({})
