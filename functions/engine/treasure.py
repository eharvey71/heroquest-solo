"""Resolves the "search treasure" button (CLAUDE.md's interface list).

Treasure itself is entirely physical -- the owner draws from the real
treasure deck; the app never needs to know what was drawn. The app's
only jobs: enforce "one treasure search per HERO per room" (1989 NA
rulebook, corrected from an earlier per-room-total misreading --
tracked as searched.<room>.treasureBy, a list of hero ids), enforce
that the room is clear of monsters first, and
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
from .heroes import find_living_hero, living_heroes
from .targeting import spawn_wandering_monster_from_treasure_card

Coord = tuple[int, int]


class RoomNotFoundError(ValueError):
    """room_id isn't a real room on the board."""


class InvalidTreasureSearchError(ValueError):
    """The search can't happen right now: the hero isn't standing in
    the room, the room hasn't been revealed yet, monsters are still in
    the room, or this hero already searched this room for treasure
    (1989 rulebook: one search per hero per room, in a room clear of
    monsters).
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

    heroes = living_heroes(game_state)
    hero = find_living_hero(game_state, hero_id)
    if hero is None:
        raise InvalidTreasureSearchError(f"hero '{hero_id}' is not in this game, or has fallen")
    hero_pos = tuple(hero["pos"])

    if board.area_of.get(hero_pos) != room_id:
        raise InvalidTreasureSearchError(f"hero '{hero_id}' is not standing in room '{room_id}'")

    if room_id not in game_state.get("revealed", {}).get("rooms", []):
        raise InvalidTreasureSearchError(f"room '{room_id}' has not been revealed yet")

    # "You may search a room for treasure only if the room is
    # uninhabited by monsters" (1989 rulebook, Action 3).
    if any(
        m.get("alive") and board.area_of.get(tuple(m["pos"])) == room_id
        for m in game_state.get("monsters", {}).values()
    ):
        raise InvalidTreasureSearchError(f"room '{room_id}' still has monsters in it -- clear them first")

    # Legacy game docs carry a per-room "treasure": True boolean from
    # the old (wrong) rule; it records no searcher, so it can't block
    # anyone under the per-hero rule and is deliberately ignored.
    if hero_id in game_state.get("searched", {}).get(room_id, {}).get("treasureBy", []):
        raise InvalidTreasureSearchError(f"hero '{hero_id}' has already searched room '{room_id}' for treasure")

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
