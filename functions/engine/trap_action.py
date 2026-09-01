"""Resolves what a hero does about a trap they already know is there:
JUMP it, DISARM it, or step on it deliberately.

Movement stops in front of a known trap (engine/hero_movement.py), so
this is the follow-up action -- the same two-step shape as opening a
door, and for the same reason: the app can't prompt mid-resolution.

The dice are the HERO's, so the app never rolls them. It names the roll
("roll 1 combat die"), the player reports the face, and this module
applies the consequence -- exactly the pattern combat.record_hero_defense
and resolve_hero_attack already use for skulls and shields.

Rulebook outcomes, verified against the owner's photos:

- JUMP (page 20): needs two squares of movement, landing on an
  unoccupied square beyond the trap. Roll 1 combat die: anything but a
  skull clears it; a skull springs the trap. Movement points are the
  hero's own bookkeeping (2 red dice, never entered into the app), so
  the "two squares remaining" half is the player's to honour -- the app
  checks only that the landing square is legal. "Beyond" is not
  "straight across": "there may be as many as 3 possible squares to
  jump to on the other sides of a single pit. However, a pit in the
  corner of a corridor has only 1 space open to jump across to." So
  any square next to the trap other than the one the hero stands on
  is a landing, as long as the hero could have STEPPED there from the
  trap square -- a wall, a closed door, a blocked square or furniture
  removes it. Found in live play: the client always jumped straight
  across, and the server let a hero land through a room wall.
- DISARM (page 21): the Dwarf needs no tool kit and fails only on a
  BLACK shield; every other hero needs a tool kit and succeeds on
  either shield, failing on a skull. Tool-kit possession is inventory,
  which is physical -- the caller asserts it. A disarmed trap is
  "gone": no tile, no further danger.
- STEP: walking on deliberately springs it, same as never having found
  it. Included so a known trap is a decision, not a wall.
- SPEAR traps (page 19) are their own case: stepping on one is not a
  choice but a die roll -- a skull costs a Body Point and ends the
  turn, either shield dodges it and "the spear trap is now gone
  forever", so the hero continues onto the square. There are no spear
  trap tiles, so nothing is ever placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .heroes import HeroCannotActError, find_living_hero, living_heroes, require_hero_can_act
from .movement import passable_door_edges
from validator.catalogs import Board
from validator.geometry import furniture_squares

Coord = tuple[int, int]

DIE_FACES = ("skull", "white_shield", "black_shield")
TRAP_ACTIONS = ("jump", "disarm", "step")

DWARF_HERO_ID = "dwarf"


class InvalidTrapActionError(ValueError):
    """The action can't happen: unknown trap, hero not adjacent to it,
    an illegal landing square, a missing die result, or a non-Dwarf
    trying to disarm without a tool kit.
    """


@dataclass
class TrapActionResult:
    trap_id: str
    action: str
    sprung: bool
    disarmed: bool
    hero_pos: Coord
    placement_instruction: str | None = None
    log: list[str] = field(default_factory=list)


def _orthogonally_adjacent(a: Coord, b: Coord) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def _landing_problem(
    board: Board, quest: dict, game_state: dict, trap_pos: Coord, landing: Coord, catalogs
) -> str | None:
    """Why a jump can't come down on `landing`, or None if it can. The
    same passability a step from the trap square would need: on the
    board, no wall between (an OPEN door edge counts as no wall), not a
    blocked or collapsed square, not furniture."""
    landing_area = board.area_of.get(landing)
    if landing_area is None:
        return "the landing square is off the board"
    if landing_area != board.area_of.get(trap_pos):
        open_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
        if frozenset((tuple(trap_pos), tuple(landing))) not in open_edges:
            return "the landing square is on the other side of a wall -- a jump can't go through it"
    blocked = {tuple(sq) for sq in quest.get("blockedSquares", [])} | {
        tuple(sq) for sq in game_state.get("collapsedSquares", [])
    }
    if tuple(landing) in blocked:
        return "the landing square is blocked"
    if catalogs is not None and tuple(landing) in furniture_squares(quest, catalogs):
        return "furniture stands on the landing square"
    return None


def _spring(trap_type: str, pos: Coord, hero_id: str) -> tuple[str | None, str]:
    """Returns (placement_instruction, log line) for a sprung trap.
    A spear trap has no tile -- "Note: There are no spear trap tiles."
    """
    if trap_type == "spear":
        return None, (
            f"The spear catches {hero_id} at [{pos[0]},{pos[1]}] -- 1 Body Point of damage, and the turn ends."
        )
    if trap_type == "falling_block":
        instruction = (
            f"Place the falling block trap tile at square [{pos[0]},{pos[1]}] -- "
            f"that square is blocked for the rest of the quest."
        )
        return instruction, (
            f"{hero_id} springs the falling block at [{pos[0]},{pos[1]}]! The ceiling caves in. "
            f"Roll 3 combat dice -- 1 Body Point per skull, no defend dice. {instruction}"
        )
    instruction = f"Place the pit trap tile at square [{pos[0]},{pos[1]}], under the hero's figure."
    return instruction, (
        f"{hero_id} drops into the pit at [{pos[0]},{pos[1]}]! 1 Body Point of damage, and the turn ends. "
        f"{instruction}"
    )


def resolve_trap_action(
    *,
    board: Board,
    quest: dict,
    game_state: dict,
    hero_id: str,
    trap_id: str,
    trap_type: str,
    trap_pos: Coord,
    action: str,
    die_face: str | None = None,
    landing: Coord | None = None,
    has_tool_kit: bool = False,
    catalogs=None,
) -> TrapActionResult:
    """`catalogs` is only needed to keep a jump from landing on
    furniture (footprints come from the furniture catalog); without it
    that one check is skipped."""
    if action not in TRAP_ACTIONS:
        raise InvalidTrapActionError(f"action must be one of {TRAP_ACTIONS}, got '{action}'")

    heroes = living_heroes(game_state)
    hero = find_living_hero(game_state, hero_id)
    if hero is None:
        raise InvalidTrapActionError(f"hero '{hero_id}' is not in this game, or has fallen")
    try:
        require_hero_can_act(game_state, hero)
    except HeroCannotActError as e:
        raise InvalidTrapActionError(str(e)) from e
    hero_pos = tuple(hero["pos"])

    already_sprung = trap_id in set(game_state.get("trapsTriggered", []))
    if already_sprung and not (trap_type == "pit" and action in ("jump", "step")):
        # A sprung pit is the one trap that stays interactive: crossing
        # the open hole means jumping it or climbing in (1989 rulebook
        # p.19-20). "Once a pit trap is sprung ... the trap cannot be
        # disarmed and removed" -- and every other sprung trap is
        # simply over.
        raise InvalidTrapActionError(f"trap '{trap_id}' has already been sprung")
    if trap_id not in set(game_state.get("trapsFound", [])):
        raise InvalidTrapActionError(f"trap '{trap_id}' hasn't been found yet -- search for traps first")
    if not _orthogonally_adjacent(hero_pos, trap_pos):
        raise InvalidTrapActionError(f"hero '{hero_id}' is not next to the trap at {list(trap_pos)}")

    if already_sprung and action == "step":
        # Climbing into the open pit deliberately. The rulebook's
        # occupied-landing case makes the cost explicit: "you must
        # voluntarily fall into the pit (suffering damage)". Standing
        # in it is legal (sharing rules) and costs one attack/defend
        # die; climbing out is next turn's movement.
        return TrapActionResult(
            trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=trap_pos,
            log=[
                f"{hero_id} climbs down into the open pit at [{trap_pos[0]},{trap_pos[1]}] -- "
                f"1 Body Point of damage, and the move ends here. Attacks from the pit roll one die fewer; "
                f"climbing out is next turn's movement."
            ],
        )

    if already_sprung and action == "jump":
        if die_face not in DIE_FACES:
            raise InvalidTrapActionError(f"jumping the open pit needs the hero's die -- one of {DIE_FACES}")
        if landing is None:
            raise InvalidTrapActionError("a jump needs a landing square")
        landing = tuple(landing)
        if not _orthogonally_adjacent(landing, trap_pos) or landing == hero_pos:
            raise InvalidTrapActionError("the landing square must be next to the trap, on a side the hero isn't on")
        problem = _landing_problem(board, quest, game_state, trap_pos, landing, catalogs)
        if problem is not None:
            raise InvalidTrapActionError(problem)
        occupied = {tuple(h["pos"]) for h in heroes if h["id"] != hero_id} | {
            tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
        }
        if landing in occupied:
            raise InvalidTrapActionError("the landing square is occupied")
        if die_face == "skull":
            return TrapActionResult(
                trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=trap_pos,
                log=[
                    f"{hero_id} tries to jump the open pit and rolls a skull -- they fall in! "
                    f"1 Body Point of damage, and the turn ends. The figure stands in the pit."
                ],
            )
        return TrapActionResult(
            trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=landing,
            log=[
                f"{hero_id} clears the open pit at {list(trap_pos)} and lands on {list(landing)} "
                f"(two squares of movement)."
            ],
        )

    if action == "step" and trap_type == "spear":
        # Not a choice but a reflex: the hero is already on the square.
        if die_face not in DIE_FACES:
            raise InvalidTrapActionError(f"a spear trap needs the hero's die -- one of {DIE_FACES}")
        if die_face == "skull":
            _, line = _spring(trap_type, trap_pos, hero_id)
            return TrapActionResult(
                trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=trap_pos, log=[line]
            )
        return TrapActionResult(
            trap_id=trap_id, action=action, sprung=False, disarmed=True, hero_pos=trap_pos,
            log=[
                f"{hero_id} dodges the spear at {list(trap_pos)}. It is gone forever -- "
                f"the square is safe now, and the move may continue."
            ],
        )

    if action == "step":
        instruction, line = _spring(trap_type, trap_pos, hero_id)
        # A pit puts the hero in it; a falling block never lets them past.
        landed = trap_pos if trap_type != "falling_block" else hero_pos
        return TrapActionResult(
            trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=landed,
            placement_instruction=instruction, log=[line],
        )

    if die_face not in DIE_FACES:
        raise InvalidTrapActionError(f"die_face must be one of {DIE_FACES}, got '{die_face}'")

    if action == "jump":
        if landing is None:
            raise InvalidTrapActionError("a jump needs a landing square")
        landing = tuple(landing)
        if not _orthogonally_adjacent(landing, trap_pos) or landing == hero_pos:
            raise InvalidTrapActionError("the landing square must be next to the trap, on a side the hero isn't on")
        problem = _landing_problem(board, quest, game_state, trap_pos, landing, catalogs)
        if problem is not None:
            raise InvalidTrapActionError(problem)
        occupied = {tuple(h["pos"]) for h in heroes if h["id"] != hero_id} | {
            tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
        }
        if landing in occupied:
            raise InvalidTrapActionError("the landing square is occupied")

        if die_face == "skull":
            instruction, line = _spring(trap_type, trap_pos, hero_id)
            landed = trap_pos if trap_type != "falling_block" else hero_pos
            return TrapActionResult(
                trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=landed,
                placement_instruction=instruction,
                log=[f"{hero_id} tries to jump the {trap_type} and rolls a skull. {line}"],
            )
        return TrapActionResult(
            trap_id=trap_id, action=action, sprung=False, disarmed=False, hero_pos=landing,
            log=[f"{hero_id} clears the {trap_type} at {list(trap_pos)} and lands on {list(landing)} (two squares of movement)."],
        )

    # disarm
    is_dwarf = hero_id == DWARF_HERO_ID
    if not is_dwarf and not has_tool_kit:
        raise InvalidTrapActionError(
            f"'{hero_id}' needs a tool kit to disarm a trap (only the Dwarf can do it bare-handed)"
        )
    failed = die_face == "black_shield" if is_dwarf else die_face == "skull"
    if failed:
        instruction, line = _spring(trap_type, trap_pos, hero_id)
        landed = trap_pos if trap_type != "falling_block" else hero_pos
        return TrapActionResult(
            trap_id=trap_id, action=action, sprung=True, disarmed=False, hero_pos=landed,
            placement_instruction=instruction,
            log=[f"{hero_id}'s disarm attempt fails. {line}"],
        )
    return TrapActionResult(
        trap_id=trap_id, action=action, sprung=False, disarmed=True, hero_pos=hero_pos,
        log=[f"{hero_id} disarms the {trap_type} at {list(trap_pos)}. It is gone -- no tile goes on the board."],
    )
