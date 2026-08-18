import random

import pytest

from engine.movement import passable_door_edges, revealed_squares
from engine.targeting import (
    TURN_WEIGHTS_BY_HERO_COUNT,
    _frontier_squares,
    guard_should_engage,
    needs_cunning_target_prompt,
    roll_turn_type,
    select_cunning_target,
    select_normal_target,
    should_guard,
    spawn_wandering_monster_from_treasure_card,
    spawn_wandering_monster_from_turn_roll,
    turn_type_weights,
)

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}  # R1 <-> R2
D2 = {"id": "D2", "squares": [[8, 1], [9, 1]], "state": "closed"}  # R2 <-> R3


def test_turn_weights_match_claude_md_table():
    assert TURN_WEIGHTS_BY_HERO_COUNT[4] == {"normal": 72, "cunning": 24, "wandering": 4}
    assert TURN_WEIGHTS_BY_HERO_COUNT[3] == {"normal": 76, "cunning": 20, "wandering": 4}
    assert TURN_WEIGHTS_BY_HERO_COUNT[2] == {"normal": 80, "cunning": 16, "wandering": 4}
    assert TURN_WEIGHTS_BY_HERO_COUNT[1] == {"normal": 84, "cunning": 12, "wandering": 4}


def test_hard_difficulty_shifts_one_point_from_normal_to_wandering():
    standard = turn_type_weights(4, "standard")
    hard = turn_type_weights(4, "hard")
    assert hard["wandering"] == standard["wandering"] + 1
    assert hard["normal"] == standard["normal"] - 1
    assert hard["cunning"] == standard["cunning"]
    assert sum(hard.values()) == sum(standard.values()) == 100


@pytest.mark.parametrize("hero_count", [1, 2, 3, 4])
def test_roll_turn_type_distribution_matches_weights(hero_count):
    rng = random.Random(hero_count)
    n = 30_000
    counts = {"normal": 0, "cunning": 0, "wandering": 0}
    for _ in range(n):
        counts[roll_turn_type(hero_count, "standard", rng)] += 1
    weights = turn_type_weights(hero_count)
    for turn_type, weight in weights.items():
        assert abs(counts[turn_type] / n - weight / 100) < 0.02


def test_select_normal_target_picks_nearest_hero(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    revealed = revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})
    heroes = [
        {"id": "barbarian", "pos": [2, 2]},  # far side of R1
        {"id": "wizard", "pos": [5, 2]},  # right next to the door, closest to the monster
    ]
    target = select_normal_target(board, revealed, edges, set(), (6, 2), heroes)
    assert target == "wizard"


def test_select_normal_target_none_when_no_hero_reachable(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "locked"})
    revealed = revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})
    heroes = [{"id": "barbarian", "pos": [2, 2]}]
    target = select_normal_target(board, revealed, edges, set(), (6, 2), heroes)
    assert target is None


def test_needs_cunning_prompt_only_with_multiple_heroes():
    one = [{"id": "barbarian", "pos": [1, 1]}]
    two = one + [{"id": "wizard", "pos": [2, 2]}]
    assert needs_cunning_target_prompt(one) is False
    assert needs_cunning_target_prompt(two) is True


def test_select_cunning_target_single_hero_needs_no_answer():
    heroes = [{"id": "barbarian", "pos": [1, 1]}]
    assert select_cunning_target(heroes, None) == "barbarian"


def test_select_cunning_target_requires_answer_for_multiple_heroes():
    heroes = [{"id": "barbarian", "pos": [1, 1]}, {"id": "wizard", "pos": [2, 2]}]
    with pytest.raises(ValueError):
        select_cunning_target(heroes, None)


def test_select_cunning_target_rejects_unknown_hero_id():
    heroes = [{"id": "barbarian", "pos": [1, 1]}, {"id": "wizard", "pos": [2, 2]}]
    with pytest.raises(ValueError):
        select_cunning_target(heroes, "dwarf")


def test_select_cunning_target_uses_given_answer():
    heroes = [{"id": "barbarian", "pos": [1, 1]}, {"id": "wizard", "pos": [2, 2]}]
    assert select_cunning_target(heroes, "wizard") == "wizard"


def test_should_guard_matches_objective_room_only():
    assert should_guard("R12", "R12") is True
    assert should_guard("R2", "R12") is False


# -- guard_should_engage: room entry or open-doorway line of sight, not
# mere adjacency to the monster's own square --


