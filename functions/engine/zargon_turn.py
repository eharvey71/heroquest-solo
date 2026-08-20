"""Orchestrates one Zargon turn across every active monster, given an
ALREADY-ROLLED turn type. The roll itself (targeting.roll_turn_type)
is a separate step on purpose: a cunning turn sometimes needs to ask a
human "which hero is lowest on BP?", and that can't happen inside one
atomic resolution -- see functions/main.py's roll_zargon_turn_type /
resolve_zargon_turn split.

Per CLAUDE.md (documented in the "Zargon engine details" section):
guard-objective behavior is specific to CUNNING turns. On a normal
turn every active monster just chases the nearest hero, full stop.
On a cunning turn, most monsters focus-fire the given lowest-BP hero,
EXCEPT a monster stationed in the objective's own room, which holds
position unless a hero is actually in/at that room -- and if engaged,
fights whoever is actually there, not the globally focus-fired hero.

A monster only acts if its current position is in currently-revealed
territory -- Zargon doesn't move monsters the party hasn't found yet.
Room membership is derived from each monster's LIVE position, not its
original quest-declared room, since it may have moved on a prior turn.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from validator.catalogs import CORRIDOR, Board, Catalogs
from validator.geometry import furniture_squares

from .movement import Coord, passable_door_edges, revealed_squares
from .targeting import (
    guard_engaged_by,
    select_cunning_target,
    select_normal_target,
    should_guard,
    spawn_wandering_monster_from_turn_roll,
)
from .turn import MonsterTurnResult, take_monster_turn


@dataclass
class MonsterActionResult:
    monster_id: str
    monster_name: str
    action: str  # "moved_and_attacked" | "moved" | "held" | "guards" | "no_target"
    turn_result: MonsterTurnResult | None
    log: list[str] = field(default_factory=list)


@dataclass
class ZargonTurnResult:
    turn_type: str
    monster_results: list[MonsterActionResult] = field(default_factory=list)
    spawned_monster: dict | None = None  # {"type", "pos", "attacksImmediately", "placementInstruction"}
    updated_monster_positions: dict[str, Coord] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)


def _monster_defs(quest: dict) -> dict[str, dict]:
    """monster_id -> {type, overrides, name} from the quest's static
    declaration -- combat stats don't change at runtime, only position.
    """
    defs: dict[str, dict] = {}
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            defs[m["id"]] = {"type": m["type"], "overrides": m.get("overrides", {}), "name": m.get("name")}
    return defs


def _objective_room_id(quest: dict, game_state: dict, board: Board) -> str | None:
    target = quest.get("objective", {}).get("target", {})
    if "room" in target:
        return target["room"]
    monster_id = target.get("monsterId")
    if monster_id is None:
        return None
    monster_state = game_state.get("monsters", {}).get(monster_id)
    if monster_state and monster_state.get("alive"):
        return board.area_of.get(tuple(monster_state["pos"]))
    # Fallen or not-yet-placed boss: fall back to the quest's original
    # declaration so "guard the objective room" still means something.
    for room_id, room in quest.get("rooms", {}).items():
        for m in room.get("monsters", []):
            if m.get("id") == monster_id:
                return room_id
    return None


ZARGON_TURN_OPENING = {
    "normal": "Zargon's turn. The dungeon stirs...",
    "cunning": "Zargon's turn. Zargon smiles -- his creatures have picked a target.",
    "wandering": "Zargon's turn. Something else is prowling these halls...",
}

ZARGON_TURN_END = "Zargon ends his turn. The heroes may act."


def _turn_opening(turn_type: str, focus_hero_name: str | None) -> str:
    """Static, deterministic narration -- the LLM is never in the rules
    path (CLAUDE.md). Cunning names the hero being focus-fired, since
    that is the one Zargon decision the player can't infer from the
    board alone.
    """
    line = ZARGON_TURN_OPENING[turn_type]
    if turn_type == "cunning" and focus_hero_name:
        line += f" They close on {focus_hero_name}."
    return line


def resolve_zargon_turn(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    turn_type: str,
    lowest_bp_hero_id: str | None = None,
    rng: random.Random | None = None,
) -> ZargonTurnResult:
    if turn_type not in ("normal", "cunning", "wandering"):
        raise ValueError(f"unknown turn_type '{turn_type}'")

    heroes = game_state.get("heroes", [])
    heroes_by_id = {h["id"]: h for h in heroes}
    revealed = revealed_squares(board, game_state.get("revealed", {}))
    revealed_room_ids = set(game_state.get("revealed", {}).get("rooms", []))
    door_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    # Furniture is solid for monsters too -- a monster pathing through a
    # tomb would desync from the physical board (see hero_movement.py).
    furniture = furniture_squares(quest, catalogs)

    if turn_type == "wandering":
        occupied = {tuple(h["pos"]) for h in heroes} | {
            tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
        } | furniture
        spawn = spawn_wandering_monster_from_turn_roll(
            board, quest, revealed, quest.get("doors", []), occupied, heroes
        )
        opening = _turn_opening(turn_type, None)
        if spawn is None:
            # Two different reasons, and the log should not blame the
            # wrong one: the quest may declare no wandering monster at
            # all, or there may be nowhere legal to place it yet.
            reason = (
                "...but nothing answers the call (this quest declares no wandering monster)."
                if not quest.get("wanderingMonster")
                else "...but it finds no way in -- nowhere to place it yet."
            )
            return ZargonTurnResult(turn_type=turn_type, log=[opening, reason, ZARGON_TURN_END])
        return ZargonTurnResult(
            turn_type=turn_type,
            spawned_monster=spawn,
            log=[
                opening,
                f"A wandering {spawn['type']} appears! {spawn['placementInstruction']}",
                ZARGON_TURN_END,
            ],
        )

    # normal or cunning: validates/raises if a cunning prompt was needed
    # and not answered -- same rule as targeting.select_cunning_target.
    resolved_lowest_bp = select_cunning_target(heroes, lowest_bp_hero_id) if turn_type == "cunning" else None

    monster_defs = _monster_defs(quest)
    objective_room_id = _objective_room_id(quest, game_state, board)

    monster_positions: dict[str, Coord] = {
        mid: tuple(m["pos"]) for mid, m in game_state.get("monsters", {}).items() if m.get("alive")
    }
    hero_positions = {h["id"]: tuple(h["pos"]) for h in heroes}

    results: list[MonsterActionResult] = []
    updated_positions: dict[str, Coord] = {}
    turn_log: list[str] = []

    for monster_id, pos in list(monster_positions.items()):
        mdef = monster_defs.get(monster_id)
        if mdef is None:
            continue

        current_room = board.area_of.get(pos)
        location_revealed = pos in revealed if current_room == CORRIDOR else current_room in revealed_room_ids
        if not location_revealed:
            continue

        catalog_entry = catalogs.monsters.get(mdef["type"])
        if catalog_entry is None:
            continue
        overrides = mdef.get("overrides", {})
        attack_dice = overrides.get("attack", catalog_entry["attack"])
        move_points = overrides.get("move", catalog_entry["move"])
        monster_name = mdef.get("name") or mdef["type"]

        occupied = set(hero_positions.values()) | {
            p for other_id, p in monster_positions.items() if other_id != monster_id
        } | furniture

        target_id: str | None
        if turn_type == "cunning" and objective_room_id and should_guard(current_room, objective_room_id):
            engaged_by = guard_engaged_by(board, current_room, door_edges, heroes)
            if engaged_by is None:
                results.append(
                    MonsterActionResult(
                        monster_id=monster_id,
                        monster_name=monster_name,
                        action="guards",
                        turn_result=None,
                        log=[f"{monster_name} guards its position."],
                    )
                )
                turn_log.append(f"{monster_name} guards its position.")
                continue
            target_id = engaged_by
        elif turn_type == "cunning":
            target_id = resolved_lowest_bp
        else:
            target_id = select_normal_target(board, revealed, door_edges, occupied, pos, heroes)

        if target_id is None:
            results.append(
                MonsterActionResult(
                    monster_id=monster_id,
                    monster_name=monster_name,
                    action="no_target",
                    turn_result=None,
                    log=[f"{monster_name} has no target."],
                )
            )
            continue

        target_hero = heroes_by_id[target_id]
        tr = take_monster_turn(
            board=board,
            revealed=revealed,
            door_edges=door_edges,
            occupied=occupied,
            monster_id=monster_id,
            monster_name=monster_name,
            monster_pos=pos,
            move_points=move_points,
            attack_dice=attack_dice,
            target_hero_id=target_id,
            target_hero_name=target_hero.get("name", target_id),
            target_hero_pos=tuple(target_hero["pos"]),
            guarding=False,
            rng=rng,
        )
        monster_positions[monster_id] = tr.end_pos
        updated_positions[monster_id] = tr.end_pos
        action = "moved_and_attacked" if tr.attacked else ("moved" if tr.moved else "held")
        results.append(
            MonsterActionResult(monster_id=monster_id, monster_name=monster_name, action=action, turn_result=tr, log=tr.log)
        )
        turn_log.extend(tr.log)

    focus_hero = heroes_by_id.get(resolved_lowest_bp) if resolved_lowest_bp else None
    opening = _turn_opening(turn_type, focus_hero.get("name", resolved_lowest_bp) if focus_hero else None)
    if not turn_log:
        # Every monster is still hidden, or none are left alive -- say so
        # rather than emitting a turn that looks like it did nothing.
        turn_log = ["No monster stirs where the party can see."]

    return ZargonTurnResult(
        turn_type=turn_type,
        monster_results=results,
        updated_monster_positions=updated_positions,
        log=[opening, *turn_log, ZARGON_TURN_END],
    )
