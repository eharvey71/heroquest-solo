import random

import pytest

from engine.treasure import InvalidTreasureSearchError, RoomNotFoundError, resolve_treasure_search


def _hero_at(pos):
    return [{"id": "barbarian", "name": "Barbarian", "pos": list(pos), "active": True}]


def _game_state(pos, revealed_rooms, searched=None):
    return {
        "heroes": _hero_at(pos),
        "monsters": {},
        "revealed": {"rooms": revealed_rooms, "corridorSquares": []},
        "searched": searched or {},
    }


def test_searches_treasure_and_flags_room(good_quest_4h, catalogs):
    # R1 is the stairway room; hero starts at [1,1] which is in R1.
    game_state = _game_state((1, 1), ["R1"])
    result = resolve_treasure_search(
        board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
        hero_id="barbarian", room_id="R1",
    )
    assert result.room_id == "R1"
    assert result.spawned_monster is None
    assert result.log


def test_rejects_unknown_room(good_quest_4h, catalogs):
    game_state = _game_state((1, 1), ["R1"])
    with pytest.raises(RoomNotFoundError):
        resolve_treasure_search(
            board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
            hero_id="barbarian", room_id="R99",
        )


def test_rejects_hero_not_in_room(good_quest_4h, catalogs):
    game_state = _game_state((1, 1), ["R1"])
    with pytest.raises(InvalidTreasureSearchError):
        resolve_treasure_search(
            board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
            hero_id="barbarian", room_id="R3",
        )


def test_rejects_unrevealed_room(good_quest_4h, catalogs):
    # Hero physically standing there (shouldn't happen without reveal,
    # but the check is independent -- defensive backstop).
    game_state = _game_state((1, 1), [])
    with pytest.raises(InvalidTreasureSearchError):
        resolve_treasure_search(
            board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
            hero_id="barbarian", room_id="R1",
        )


def test_rejects_already_searched_room(good_quest_4h, catalogs):
    game_state = _game_state((1, 1), ["R1"], searched={"R1": {"treasure": True}})
    with pytest.raises(InvalidTreasureSearchError):
        resolve_treasure_search(
            board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
            hero_id="barbarian", room_id="R1",
        )


def test_wandering_monster_drawn_spawns_and_attacks_immediately(good_quest_4h, catalogs):
    game_state = _game_state((1, 1), ["R1"])
    result = resolve_treasure_search(
        board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
        hero_id="barbarian", room_id="R1", wandering_monster_drawn=True, rng=random.Random(1),
    )
    assert result.spawned_monster is not None
    assert result.spawned_monster["type"] == good_quest_4h["wanderingMonster"]
    assert result.spawned_monster["attacksImmediately"] is True
    assert result.monster_attack is not None
    assert result.monster_attack.hero_name == "Barbarian"


def test_no_wandering_monster_card_means_no_spawn(good_quest_4h, catalogs):
    game_state = _game_state((1, 1), ["R1"])
    result = resolve_treasure_search(
        board=catalogs.board, catalogs=catalogs, quest=good_quest_4h, game_state=game_state,
        hero_id="barbarian", room_id="R1", wandering_monster_drawn=False,
    )
    assert result.spawned_monster is None
    assert result.monster_attack is None