def test_guard_engages_when_hero_is_in_the_room(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    heroes = [{"id": "barbarian", "pos": [1, 1]}]  # deep in R1, nowhere near the door
    assert guard_should_engage(board, "R1", edges, heroes) is True


def test_guard_engages_at_open_doorway_without_entering(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    # Hero stands in R2 at the door threshold -- can see into R1 without
    # having stepped inside yet.
    heroes = [{"id": "wizard", "pos": [5, 1]}]
    assert guard_should_engage(board, "R1", edges, heroes) is True


def test_guard_does_not_engage_through_a_locked_door(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "locked"})
    heroes = [{"id": "wizard", "pos": [5, 1]}]
    assert guard_should_engage(board, "R1", edges, heroes) is False


def test_guard_does_not_engage_through_a_plain_wall(catalogs):
    # (1,3) is in R1, (1,4) is in R4 -- real grid-adjacent squares across
    # a real wall, with no door declared between them. Adjacency alone
    # must not count as a sightline.
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    heroes = [{"id": "wizard", "pos": [1, 4]}]
    assert guard_should_engage(board, "R1", edges, heroes) is False


def test_guard_does_not_engage_when_hero_is_elsewhere(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    heroes = [{"id": "wizard", "pos": [8, 3]}]  # in R2, nowhere near the R1 door
    assert guard_should_engage(board, "R1", edges, heroes) is False


# -- treasure-card wandering monster: rulebook-mandated placement --


def test_treasure_card_spawn_adjacent_to_searcher(catalogs):
    board = catalogs.board
    result = spawn_wandering_monster_from_treasure_card(board, "orc", (2, 2), occupied=set())
    assert result["type"] == "orc"
    assert result["attacksImmediately"] is True
    assert result["pos"] in {(3, 2), (1, 2), (2, 3), (2, 1)}
    assert result["placementInstruction"] == f"Place the orc mini at square [{result['pos'][0]},{result['pos'][1]}]."


def test_treasure_card_spawn_falls_back_when_boxed_in(catalogs):
    board = catalogs.board
    searcher = (2, 2)
    occupied = {(3, 2), (1, 2), (2, 3), (2, 1)}  # every adjacent square taken
    result = spawn_wandering_monster_from_treasure_card(board, "orc", searcher, occupied)
    assert result is not None
    assert result["pos"] not in occupied
    # still close by -- BFS ring expansion, not a random far square
    assert abs(result["pos"][0] - 2) + abs(result["pos"][1] - 2) <= 2


def test_treasure_card_spawn_none_without_monster_type(catalogs):
    board = catalogs.board
    assert spawn_wandering_monster_from_treasure_card(board, "", (2, 2), set()) is None


# -- turn-roll wandering monster: frontier placement, stairway fallback --


def test_frontier_includes_door_to_unrevealed_room(catalogs):
    board = catalogs.board
    revealed = revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})
    frontier = _frontier_squares(board, revealed, [D1, D2])
    assert (8, 1) in frontier  # R2 side of the door into unrevealed R3
    assert (4, 1) not in frontier  # D1: both sides already revealed, not a frontier
    assert (5, 1) not in frontier


def test_frontier_includes_edge_of_revealed_corridor(catalogs):
    board = catalogs.board
    # (3,0) and (4,0) are adjacent corridor squares; only reveal (3,0).
    revealed = revealed_squares(board, {"rooms": [], "corridorSquares": [[3, 0]]})
    frontier = _frontier_squares(board, revealed, [])
    assert (3, 0) in frontier


def test_frontier_excludes_boundary_with_no_door(catalogs):
    # R1/R4 share a real wall at (1,3)/(1,4) with no door declared --
    # not a frontier, since nothing connects the two squares in-game.
    board = catalogs.board
    revealed = revealed_squares(board, {"rooms": ["R1"], "corridorSquares": []})
    frontier = _frontier_squares(board, revealed, [D1])
    assert (1, 3) not in frontier


def test_turn_roll_spawn_prefers_frontier_nearest_the_party(catalogs):
    board = catalogs.board
    revealed = revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})
    quest = {"wanderingMonster": "goblin"}
    heroes = [{"id": "barbarian", "pos": [7, 2]}]  # close to the R2/R3 frontier
    result = spawn_wandering_monster_from_turn_roll(board, quest, revealed, [D1, D2], set(), heroes)
    assert result["type"] == "goblin"
    assert result["attacksImmediately"] is False
    assert result["pos"] == (8, 1)
    assert result["placementInstruction"] == "Place the goblin mini at square [8,1]."


def test_turn_roll_spawn_falls_back_to_stairway_with_no_frontier(catalogs):
    board = catalogs.board
    # Fully revealed, self-contained territory -- no unrevealed
    # connection anywhere (only D1 is declared, and both its sides are
    # revealed).
    revealed = revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})
    quest = {"wanderingMonster": "goblin", "stairway": {"room": "R1", "pos": [1, 1]}}
    result = spawn_wandering_monster_from_turn_roll(board, quest, revealed, [D1], set(), [])
    assert result["pos"] == (1, 1)


def test_turn_roll_spawn_none_without_monster_type(catalogs):
    board = catalogs.board
    revealed = revealed_squares(board, {"rooms": ["R1"], "corridorSquares": []})
    assert spawn_wandering_monster_from_turn_roll(board, {}, revealed, [], set(), []) is None
