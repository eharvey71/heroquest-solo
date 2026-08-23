"""Per-monster turn orchestration: move toward the selected target (or
hold position if guarding), then attack if now adjacent -- and, for a
monster that was already in contact, attack and THEN move.

Attack-then-move is a real 1989 rule: a monster may move and then act,
or act and then move (never move-partway-act-move, which is why only a
monster that started its turn adjacent gets to use it). It is governed
by WITHDRAW_POLICIES, because the unrestricted version is a balance
problem rather than a coding one:

- "none": the original behaviour. A monster that attacks stays put.
- "reposition": it may move, but must end its move still orthogonally
  adjacent to some hero -- it steps out of a flanked square, it never
  breaks contact. Measured at barely 1% of monster turns (being flanked
  WITH an escape square is rare), so it is nearly a no-op.
- "fall_back" (the default): the full rule. Hit, then step just out of
  reach -- the NEAREST square no hero can swing at, not a sprint for
  the far wall, which is both what a human Zargon does and what reads
  sensibly on the table. Fires on roughly 40% of monster turns.

The worry about the full rule was that hit-and-run would multiply how
long a monster survives, and threat cost (attack + defend + body) has
no term for that, so a 120-point quest would quietly play much harder.
The simulator says otherwise: across 150 games per cell the difference
between "none" and a withdrawing Zargon is smaller than the noise, and
far smaller than a 10% budget change. It trades damage output for
survivability -- a monster that leaves melee also stops attacking that
turn. See sim/README.md.

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
from .movement import Coord, move_toward, reachable_within, squares_adjacent_to
from .targeting import guard_should_engage

WITHDRAW_POLICIES = ("none", "reposition", "fall_back")
DEFAULT_WITHDRAW_POLICY = "fall_back"


@dataclass
class MonsterTurnResult:
    monster_id: str
    start_pos: Coord
    end_pos: Coord
    moved: bool
    attacked: bool
    attack: MonsterAttackRoll | None
    withdrew: bool = False
    log: list[str] = field(default_factory=list)


def _withdraw_square(
    *,
    board: Board,
    revealed: set[Coord],
    door_edges: set[frozenset],
    occupied: set[Coord],
    start: Coord,
    move_points: int,
    hero_squares: set[Coord],
    policy: str,
) -> Coord:
    """Where a monster that has just attacked moves to. `start` when it
    shouldn't move at all -- which is the answer whenever moving buys
    nothing, so a monster never shuffles for the sake of it.
    """
    if policy == "none" or move_points <= 0 or not hero_squares:
        return start

    reach = reachable_within(board, revealed, door_edges, occupied, start, move_points)

    if policy == "reposition":
        # Stay in the fight, but not surrounded: fewest heroes able to
        # swing back, and among equals the shortest move (so standing
        # still wins ties).
        candidates = [sq for sq in reach if squares_adjacent_to(sq) & hero_squares]
        if not candidates:
            return start
        return min(
            candidates,
            key=lambda sq: (len(squares_adjacent_to(sq) & hero_squares), reach[sq], sq[1], sq[0]),
        )

    # "fall_back": out of reach, but only just. Sprinting to the far end
    # of the room is equally legal and looks ridiculous on the table.
    out_of_reach = [sq for sq in reach if not (squares_adjacent_to(sq) & hero_squares)]
    if not out_of_reach:
        return start
    return min(out_of_reach, key=lambda sq: (reach[sq], sq[1], sq[0]))


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
    hero_squares: set[Coord] | None = None,
    withdraw_policy: str = DEFAULT_WITHDRAW_POLICY,
    rng: random.Random | None = None,
) -> MonsterTurnResult:
    """`guarding`, `monster_room_id`, and `heroes` are only required
    together: a guard holds position until guard_should_engage() finds
    a hero in its room (or at an open doorway looking in) -- see that
    function for why plain adjacency-to-the-monster isn't the trigger.

    `hero_squares` (every living hero's square) is what attack-then-move
    is judged against; without it the monster simply holds after
    attacking, same as withdraw_policy="none". A GUARD never withdraws
    whatever the policy says -- guarding is the whole point of it.
    """
    if withdraw_policy not in WITHDRAW_POLICIES:
        raise ValueError(f"withdraw_policy must be one of {WITHDRAW_POLICIES}, got '{withdraw_policy}'")
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
        # reachable_this_turn includes the start square, so the path
        # length is one less than its size -- actual squares crossed,
        # not straight-line distance, since a corridor bends.
        steps = len(move_result.reachable_this_turn) - 1
        already_adjacent = move_result.reached_target_adjacency

    attack: MonsterAttackRoll | None = None
    withdrew = False
    if already_adjacent:
        if moved:
            log.append(f"{monster_name} moves {steps} space{'s' if steps != 1 else ''} toward {target_hero_name}.")
        attack = roll_monster_attack(
            monster_name=monster_name, hero_name=target_hero_name, attack_dice=attack_dice, rng=rng
        )
        log.append(attack.log)

        # Attack THEN move -- only for a monster that hadn't already
        # spent its movement getting here, and never for a guard.
        if not moved and not guarding:
            destination = _withdraw_square(
                board=board,
                revealed=revealed,
                door_edges=door_edges,
                occupied=occupied,
                start=monster_pos,
                move_points=move_points,
                hero_squares=set(hero_squares or ()),
                policy=withdraw_policy,
            )
            if destination != monster_pos:
                end_pos = destination
                withdrew = True
                still_in_contact = bool(squares_adjacent_to(end_pos) & set(hero_squares or ()))
                log.append(
                    f"{monster_name} shifts to [{end_pos[0]},{end_pos[1]}], still in reach."
                    if still_in_contact
                    else f"{monster_name} strikes and falls back to [{end_pos[0]},{end_pos[1]}]."
                )
    else:
        log.append(
            f"{monster_name} moves {steps} space{'s' if steps != 1 else ''} toward "
            f"{target_hero_name} but isn't in range yet."
        )

    return MonsterTurnResult(
        monster_id=monster_id,
        start_pos=monster_pos,
        end_pos=end_pos,
        moved=moved or withdrew,
        attacked=attack is not None,
        attack=attack,
        withdrew=withdrew,
        log=log,
    )
