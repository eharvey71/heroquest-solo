"""The twelve base-game hero spell cards.

Card text is transcribed verbatim in data/hero_spells.json; these test
the resolution -- which half of each card the app applies, and which
half it hands back to the table.
"""

import random

import pytest

from engine.hero_spells import (
    HERO_SPELLS,
    HeroSpellUnavailableError,
    UnknownHeroSpellError,
    resolve_hero_spell,
    spellbook_for,
    validate_spellbooks,
)

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}

SPELLBOOKS = {"wizard": ["Fire", "Water", "Earth"], "elf": ["Air"]}


def _quest(**overrides):
    quest = {"doors": [D1], "blockedSquares": [], "rooms": {}, "corridorTraps": []}
    quest.update(overrides)
    return quest


def _state(monsters=None, cast=(), spellbooks=None):
    return {
        "heroes": [
            {"id": "wizard", "name": "Wizard", "pos": [6, 2], "alive": True},
            {"id": "elf", "name": "Elf", "pos": [6, 3], "alive": True},
        ],
        "monsters": monsters
        if monsters is not None
        else {"M1": {"type": "orc", "pos": [8, 2], "currentBody": 3, "alive": True}},
        "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
        "doors": {"D1": "open"},
        "collapsedSquares": [],
        "spellsCast": list(cast),
        "spellbooks": spellbooks if spellbooks is not None else SPELLBOOKS,
        "heroStatus": {},
        "monsterStatus": {},
    }


def _cast(catalogs, spell_id, *, caster="wizard", state=None, quest=None, rng=None, **kw):
    state = state or _state()
    hero = next(h for h in state["heroes"] if h["id"] == caster)
    return resolve_hero_spell(
        board=catalogs.board, catalogs=catalogs, quest=quest or _quest(), game_state=state,
        heroes=state["heroes"], caster_id=caster, caster_name=hero["name"],
        caster_pos=tuple(hero["pos"]), spell_id=spell_id, rng=rng or random.Random(1), **kw
    )


def test_every_card_carries_its_own_text():
    assert len(HERO_SPELLS) == 12
    for spell in HERO_SPELLS.values():
        assert spell["text"].strip() and spell["name"].strip() and spell["element"]


def test_a_hero_only_holds_the_elements_they_took():
    state = _state()
    assert spellbook_for(state, "elf") == ["genie", "swift_wind", "tempest"]
    assert "ball_of_flame" in spellbook_for(state, "wizard")
    assert "tempest" not in spellbook_for(state, "wizard")


def test_casting_a_card_you_do_not_hold_is_refused(catalogs):
    with pytest.raises(HeroSpellUnavailableError):
        _cast(catalogs, "tempest", caster="wizard")  # the Elf took Air


def test_a_spent_card_cannot_be_cast_again(catalogs):
    with pytest.raises(HeroSpellUnavailableError):
        _cast(catalogs, "ball_of_flame", state=_state(cast=["ball_of_flame"]))


def test_unknown_card_rejected(catalogs):
    with pytest.raises(UnknownHeroSpellError):
        _cast(catalogs, "meteor_swarm")


# ---- the app's half ----

def test_ball_of_flame_applies_damage_less_the_monsters_own_save(catalogs):
    result = _cast(catalogs, "ball_of_flame", target_monster_id="M1", rng=random.Random(4))
    damage = result.monster_damage["M1"]
    assert 0 <= damage <= 2  # 2 Body Points, less each 5 or 6 on two red dice
    assert any("Body Point" in line for line in result.log)


def test_fire_of_wrath_is_all_or_nothing(catalogs):
    damages = {
        _cast(catalogs, "fire_of_wrath", target_monster_id="M1", rng=random.Random(seed)).monster_damage["M1"]
        for seed in range(25)
    }
    assert damages == {0, 1}  # one point unless it rolls a 5 or 6


def test_sleep_holds_a_monster(catalogs):
    result = _cast(catalogs, "sleep", target_monster_id="M1")
    assert result.monster_statuses == [{"monsterId": "M1", "status": "asleep", "missesTurns": 0}]
    assert any("cannot move, attack, or even defend" in line for line in result.log)


