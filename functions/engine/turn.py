"""Per-monster turn orchestration: move toward the selected target (or
hold position if guarding), then attack if now adjacent.

Multi-monster turn ORDER -- which monster acts first within one Zargon
turn, when several are in play -- is a Zargon-player judgment call in
the physical rules, not a fixed algorithm. This module processes one
monster at a time; the caller decides sequencing (a reasonable default
is simply the order monsters are listed in game state).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from validator.catalogs import Board

from .combat import MonsterAttackRoll, roll_monster_attack
from .movement import Coord, move_toward, squares_adjacent_to
from .targeting import guard_should_engage


@dataclass
class MonsterTurnResult:
    monster_id: str
    start_pos: Coord
    end_pos: Coord
    moved: bool
    attacked: bool
    attack: MonsterAttackRoll | None
    log: list[str] = field(default_factory=list)


def take_monster_turn(
    *,
    board: Board,
    revealed: set[Coord],
    door_edges: set[frozenset],
    occupied: set[Coord],
    monster_id: str,
    monster_name: str,
    monster_pos: Coord,
    move_points: int,
    attack_dice: int,
    target_hero_id: str,
    target_hero_name: str,
    target_hero_pos: Coord,
    guarding: bool = False,
    monster_room_id: str | None = None,
    heroes: list[dict] | None = None,
    rng: random.Random | None = None,
) -> MonsterTurnResult:
    """`guarding`, `monster_room_id`, and `heroes` are only required
    together: a guard holds position until guard_should_engage() finds
    a hero in its room (or at an open doorway looking in) -- see that
    function for why plain adjacency-to-the-monster isn't the trigger.
    """
    if guarding:
        if monster_room_id is None or heroes is None:
            raise ValueError("monster_room_id and heroes are required when guarding=True")
        if not guard_should_engage(board, monster_room_id, door_edges, heroes):
            return MonsterTurnResult(
                monster_id=monster_id,
                start_pos=monster_pos,
                end_pos=monster_pos,
                moved=False,
                attacked=False,
                attack=None,
                log=[f"{monster_name} guards its position."],
            )

    already_adjacent = monster_pos in squares_adjacent_to(target_hero_pos)
    end_pos = monster_pos
    moved = False
    log: list[str] = []

    if not already_adjacent:
        move_result = move_toward(board, revealed, door_edges, occupied, monster_pos, target_hero_pos, move_points)
        if move_result is None:
            return MonsterTurnResult(
                monster_id=monster_id,
                start_pos=monster_pos,
                end_pos=monster_pos,
                moved=False,
                attacked=False,
                attack=None,
                log=[f"{monster_name} has no path to {target_hero_name}."],
            )
        end_pos = move_result.reachable_this_turn[-1]
        moved = end_pos != monster_pos
        if moved:
            log.append(f"{monster_name} moves toward {target_hero_name}.")
        already_adjacent = move_result.reached_target_adjacency

    attack: MonsterAttackRoll | None = None
    if already_adjacent:
        attack = roll_monster_attack(
            monster_name=monster_name, hero_name=target_hero_name, attack_dice=attack_dice, rng=rng
        )
        log.append(attack.log)
    else:
        log.append(f"{monster_name} moves toward {target_hero_name} but isn't in range yet.")

    return MonsterTurnResult(
        monster_id=monster_id,
        start_pos=monster_pos,
        end_pos=end_pos,
        moved=moved,
        attacked=attack is not None,
        attack=attack,
        log=log,
    )
