"""Trapped chests and tombs.

The 1989 quest books trap furniture, and the trap springs on a party
that searches a room for TREASURE before it searches that room for
TRAPS. Searching for traps first finds the thing and the party opens it
carefully; going straight for the loot sets it off.

Two details from the owner, both of which shape this module:

- EVERY armed piece in the room springs, not just the one being opened.
  One greedy search sets off the whole room.
- "You then suffer the consequences described in the quest book." The
  effect is quest-authored text, not a formula the app computes -- and
  Body Points are physical anyway (CLAUDE.md's boundary), so the app
  narrates the consequence and the player applies it. Springing one
  ends the hero's turn, same as any other trap.

A furniture trap has no id in the quest schema (furniture entries carry
none), so it is identified by where it stands: "R4:3,10". That is
unique -- the validator already rejects two pieces on one square -- and
it goes in the existing trapsTriggered registry, which is exactly what
that registry means: sprung, inert, never again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Trap types that have a physical tile in the box. A chest trap usually
# doesn't -- it's a needle or a gas, narrated and then gone.
TILED_TRAP_TYPES = ("pit", "falling_block")


@dataclass
class FurnitureTrap:
    trap_id: str
    furniture_type: str
    trap_type: str
    pos: tuple[int, int]
    text: str


@dataclass
class FurnitureTrapResult:
    sprung: list[FurnitureTrap] = field(default_factory=list)
    placement_instructions: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    @property
    def any_sprung(self) -> bool:
        return bool(self.sprung)


def furniture_trap_id(room_id: str, pos) -> str:
    return f"{room_id}:{pos[0]},{pos[1]}"


def room_furniture_traps(quest: dict, room_id: str) -> list[FurnitureTrap]:
    """Every trapped piece declared in this room, sprung or not."""
    room = quest.get("rooms", {}).get(room_id, {})
    traps = []
    for piece in room.get("furniture", []):
        contains = piece.get("contains") or {}
        trap_type = contains.get("trap", "none")
        pos = piece.get("pos")
        if trap_type in (None, "none") or not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            continue
        traps.append(
            FurnitureTrap(
                trap_id=furniture_trap_id(room_id, pos),
                furniture_type=piece.get("type", "furniture"),
                trap_type=trap_type,
                pos=(pos[0], pos[1]),
                text=contains.get("trapText") or "",
            )
        )
    return traps


def armed_furniture_traps(quest: dict, game_state: dict, room_id: str) -> list[FurnitureTrap]:
    """Trapped pieces that haven't gone off yet."""
    spent = set(game_state.get("trapsTriggered", []))
    return [t for t in room_furniture_traps(quest, room_id) if t.trap_id not in spent]


def room_searched_for_traps(game_state: dict, room_id: str) -> bool:
    return bool(game_state.get("searched", {}).get(room_id, {}).get("traps"))


def spring_furniture_traps(traps: list[FurnitureTrap], hero_name: str) -> FurnitureTrapResult:
    """Narrates every trap going off at once and ends the hero's turn.

    Damage is never computed here: the consequence is the quest's own
    text and the hero sheet is physical.
    """
    result = FurnitureTrapResult()
    if not traps:
        return result

    for trap in traps:
        result.sprung.append(trap)
        where = f"[{trap.pos[0]},{trap.pos[1]}]"
        consequence = trap.text.strip() or "Apply the consequence from the quest."
        result.log.append(f"The {trap.furniture_type} at {where} was trapped! {consequence}")
        if trap.trap_type in TILED_TRAP_TYPES:
            instruction = (
                f"Place the {trap.trap_type.replace('_', ' ')} trap tile at square {where}."
                if trap.trap_type == "falling_block"
                else f"Place the pit trap tile at square {where}."
            )
            result.placement_instructions.append(instruction)
            result.log.append(instruction)

    result.log.append(
        f"{hero_name}'s turn ends -- no treasure is drawn. The room is safe to search now that everything has gone off."
    )
    return result
