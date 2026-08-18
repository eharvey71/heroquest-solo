"""Resolves the "search treasure" button (CLAUDE.md's interface list).

Treasure itself is entirely physical -- the owner draws from the real
treasure deck; the app never needs to know what was drawn. The app's
only jobs: enforce "one treasure search per room" (CLAUDE.md), and
handle the rulebook-mandated wandering-monster card. If the owner draws
it, the app spawns the monster adjacent to the searching hero and
rolls its attack immediately -- "attacks immediately" per
targeting.spawn_wandering_monster_from_treasure_card's docstring, not
a design choice. The hero then defends with their own physical dice
and reports shields via the existing record_hero_defense button, same
flow as any other monster attack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from validator.catalogs import Board, Catalogs

from .combat import MonsterAttackRoll, roll_monster_attack
from .targeting import spawn_wandering_monster_from_treasure_card

Coord = tuple[int, int]


class RoomNotFoundError(ValueError):
    """room_id isn't a real room on the board."""


class InvalidTreasureSearchError(ValueError):
    """The search can't happen right now: the hero isn't standing in
    the room, the room hasn't been revealed yet, or it's already been
    searched for treasure this quest (CLAUDE.md: one search per room,
    enforced by the app).
    """


@dataclass
class TreasureSearchResult:
    room_id: str
    spawned_monster: dict | None = None  # {"type","pos","attacksImmediately","placementInstruction"}
    monster_attack: MonsterAttackRoll | None = None
    log: list[str] = field(default_factory=list)


def resolve_treasure_search(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    hero_id: str,
    room_id: str,
    wandering_monster_drawn: bool = False,
    rng=None,
) -> TreasureSearchResult:
    if room_id not in board.room_squares:
        raise RoomNotFoundError(f"room '{room_id}' not found on the board")

    heroes = game_state.get("heroes", [])
    hero = next((h for h in heroes if h["id"] == hero_id), None)
    if hero is None:
        raise InvalidTreasureSearchError(f"hero '{hero_id}' not found in game state")
    hero_pos = tuple(hero["pos"])

    if board.area_of.get(hero_pos) != room_id:
        raise InvalidTreasureSearchError(f"hero '{hero_id}' is not standing in room '{room_id}'")

    if room_id not in game_state.get("revealed", {}).get("rooms", []):
        raise InvalidTreasureSearchError(f"room '{room_id}' has not been revealed yet")

    if game_state.get("searched", {}).get(room_id, {}).get("treasure"):
        raise InvalidTreasureSearchError(f"room '{room_id}' has already been searched for treasure")

    log = [f"{hero_id} searches {room_id} for treasure."]
    spawn = None
    monster_attack = None

    if wandering_monster_drawn:
        occupied = {tuple(h["pos"]) for h in heroes} | {
            tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
        }
        spawn = spawn_wandering_monster_from_treasure_card(board, quest.get("wanderingMonster"), hero_pos, occupied)
        if spawn is not None:
            log.append(f"A wandering {spawn['type']} appears! {spawn['placementInstruction']}")
            catalog_entry = catalogs.monsters.get(spawn["type"], {})
            monster_attack = roll_monster_attack(
                monster_name=spawn["type"],
                hero_name=hero.get("name", hero_id),
                attack_dice=catalog_entry.get("attack", 0),
                rng=rng,
            )
            log.append(monster_attack.log)

    return TreasureSearchResult(room_id=room_id, spawned_monster=spawn, monster_attack=monster_attack, log=log)
