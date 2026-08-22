"""Trapped chests and tombs.

The rule (owner, from the quest books): searching a room for TREASURE
before searching it for TRAPS springs every trapped piece in that room
at once, ends the hero's turn, and the consequence is whatever the
quest says it is.
"""

import copy

from engine.furniture_traps import armed_furniture_traps, furniture_trap_id, room_furniture_traps
from engine.trap_search import resolve_trap_search
from engine.treasure import resolve_treasure_search

CHEST = {
    "type": "treasure_chest",
    "pos": [2, 2],
    "orientation": "N",
    "contains": {"trap": "chest_trap", "trapText": "A needle jabs your hand -- lose 1 Body Point.", "treasure": "deck"},
}
TOMB = {
    "type": "tomb",
    "pos": [1, 3],
    "orientation": "N",
    "contains": {"trap": "pit", "trapText": "The slab gives way beneath you.", "treasure": "none"},
}
PLAIN_CHEST = {"type": "treasure_chest", "pos": [3, 2], "orientation": "N", "contains": {"trap": "none", "treasure": "deck"}}


def _quest(*furniture):
    return {
        "rooms": {"R1": {"monsters": [], "traps": [], "furniture": list(furniture)}},
        "doors": [],
        "blockedSquares": [],
        "wanderingMonster": "orc",
    }


def _state(searched=None, sprung=()):
    return {
        "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [1, 1], "alive": True}],
        "monsters": {},
        "revealed": {"rooms": ["R1"], "corridorSquares": []},
        "searched": searched or {},
        "trapsTriggered": list(sprung),
        "collapsedSquares": [],
    }


def _search_treasure(catalogs, quest, state):
    return resolve_treasure_search(
        board=catalogs.board, catalogs=catalogs, quest=quest, game_state=state,
        hero_id="barbarian", room_id="R1",
    )


def test_only_trapped_pieces_count(catalogs):
    quest = _quest(CHEST, PLAIN_CHEST, TOMB)
    assert {t.trap_id for t in room_furniture_traps(quest, "R1")} == {
        furniture_trap_id("R1", (2, 2)),
        furniture_trap_id("R1", (1, 3)),
    }


def test_greedy_search_springs_every_trap_in_the_room(catalogs):
    result = _search_treasure(catalogs, _quest(CHEST, TOMB), _state())

    assert len(result.sprung_furniture_traps) == 2
    assert result.treasure_drawn is False
    assert any("needle jabs your hand" in line for line in result.log)
    assert any("slab gives way" in line for line in result.log)
    assert any("turn ends" in line for line in result.log)


def test_a_chest_trap_puts_no_tile_on_the_board_but_a_pit_does(catalogs):
    needle = _search_treasure(catalogs, _quest(CHEST), _state())
    assert needle.placement_instructions == []

    pit = _search_treasure(catalogs, _quest(TOMB), _state())
    assert any("pit trap tile" in i for i in pit.placement_instructions)


def test_searching_for_traps_first_makes_the_room_safe(catalogs):
    state = _state(searched={"R1": {"traps": True}})
    result = _search_treasure(catalogs, _quest(CHEST, TOMB), state)

    assert result.sprung_furniture_traps == []
    assert result.treasure_drawn is True


def test_a_sprung_trap_never_fires_twice(catalogs):
    quest = _quest(CHEST)
    state = _state(sprung=[furniture_trap_id("R1", (2, 2))])
    assert armed_furniture_traps(quest, state, "R1") == []
    assert _search_treasure(catalogs, quest, state).treasure_drawn is True


def test_a_room_with_no_trapped_furniture_is_unaffected(catalogs):
    result = _search_treasure(catalogs, _quest(PLAIN_CHEST), _state())
    assert result.sprung_furniture_traps == []
    assert result.treasure_drawn is True


def test_the_trap_search_points_out_a_trapped_chest(catalogs):
    result = resolve_trap_search(
        board=catalogs.board, quest=_quest(CHEST), game_state=_state(),
        hero_id="barbarian", room_id="R1", search_type="traps",
    )
    assert len(result.found_furniture_traps) == 1
    assert any("is trapped" in line for line in result.log)
    assert "Nothing found." not in result.log


def test_a_secret_door_search_says_nothing_about_furniture(catalogs):
    result = resolve_trap_search(
        board=catalogs.board, quest=_quest(CHEST), game_state=_state(),
        hero_id="barbarian", room_id="R1", search_type="secret_doors",
    )
    assert result.found_furniture_traps == []


def test_missing_trap_text_still_narrates(catalogs):
    bare = copy.deepcopy(CHEST)
    del bare["contains"]["trapText"]
    result = _search_treasure(catalogs, _quest(bare), _state())
    assert result.sprung_furniture_traps
    assert any("consequence from the quest" in line for line in result.log)
