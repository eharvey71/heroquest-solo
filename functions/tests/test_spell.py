"""Hero spellcasting: Elf/Wizard only, needs sight, once per quest.

R1 (x:1-4,y:1-3) <-D1(4,1)/(5,1)-> R2 (x:5-8,y:1-3).
"""

import random

import pytest

from engine.spell import InvalidSpellError, resolve_hero_spell

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}


def _quest(doors=None):
    return {"doors": doors if doors is not None else [D1], "blockedSquares": [], "rooms": {}}


def _state(hero_id="wizard", hero_pos=(2, 2), monster_pos=(4, 2), spells_cast=(), doors=None):
    return {
        "heroes": [{"id": hero_id, "name": hero_id.title(), "pos": list(hero_pos), "active": True}],
        "monsters": {"M1": {"type": "orc", "pos": list(monster_pos), "currentBody": 1, "alive": True}},
        "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
        "doors": doors or {},
        "spellsCast": list(spells_cast),
    }


def _cast(catalogs, **kw):
    base = dict(
        board=catalogs.board, catalogs=catalogs, quest=_quest(), game_state=_state(),
        hero_id="wizard", spell_name="Ball of Flame", target_monster_id="M1",
        skulls=2, rng=random.Random(1),
    )
    base.update(kw)
    return resolve_hero_spell(**base)


def test_wizard_can_damage_a_monster_in_sight(catalogs):
    result = _cast(catalogs)
    assert result.defense is not None
    assert result.target_monster_id == "M1"


def test_elf_can_cast_too(catalogs):
    result = _cast(catalogs, game_state=_state(hero_id="elf"), hero_id="elf")
    assert result.defense is not None


def test_barbarian_has_no_spells(catalogs):
    with pytest.raises(InvalidSpellError):
        _cast(catalogs, game_state=_state(hero_id="barbarian"), hero_id="barbarian")


def test_a_spell_may_only_be_cast_once_per_quest(catalogs):
    with pytest.raises(InvalidSpellError):
        _cast(catalogs, game_state=_state(spells_cast=("Ball of Flame",)))


def test_the_once_per_quest_check_ignores_case(catalogs):
    with pytest.raises(InvalidSpellError):
        _cast(catalogs, game_state=_state(spells_cast=("ball of flame",)))


def test_a_target_out_of_sight_cannot_be_hit(catalogs):
    # Monster in R2, closed door between -- no line of sight.
    with pytest.raises(InvalidSpellError):
        _cast(catalogs, game_state=_state(monster_pos=(6, 2)))


def test_an_open_door_restores_the_sightline(catalogs):
    result = _cast(catalogs, game_state=_state(monster_pos=(6, 1), hero_pos=(3, 1), doors={"D1": "open"}))
    assert result.defense is not None


def test_a_spell_with_no_defence_roll_lands_in_full(catalogs):
    result = _cast(catalogs, monster_defends=False, skulls=1)
    assert result.defense.blocks == 0
    assert result.defense.damage == 1


def test_a_spell_on_a_hero_changes_no_digital_state(catalogs):
    # Healing and buffs touch hero body points, which are physical.
    result = _cast(catalogs, spell_name="Heal Body", target_monster_id=None)
    assert result.defense is None
    assert result.target_monster_id is None
    assert result.log


def test_rejects_an_empty_spell_name(catalogs):
    with pytest.raises(InvalidSpellError):
        _cast(catalogs, spell_name="   ")


def test_rejects_a_dead_target(catalogs):
    state = _state()
    state["monsters"]["M1"]["alive"] = False
    with pytest.raises(InvalidSpellError):
        _cast(catalogs, game_state=state)
