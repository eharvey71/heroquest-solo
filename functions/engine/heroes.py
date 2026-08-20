"""Which heroes are still standing, and what happens when one isn't.

Body Points are physical (CLAUDE.md's boundary), so the app can never
work out for itself that a hero has died -- the player reports it, the
same handoff as skulls and shields. What the app DOES own is everything
that follows: the mini comes off the board, so the square frees up,
Zargon stops pathing to it and stops asking for defence rolls, the
hero drops out of cunning targeting, and standing there no longer
counts as "a hero reached the stairway".

A dead hero is never removed from the roster. The party's SIZE at game
creation is what the quest budget was priced against, and the
lone-hero 2-actions rule keys off that same number (CLAUDE.md: "roster
size at game creation, not survivor count"), so the entry stays put
with alive=False.

Games created before this existed have no `alive` field at all, so
missing means alive -- never dead.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class HeroNotFoundError(ValueError):
    """No hero with that id in this game."""


class HeroAlreadyDeadError(ValueError):
    """That hero has already been reported dead."""


@dataclass
class HeroDeathResult:
    hero_id: str
    hero_name: str
    party_wiped: bool
    log: list[str] = field(default_factory=list)


def is_alive(hero: dict) -> bool:
    return bool(hero.get("alive", True))


def living_heroes(game_state: dict) -> list[dict]:
    """Every hero still on the board. The set that blocks squares, draws
    Zargon's attention, and can act.
    """
    return [h for h in game_state.get("heroes", []) if is_alive(h)]


def find_living_hero(game_state: dict, hero_id: str) -> dict | None:
    """The acting hero, or None if they're dead or not in this game.
    Callers raise their own module's error so the message fits the
    action being attempted.
    """
    hero = next((h for h in game_state.get("heroes", []) if h["id"] == hero_id), None)
    return hero if hero is not None and is_alive(hero) else None


def record_hero_death(game_state: dict, hero_id: str) -> HeroDeathResult:
    """Marks a hero dead. Raises if they aren't in the game, or are
    already down -- reporting the same death twice is a misclick, not a
    second casualty.
    """
    hero = next((h for h in game_state.get("heroes", []) if h["id"] == hero_id), None)
    if hero is None:
        raise HeroNotFoundError(f"hero '{hero_id}' is not in this game")
    if not is_alive(hero):
        raise HeroAlreadyDeadError(f"{hero.get('name', hero_id)} has already fallen")

    hero["alive"] = False
    name = hero.get("name", hero_id)
    pos = hero.get("pos") or []
    where = f" at [{pos[0]},{pos[1]}]" if len(pos) == 2 else ""

    log = [
        f"{name} falls{where}. Take the figure off the board -- the square is clear, "
        f"and Zargon has one less target."
    ]
    party_wiped = not living_heroes(game_state)
    if party_wiped:
        log.append("The last hero has fallen. The quest is lost -- Zargon holds the dungeon.")

    return HeroDeathResult(hero_id=hero_id, hero_name=name, party_wiped=party_wiped, log=log)
