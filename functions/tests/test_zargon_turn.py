"""Zargon-turn orchestration tests against real board.json geometry.

R1 (x:1-4,y:1-3) <-D1(4,1)/(5,1)-> R2 (x:5-8,y:1-3) <-D2(8,1)/(9,1)-> R3
(unrevealed in most tests, used only for the wandering-frontier case).
"""

import pytest

from engine.zargon_turn import resolve_zargon_turn

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}
D2 = {"id": "D2", "squares": [[8, 1], [9, 1]], "state": "closed"}


def _quest(monsters=None, objective=None, wandering=None, doors=None):
    rooms = {}
    if monsters:
        rooms["R2"] = {"monsters": monsters, "traps": [], "furniture": []}
    return {
        "doors": doors if doors is not None else [D1],
        "objective": objective or {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
        "wanderingMonster": wandering,
        "rooms": rooms,
    }


def _game_state(heroes=None, monsters=None, doors=None):
    return {
        "heroes": heroes or [{"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "active": True}],
        "monsters": monsters or {},
        "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
        "doors": doors or {"D1": "open"},
    }


def test_normal_turn_chases_and_attacks_nearest_hero(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "name": "Grukk", "pos": [8, 3]}])
    game_state = _game_state(monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}})

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="normal")

    assert len(result.monster_results) == 1
    mr = result.monster_results[0]
    assert mr.action == "moved_and_attacked"
    assert "M1" in result.updated_monster_positions


def test_normal_turn_no_target_when_unreachable(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "pos": [8, 3]}])
    game_state = _game_state(monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}}, doors={"D1": "locked"})

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="normal")

    assert result.monster_results[0].action == "no_target"


def test_cunning_turn_focus_fires_the_given_lowest_bp_hero(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(
        monsters=[{"id": "M1", "type": "orc", "pos": [8, 3]}],
        objective={"type": "kill_boss", "description": "x", "target": {"room": "R99"}},  # not R2 -- not a guard
    )
    heroes = [
        {"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "active": True},
        {"id": "wizard", "name": "Wizard", "pos": [2, 1], "active": True},
    ]
    game_state = _game_state(heroes=heroes, monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}})

    result = resolve_zargon_turn(
        board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="cunning", lowest_bp_hero_id="wizard"
    )

    assert result.monster_results[0].turn_result.attack.hero_name == "Wizard"


def test_cunning_turn_guard_holds_when_not_engaged(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "name": "Grukk", "pos": [8, 3]}])  # objective room is R2
    game_state = _game_state(monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}})  # hero far in R1

    result = resolve_zargon_turn(
        board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="cunning", lowest_bp_hero_id="barbarian"
    )

    assert result.monster_results[0].action == "guards"
    assert result.updated_monster_positions == {}


def test_cunning_turn_guard_engages_actual_intruder_not_global_target(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "name": "Grukk", "pos": [8, 3]}])
    heroes = [
        {"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "active": True},  # far away, the "focus fire" pick
        {"id": "wizard", "name": "Wizard", "pos": [6, 2], "active": True},  # actually in the guard's room
    ]
    game_state = _game_state(heroes=heroes, monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}})

    result = resolve_zargon_turn(
        board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="cunning", lowest_bp_hero_id="barbarian"
    )

    # engages Wizard (actually present), not Barbarian (the global focus-fire pick)
    assert result.monster_results[0].action == "moved_and_attacked"
    assert result.monster_results[0].turn_result.attack.hero_name == "Wizard"


def test_cunning_turn_requires_answer_with_multiple_heroes(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "pos": [8, 3]}])
    heroes = [
        {"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "active": True},
        {"id": "wizard", "name": "Wizard", "pos": [2, 1], "active": True},
    ]
    game_state = _game_state(heroes=heroes, monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}})

    with pytest.raises(ValueError):
        resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="cunning")


def test_wandering_spawns_and_no_monster_acts(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(wandering="goblin", doors=[D1, D2])
    game_state = _game_state(heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}])

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="wandering")

    assert result.spawned_monster["type"] == "goblin"
    assert result.spawned_monster["pos"] == (8, 1)
    assert result.monster_results == []
    assert result.updated_monster_positions == {}


def test_wandering_no_monster_type_returns_no_spawn(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(wandering=None)
    game_state = _game_state()

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="wandering")

    assert result.spawned_monster is None


def test_monster_not_in_revealed_territory_does_not_act(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "pos": [8, 3]}])
    game_state = _game_state(monsters={"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}})
    game_state["revealed"] = {"rooms": ["R1"], "corridorSquares": []}  # R2 (where M1 stands) not revealed

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="normal")

    assert result.monster_results == []


def test_dead_monster_does_not_act(catalogs):
    board, c = catalogs.board, catalogs
    quest = _quest(monsters=[{"id": "M1", "type": "orc", "pos": [8, 3]}])
    game_state = _game_state(monsters={"M1": {"pos": [8, 3], "currentBody": 0, "alive": False}})

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="normal")

    assert result.monster_results == []


def test_invalid_turn_type_raises(catalogs):
    board, c = catalogs.board, catalogs
    with pytest.raises(ValueError):
        resolve_zargon_turn(board=board, catalogs=c, quest=_quest(), game_state=_game_state(), turn_type="chaotic")


def test_monster_occupancy_respected_within_one_turn(catalogs):
    # M1 sits at the ONLY square connecting R1<->R2 ((5,1), the D1
    # doorway) after moving there with exactly 1 move point. M2,
    # processed second, wants the same chokepoint and must be blocked
    # by M1's NEW position, not its stale starting square.
    board, c = catalogs.board, catalogs
    quest = _quest(
        monsters=[
            {"id": "M1", "type": "orc", "pos": [6, 1], "overrides": {"move": 1, "attack": 3, "defend": 2, "body": 1, "mind": 2}},
            {"id": "M2", "type": "orc", "pos": [7, 1], "overrides": {"move": 10, "attack": 3, "defend": 2, "body": 1, "mind": 2}},
        ]
    )
    game_state = _game_state(
        monsters={
            "M1": {"pos": [6, 1], "currentBody": 1, "alive": True},
            "M2": {"pos": [7, 1], "currentBody": 1, "alive": True},
        }
    )

    result = resolve_zargon_turn(board=board, catalogs=c, quest=quest, game_state=game_state, turn_type="normal")

    assert result.updated_monster_positions["M1"] == (5, 1)  # took the doorway, its only reachable step
    m2_result = next(r for r in result.monster_results if r.monster_id == "M2")
    # M1 now occupies the only square connecting R1<->R2, so M2 has NO
    # reachable path to any hero at all -- not "blocked partway", fully
    # cut off. It correctly never attempts to move.
    assert m2_result.action == "no_target"
    assert "M2" not in result.updated_monster_positions
