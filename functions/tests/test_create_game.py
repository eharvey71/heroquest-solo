import pytest

from engine.create_game import InvalidRosterError, build_initial_game_state


def test_heroes_placed_within_stairway_footprint(good_quest_4h, catalogs):
    heroes = [{"id": "barbarian", "name": "Barbarian"}, {"id": "wizard", "name": "Wizard"}]
    game_state = build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=heroes)

    stairway_pos = good_quest_4h["stairway"]["pos"]
    footprint = {
        (stairway_pos[0], stairway_pos[1]),
        (stairway_pos[0] + 1, stairway_pos[1]),
        (stairway_pos[0], stairway_pos[1] + 1),
        (stairway_pos[0] + 1, stairway_pos[1] + 1),
    }
    positions = [tuple(h["pos"]) for h in game_state["heroes"]]
    assert all(p in footprint for p in positions)
    assert len(set(positions)) == len(positions)  # no two heroes on the same square


def test_hero_order_determines_square_assignment(good_quest_4h, catalogs):
    heroes = [{"id": "barbarian", "name": "Barbarian"}, {"id": "wizard", "name": "Wizard"}]
    game_state = build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=heroes)

    stairway_pos = good_quest_4h["stairway"]["pos"]
    assert game_state["heroes"][0]["pos"] == list(stairway_pos)
    assert game_state["heroes"][1]["pos"] == [stairway_pos[0] + 1, stairway_pos[1]]


def test_four_heroes_fill_the_whole_stairway_footprint(good_quest_4h, catalogs):
    heroes = [{"id": f"h{i}", "name": f"Hero{i}"} for i in range(4)]
    game_state = build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=heroes)
    positions = {tuple(h["pos"]) for h in game_state["heroes"]}
    assert len(positions) == 4


def test_single_hero_quest_places_one_hero(good_quest_1h, catalogs):
    heroes = [{"id": "barbarian", "name": "Barbarian"}]
    game_state = build_initial_game_state(quest=good_quest_1h, catalogs=catalogs, heroes=heroes)
    assert len(game_state["heroes"]) == 1
    assert game_state["heroes"][0]["pos"] == list(good_quest_1h["stairway"]["pos"])


def test_hero_defaults_name_to_id_when_missing(good_quest_4h, catalogs):
    game_state = build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=[{"id": "barbarian"}])
    assert game_state["heroes"][0]["name"] == "barbarian"


def test_monster_roster_loaded_with_full_body_points(good_quest_4h, catalogs):
    game_state = build_initial_game_state(
        quest=good_quest_4h, catalogs=catalogs, heroes=[{"id": "barbarian", "name": "Barbarian"}]
    )
    # M17 is the boss with an override body of 4 (see good_4h_full.json)
    assert game_state["monsters"]["M17"]["currentBody"] == 4
    assert game_state["monsters"]["M17"]["alive"] is True
    # M1 (plain orc, no override) gets the catalog base body
    assert game_state["monsters"]["M1"]["currentBody"] == catalogs.monsters["orc"]["body"]
    assert game_state["monsters"]["M1"]["type"] == "orc"
    # every monster in the quest is present, none omitted for being unrevealed
    quest_monster_ids = {
        m["id"] for room in good_quest_4h["rooms"].values() for m in room.get("monsters", [])
    }
    assert set(game_state["monsters"].keys()) == quest_monster_ids
    # type is required by clients rendering a monster token (which icon/
    # letter to show) -- must be present on every entry, not just M1's.
    assert all("type" in m for m in game_state["monsters"].values())


def test_only_stairway_room_revealed(good_quest_4h, catalogs):
    game_state = build_initial_game_state(
        quest=good_quest_4h, catalogs=catalogs, heroes=[{"id": "barbarian", "name": "Barbarian"}]
    )
    assert game_state["revealed"]["rooms"] == [good_quest_4h["stairway"]["room"]]
    assert game_state["revealed"]["corridorSquares"] == []


def test_initial_phase_turn_and_log(good_quest_4h, catalogs):
    game_state = build_initial_game_state(
        quest=good_quest_4h, catalogs=catalogs, heroes=[{"id": "barbarian", "name": "Barbarian"}]
    )
    assert game_state["phase"] == "hero"
    assert game_state["status"] == "in_progress"
    assert game_state["turn"] == 1
    assert game_state["heroPhaseSegment"] == 1
    assert game_state["trapsTriggered"] == []
    assert game_state["searched"] == {}
    assert len(game_state["log"]) == 1


def test_rejects_empty_roster(good_quest_4h, catalogs):
    with pytest.raises(InvalidRosterError):
        build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=[])


def test_rejects_more_than_four_heroes(good_quest_4h, catalogs):
    with pytest.raises(InvalidRosterError):
        build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=[{"id": f"h{i}"} for i in range(5)])


def test_rejects_quest_with_no_stairway(catalogs):
    with pytest.raises(InvalidRosterError):
        build_initial_game_state(quest={}, catalogs=catalogs, heroes=[{"id": "barbarian"}])
