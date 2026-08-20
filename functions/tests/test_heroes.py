"""Hero death: reported by the player, applied by the app.

Body Points never enter the app (CLAUDE.md's physical/digital
boundary), so these tests are about the CONSEQUENCES of a death, not
about detecting one.
"""

import pytest

from engine.heroes import (
    HeroAlreadyDeadError,
    HeroNotFoundError,
    is_alive,
    living_heroes,
    record_hero_death,
)


def _state(*heroes):
    return {"heroes": [dict(h) for h in heroes], "monsters": {}}


BARB = {"id": "barbarian", "name": "Barbarian", "pos": [5, 5], "alive": True}
DWARF = {"id": "dwarf", "name": "Dwarf", "pos": [6, 5], "alive": True}


def test_a_hero_with_no_alive_field_is_alive():
    # Games created before hero death existed carry no flag at all.
    assert is_alive({"id": "elf", "pos": [1, 1]}) is True


def test_death_marks_the_hero_and_frees_the_board():
    state = _state(BARB, DWARF)
    result = record_hero_death(state, "barbarian")

    assert result.party_wiped is False
    assert [h["id"] for h in living_heroes(state)] == ["dwarf"]
    assert "Take the figure off the board" in result.log[0]


def test_the_roster_keeps_the_dead_hero():
    # The party's SIZE at creation is what the quest budget was priced
    # against, and the lone-hero rule keys off it -- so the entry stays.
    state = _state(BARB, DWARF)
    record_hero_death(state, "barbarian")
    assert len(state["heroes"]) == 2


def test_last_hero_down_loses_the_quest():
    state = _state(BARB, DWARF)
    record_hero_death(state, "barbarian")
    result = record_hero_death(state, "dwarf")

    assert result.party_wiped is True
    assert any("quest is lost" in line for line in result.log)
    assert living_heroes(state) == []


def test_reporting_the_same_death_twice_is_rejected():
    state = _state(BARB)
    record_hero_death(state, "barbarian")
    with pytest.raises(HeroAlreadyDeadError):
        record_hero_death(state, "barbarian")


def test_unknown_hero_rejected():
    with pytest.raises(HeroNotFoundError):
        record_hero_death(_state(BARB), "elf")