def test_sleep_does_not_work_on_the_undead(catalogs):
    for undead in ("mummy", "zombie", "skeleton"):
        state = _state(monsters={"M1": {"type": undead, "pos": [8, 2], "currentBody": 3, "alive": True}})
        with pytest.raises(HeroSpellUnavailableError):
            _cast(catalogs, "sleep", state=state, target_monster_id="M1")


def test_tempest_costs_a_monster_its_next_turn(catalogs):
    result = _cast(catalogs, "tempest", caster="elf", target_monster_id="M1")
    assert result.monster_statuses[0]["status"] == "becalmed"
    assert result.monster_statuses[0]["missesTurns"] == 1


def test_the_genie_opens_any_door_on_the_board(catalogs):
    # "open any door on the board" -- no line of sight needed.
    result = _cast(catalogs, "genie", caster="elf", genie_mode="door", door_id="D1")
    assert result.opened_door_id == "D1"


def test_the_genie_attacks_with_its_own_five_dice(catalogs):
    result = _cast(catalogs, "genie", caster="elf", genie_mode="attack", target_monster_id="M1",
                   rng=random.Random(2))
    assert "M1" in result.monster_damage
    assert any("combat dice" in line for line in result.log)


def test_a_monster_out_of_sight_cannot_be_targeted(catalogs):
    quest = _quest(doors=[{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}])
    state = _state(monsters={"M1": {"type": "orc", "pos": [2, 2], "currentBody": 3, "alive": True}})
    state["doors"] = {"D1": "closed"}
    with pytest.raises(HeroSpellUnavailableError):
        _cast(catalogs, "ball_of_flame", state=state, quest=quest, target_monster_id="M1")


# ---- the table's half ----

def test_healing_is_announced_never_applied(catalogs):
    for spell_id in ("heal_body", "water_of_healing"):
        result = _cast(catalogs, spell_id, target_hero_id="elf")
        assert result.monster_damage == {} and result.hero_statuses == []
        assert any("Body Points" in line for line in result.log)


def test_swift_wind_just_names_the_roll(catalogs):
    result = _cast(catalogs, "swift_wind", caster="elf", target_hero_id="wizard")
    assert result.hero_statuses == []
    assert any("4 red dice" in line for line in result.log)


def test_rock_skin_and_courage_leave_a_reminder(catalogs):
    for spell_id, status in (("rock_skin", "rock_skin"), ("courage", "courageous")):
        result = _cast(catalogs, spell_id, target_hero_id="wizard")
        assert result.hero_statuses[0]["status"] == status
        assert result.hero_statuses[0]["playerCleared"] is True


def test_the_two_movement_spells_are_spent_by_the_next_move(catalogs):
    for spell_id, status in (("veil_of_mist", "veiled"), ("pass_through_rock", "through_rock")):
        result = _cast(catalogs, spell_id, target_hero_id="wizard")
        assert result.hero_statuses[0]["status"] == status
        assert result.hero_statuses[0]["consumedByMove"] is True


# ---- spellbooks, chosen at setup ----

def test_the_wizard_takes_three_elements_and_the_elf_one():
    validate_spellbooks({"wizard": ["Fire", "Water", "Earth"], "elf": ["Air"]})


@pytest.mark.parametrize(
    "books",
    [
        {"wizard": ["Fire", "Water"], "elf": ["Air"]},  # too few for the Wizard
        {"wizard": ["Fire", "Water", "Earth"], "elf": ["Air", "Water"]},  # too many for the Elf
        {"wizard": ["Fire", "Fire", "Earth"], "elf": ["Air"]},  # same element twice
        {"wizard": ["Fire", "Water", "Earth"], "elf": ["Fire"]},  # one physical set, two hands
        {"wizard": ["Fire", "Water", "Shadow"], "elf": ["Air"]},  # no such element
        {"barbarian": ["Fire"]},  # not a caster
    ],
)
def test_bad_spellbooks_rejected(books):
    with pytest.raises(HeroSpellUnavailableError):
        validate_spellbooks(books)
