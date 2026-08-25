"""Jump / disarm / step tests for a trap the party has already found."""

import pytest

from engine.trap_action import InvalidTrapActionError, resolve_trap_action


def _state(hero_id="barbarian", hero_pos=(5, 2), found=("R2-T1",), sprung=()):
    return {
        "heroes": [{"id": hero_id, "name": hero_id.title(), "pos": list(hero_pos), "active": True}],
        "monsters": {},
        "trapsFound": list(found),
        "trapsTriggered": list(sprung),
    }


def _call(catalogs, **kw):
    base = dict(
        board=catalogs.board, quest={}, game_state=_state(), hero_id="barbarian",
        trap_id="R2-T1", trap_type="pit", trap_pos=(6, 2), action="jump",
    )
    base.update(kw)
    return resolve_trap_action(**base)


def test_jump_cleared_lands_beyond_the_trap(catalogs):
    result = _call(catalogs, die_face="white_shield", landing=(7, 2))
    assert result.sprung is False
    assert result.hero_pos == (7, 2)
    assert result.placement_instruction is None  # nothing goes on the board


def test_jump_on_a_skull_springs_the_trap(catalogs):
    result = _call(catalogs, die_face="skull", landing=(7, 2))
    assert result.sprung is True
    assert result.hero_pos == (6, 2)  # a pit swallows the jumper
    assert "pit trap tile" in result.placement_instruction


def test_jump_rejects_an_occupied_landing_square(catalogs):
    state = _state()
    state["monsters"] = {"M1": {"pos": [7, 2], "currentBody": 1, "alive": True}}
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, game_state=state, die_face="white_shield", landing=(7, 2))


def test_jump_rejects_landing_back_where_the_hero_started(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, die_face="white_shield", landing=(5, 2))


def test_dwarf_disarms_on_anything_but_a_black_shield(catalogs):
    result = _call(
        catalogs, game_state=_state(hero_id="dwarf"), hero_id="dwarf",
        action="disarm", die_face="skull",
    )
    assert result.disarmed is True
    assert result.sprung is False


def test_dwarf_springs_the_trap_on_a_black_shield(catalogs):
    result = _call(
        catalogs, game_state=_state(hero_id="dwarf"), hero_id="dwarf",
        action="disarm", die_face="black_shield",
    )
    assert result.sprung is True
    assert result.disarmed is False


def test_other_heroes_need_a_tool_kit(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, action="disarm", die_face="white_shield")


def test_tool_kit_hero_disarms_on_either_shield(catalogs):
    result = _call(catalogs, action="disarm", die_face="black_shield", has_tool_kit=True)
    assert result.disarmed is True


def test_tool_kit_hero_springs_the_trap_on_a_skull(catalogs):
    result = _call(catalogs, action="disarm", die_face="skull", has_tool_kit=True)
    assert result.sprung is True


def test_stepping_on_deliberately_springs_it(catalogs):
    result = _call(catalogs, action="step")
    assert result.sprung is True
    assert result.hero_pos == (6, 2)


def test_falling_block_never_lets_the_hero_onto_the_square(catalogs):
    result = _call(catalogs, action="step", trap_type="falling_block")
    assert result.sprung is True
    assert result.hero_pos == (5, 2)  # stays put; the square is now rubble


def test_rejects_a_trap_the_party_hasnt_found(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, game_state=_state(found=()), action="step")


def test_rejects_an_already_sprung_trap(catalogs):
    # A sprung SPEAR is gone forever. (A sprung PIT is the deliberate
    # exception -- see the open-pit tests at the bottom of this file.)
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, game_state=_state(sprung=("R2-T1",)), trap_type="spear", action="step", die_face="skull")


def test_rejects_a_hero_who_isnt_next_to_the_trap(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, game_state=_state(hero_pos=(1, 1)), action="step")


def test_rejects_an_unknown_die_face(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, die_face="shield", landing=(7, 2))


def test_spear_trap_on_a_skull_wounds_and_ends_the_turn(catalogs):
    result = _call(catalogs, action="step", trap_type="spear", die_face="skull")
    assert result.sprung is True
    assert result.hero_pos == (6, 2)
    assert result.placement_instruction is None  # "There are no spear trap tiles"


def test_spear_trap_dodged_is_gone_forever(catalogs):
    result = _call(catalogs, action="step", trap_type="spear", die_face="white_shield")
    assert result.sprung is False
    assert result.disarmed is True
    assert result.hero_pos == (6, 2)


def test_spear_trap_needs_the_heros_die(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, action="step", trap_type="spear")


# ---- open (already-sprung) pits: the one trap that stays interactive
# (1989 rulebook p.19-20 -- crossing the hole means jumping or
# climbing in; it can never be disarmed) ----


def _sprung_pit(**kw):
    base = dict(game_state=_state(sprung=("R2-T1",)))
    base.update(kw)
    return base


def test_open_pit_can_be_jumped_clear(catalogs):
    result = _call(catalogs, **_sprung_pit(die_face="white_shield", landing=(7, 2)))
    assert result.hero_pos == (7, 2)
    assert result.placement_instruction is None  # the tile is already down


def test_open_pit_jump_on_a_skull_drops_the_hero_in(catalogs):
    result = _call(catalogs, **_sprung_pit(die_face="skull", landing=(7, 2)))
    assert result.hero_pos == (6, 2)
    assert "fall in" in result.log[0]


def test_open_pit_jump_needs_the_die(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, **_sprung_pit(landing=(7, 2)))


def test_open_pit_can_be_climbed_into(catalogs):
    result = _call(catalogs, **_sprung_pit(action="step"))
    assert result.hero_pos == (6, 2)
    assert "1 Body Point" in result.log[0]


def test_open_pit_can_never_be_disarmed(catalogs):
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, **_sprung_pit(action="disarm", die_face="white_shield"))


def test_a_sprung_falling_block_stays_inert(catalogs):
    # Only PITS stay interactive -- "once a falling block trap has been
    # sprung ... it cannot be disarmed or jumped".
    with pytest.raises(InvalidTrapActionError):
        _call(catalogs, **_sprung_pit(trap_type="falling_block", die_face="white_shield", landing=(7, 2)))
