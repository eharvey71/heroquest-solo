"""Zargon's twelve Chaos spell cards.

Card text is transcribed verbatim in data/chaos_spells.json; these test
the resolution -- what the app applies, what it hands back to the table,
and the conditions the cards themselves impose.
"""

import random

import pytest

from engine.chaos_spells import (
    CHAOS_SPELLS,
    ChaosSpellUnavailableError,
    UnknownChaosSpellError,
    choose_spell,
    resolve_chaos_spell,
    visible_heroes,
)

# R2 is x:5-8, y:1-3. R1 is x:1-4, y:1-3, joined by D1 at (4,1)/(5,1).
D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}


def _quest(**overrides):
    quest = {"doors": [D1], "blockedSquares": [], "rooms": {}, "corridorTraps": []}
    quest.update(overrides)
    return quest


def _state(heroes=None, monsters=None, cast=()):
    return {
        "heroes": heroes or [{"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True}],
        "monsters": monsters or {"M1": {"type": "chaos_warrior", "pos": [8, 2], "currentBody": 3, "alive": True}},
        "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
        "doors": {"D1": "open"},
        "collapsedSquares": [],
        "chaosSpellsCast": list(cast),
        "heroStatus": {},
    }


def _cast(catalogs, spell_id, state=None, quest=None, caster_pos=(8, 2), rng=None):
    state = state or _state()
    return resolve_chaos_spell(
        board=catalogs.board, catalogs=catalogs, quest=quest or _quest(), game_state=state,
        heroes=[h for h in state["heroes"] if h.get("alive", True)],
        caster_id="M1", caster_name="Verag", caster_pos=caster_pos,
        spell_id=spell_id, rng=rng or random.Random(1),
    )


def test_every_card_carries_its_own_text():
    assert len(CHAOS_SPELLS) == 12
    for spell in CHAOS_SPELLS.values():
        assert spell["text"].strip()
        assert spell["name"].strip()


def test_ball_of_flame_names_the_damage_and_the_heros_own_dice(catalogs):
    result = _cast(catalogs, "ball_of_flame")
    assert len(result.hero_hits) == 1
    hit = result.hero_hits[0]
    assert (hit.hero_id, hit.damage, hit.reduction_dice) == ("barbarian", 2, 2)
    # Body Points are physical: nothing is applied, only announced.
    assert result.monster_damage == {}
    assert any("2 Body Points" in line and "red dice" in line for line in result.log)


def test_a_spell_already_cast_cannot_be_cast_again(catalogs):
    with pytest.raises(ChaosSpellUnavailableError):
        _cast(catalogs, "ball_of_flame", state=_state(cast=["ball_of_flame"]))


def test_unknown_card_rejected(catalogs):
    with pytest.raises(UnknownChaosSpellError):
        _cast(catalogs, "meteor_swarm")


def test_lightning_bolt_picks_the_line_that_catches_most_heroes(catalogs):
    heroes = [
        {"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "alive": True},
        {"id": "dwarf", "name": "Dwarf", "pos": [6, 2], "alive": True},
        {"id": "elf", "name": "Elf", "pos": [8, 3], "alive": True},
    ]
    result = _cast(catalogs, "lightning_bolt", state=_state(heroes=heroes))
    # West catches two; south catches one.
    assert {h.hero_id for h in result.hero_hits} == {"barbarian", "dwarf"}
    assert all(h.damage == 2 for h in result.hero_hits)


def test_lightning_bolt_hits_zargons_own_monsters_too(catalogs):
    heroes = [{"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True}]
    monsters = {
        "M1": {"type": "chaos_warrior", "pos": [8, 2], "currentBody": 3, "alive": True},
        "M2": {"type": "orc", "pos": [7, 2], "currentBody": 1, "alive": True},
    }
    result = _cast(catalogs, "lightning_bolt", state=_state(heroes=heroes, monsters=monsters))
    assert result.monster_damage == {"M2": 2}


def test_firestorm_burns_the_room_but_never_the_caster(catalogs):
    heroes = [{"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True}]
    monsters = {
        "M1": {"type": "chaos_warrior", "pos": [8, 2], "currentBody": 3, "alive": True},
        "M2": {"type": "orc", "pos": [7, 3], "currentBody": 1, "alive": True},
    }
    result = _cast(catalogs, "firestorm", state=_state(heroes=heroes, monsters=monsters))
    assert [h.hero_id for h in result.hero_hits] == ["barbarian"]
    assert "M1" not in result.monster_damage  # "The spellcaster is unaffected"
    assert "M2" in result.log[-1] or any("M2" in line for line in result.log)


def test_firestorm_is_not_used_in_corridors(catalogs):
    # (0,0) is corridor; put the caster there with a hero beside it.
    heroes = [{"id": "barbarian", "name": "Barbarian", "pos": [1, 0], "alive": True}]
    state = _state(heroes=heroes, monsters={"M1": {"type": "chaos_warrior", "pos": [0, 0], "currentBody": 3, "alive": True}})
    state["revealed"]["corridorSquares"] = [[0, 0], [1, 0]]
    with pytest.raises(ChaosSpellUnavailableError):
        _cast(catalogs, "firestorm", state=state, caster_pos=(0, 0))


def test_sleep_holds_one_hero(catalogs):
    result = _cast(catalogs, "sleep")
    assert result.statuses == [
        {"heroId": "barbarian", "heroName": "Barbarian", "status": "asleep", "missesTurns": 0}
    ]


def test_cloud_of_chaos_takes_everyone_in_the_room(catalogs):
    heroes = [
        {"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True},
        {"id": "elf", "name": "Elf", "pos": [7, 3], "alive": True},
        {"id": "wizard", "name": "Wizard", "pos": [2, 2], "alive": True},  # next room, spared
    ]
    result = _cast(catalogs, "cloud_of_chaos", state=_state(heroes=heroes))
    assert {s["heroId"] for s in result.statuses} == {"barbarian", "elf"}
    assert all(s["status"] == "paralyzed" for s in result.statuses)


def test_tempest_costs_one_turn(catalogs):
    result = _cast(catalogs, "tempest")
    assert result.statuses[0]["status"] == "becalmed"
    assert result.statuses[0]["missesTurns"] == 1


def test_rust_is_narrated_and_nothing_else(catalogs):
    result = _cast(catalogs, "rust")
    assert result.hero_hits == [] and result.statuses == [] and result.summons == []
    assert any("ruined" in line for line in result.log)


def test_summon_orcs_places_minis_around_the_caster(catalogs):
    result = _cast(catalogs, "summon_orcs", rng=random.Random(2))
    assert result.summons
    assert all(s["type"] == "orc" for s in result.summons)
    assert any("Place" in i for i in result.placement_instructions)


def test_summon_undead_respects_the_owned_minis(catalogs):
    # Four skeletons already on the board: the box has exactly four.
    monsters = {
        "M1": {"type": "chaos_warrior", "pos": [8, 2], "currentBody": 3, "alive": True},
        **{f"S{i}": {"type": "skeleton", "pos": [5 + i, 1], "currentBody": 1, "alive": True} for i in range(4)},
    }
    result = _cast(catalogs, "summon_undead", state=_state(monsters=monsters), rng=random.Random(3))
    summoned_skeletons = sum(1 for s in result.summons if s["type"] == "skeleton")
    assert summoned_skeletons == 0
    assert any("proxy" in line for line in result.log)


def test_escape_needs_a_destination(catalogs):
    with pytest.raises(ChaosSpellUnavailableError):
        _cast(catalogs, "escape")

    result = _cast(catalogs, "escape", quest=_quest(escapeDestination=[2, 2]))
    assert result.caster_new_pos == (2, 2)


def test_a_caster_only_targets_a_hero_it_can_see(catalogs):
    # Hero in R1 with the door CLOSED: no sightline, so no spell.
    heroes = [{"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "alive": True}]
    state = _state(heroes=heroes)
    state["doors"] = {"D1": "closed"}
    quest = _quest(doors=[{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}])
    assert visible_heroes(catalogs.board, quest, state, heroes, (8, 2)) == []
    assert choose_spell(
        board=catalogs.board, quest=quest, game_state=state, heroes=heroes,
        caster_pos=(8, 2), available=["sleep"],
    ) is None


def test_the_big_cards_wait_for_a_crowd(catalogs):
    one_hero = _state()
    assert choose_spell(
        board=catalogs.board, quest=_quest(), game_state=one_hero, heroes=one_hero["heroes"],
        caster_pos=(8, 2), available=["firestorm", "sleep"],
    ) == "sleep"

    crowd = _state(heroes=[
        {"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True},
        {"id": "elf", "name": "Elf", "pos": [7, 3], "alive": True},
    ])
    assert choose_spell(
        board=catalogs.board, quest=_quest(), game_state=crowd, heroes=crowd["heroes"],
        caster_pos=(8, 2), available=["firestorm", "sleep"],
    ) == "firestorm"


def test_a_spent_card_drops_out_of_the_choice(catalogs):
    state = _state(cast=["sleep"])
    assert choose_spell(
        board=catalogs.board, quest=_quest(), game_state=state, heroes=state["heroes"],
        caster_pos=(8, 2), available=["sleep"],
    ) is None
