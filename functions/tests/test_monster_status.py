"""Sleep and Tempest, from the monster's side of the board.

The mirror of test_hero_status: a held HERO is stopped by refusing their
actions, a held MONSTER by Zargon skipping its turn -- and Zargon rolls
its own saving throws, since monster Mind Points are digital.
"""

import random

from engine.monster_status import (
    add_status,
    defend_dice_for,
    is_asleep,
    is_held,
    roll_break_attempts,
)
from engine.zargon_turn import resolve_zargon_turn

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}


def _quest(monsters):
    return {
        "doors": [D1],
        "objective": {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
        "rooms": {"R2": {"monsters": monsters, "traps": [], "furniture": []}},
    }


def _state(monsters):
    return {
        "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [5, 2], "alive": True}],
        "monsters": monsters,
        "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
        "doors": {"D1": "open"},
        "turn": 3,
        "monsterStatus": {},
    }


def test_a_sleeping_monster_rolls_no_defend_dice():
    state = _state({})
    add_status(state, "M1", status="asleep", spell="sleep", turn=1)
    assert defend_dice_for(state, "M1", 4) == 0
    assert defend_dice_for(state, "M2", 4) == 4


def test_a_held_monster_takes_no_turn(catalogs):
    quest = _quest([{"id": "M1", "type": "orc", "pos": [6, 2]}])
    state = _state({"M1": {"type": "orc", "pos": [6, 2], "currentBody": 1, "alive": True}})
    add_status(state, "M1", status="asleep", spell="sleep", turn=3)

    result = resolve_zargon_turn(
        board=catalogs.board, catalogs=catalogs, quest=quest, game_state=state,
        turn_type="normal", rng=random.Random(5),
    )
    assert result.monster_results[0].action == "held"
    assert result.updated_monster_positions == {}


def test_zargon_rolls_the_sleeping_monsters_own_save(catalogs):
    # An orc has 2 Mind Points, so two dice, waking on any 6.
    state = _state({"M1": {"type": "orc", "pos": [6, 2], "currentBody": 1, "alive": True}})
    add_status(state, "M1", status="asleep", spell="sleep", turn=1)
    defs = {"M1": {"type": "orc", "name": "Grukk"}}

    woke = False
    for seed in range(30):
        trial = _state({"M1": {"type": "orc", "pos": [6, 2], "currentBody": 1, "alive": True}})
        add_status(trial, "M1", status="asleep", spell="sleep", turn=1)
        roll_break_attempts(trial, defs, catalogs, turn=4, rng=random.Random(seed))
        if not is_asleep(trial, "M1"):
            woke = True
            break
    assert woke, "a sleeping monster should wake eventually"


def test_a_tempest_costs_exactly_one_turn(catalogs):
    state = _state({"M1": {"type": "orc", "pos": [6, 2], "currentBody": 1, "alive": True}})
    add_status(state, "M1", status="becalmed", spell="tempest", turn=3, misses_turns=1)
    defs = {"M1": {"type": "orc", "name": "Grukk"}}

    # The turn it landed on: still held.
    roll_break_attempts(state, defs, catalogs, turn=3, rng=random.Random(1))
    assert is_held(state, "M1") is not None

    # The turn after: it blows over.
    roll_break_attempts(state, defs, catalogs, turn=4, rng=random.Random(1))
    assert is_held(state, "M1") is None
