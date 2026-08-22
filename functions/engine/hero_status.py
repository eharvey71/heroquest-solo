"""What a Chaos spell leaves behind on a hero.

Five of the twelve cards don't do damage -- they take the hero out of
the fight for a while (engine/chaos_spells.py). That state has to live
somewhere the app can enforce, because unlike Body Points it isn't a
number on a physical sheet: it decides whether the app accepts the
hero's next move at all.

    asleep      Sleep -- "unable to move, attack, or defend himself"
    paralyzed   Cloud of Chaos -- same, on everyone in the area
    commanded   Command -- Zargon moves the hero instead
    becalmed    Tempest -- "will miss his next turn"
    afraid      Fear -- attacks drop to one combat die

The first four stop a hero acting. `afraid` does not: the hero still
takes their turn, they just roll one die, and since hero attack dice are
physical the app can only remind them.

Breaking a spell is the hero's own red dice against their own Mind
Points, both physical, so the app never rolls it: it asks for the roll
and the player reports whether a 6 came up. Tempest can't be broken at
all -- it simply expires once the missed turn has passed.
"""

from __future__ import annotations

# Statuses that stop a hero taking their turn.
BLOCKING_STATUSES = ("asleep", "paralyzed", "commanded", "becalmed")

BLOCKED_REASON = {
    "asleep": "is asleep -- no moving, attacking or defending until the spell is broken",
    "paralyzed": "is paralyzed by the Cloud of Chaos -- no moving, attacking or defending until it breaks",
    "commanded": "is under Zargon's command -- Zargon moves them, not you",
    "becalmed": "is caught in the Tempest and misses this turn",
}


class SpellNotOnHeroError(ValueError):
    """That hero isn't under that spell."""


class SpellCannotBeBrokenError(ValueError):
    """Tempest has no saving roll -- it just expires."""


def statuses_for(game_state: dict, hero_id: str) -> list[dict]:
    return list(game_state.get("heroStatus", {}).get(hero_id, []))


def add_status(game_state: dict, hero_id: str, *, status: str, spell: str, turn: int, misses_turns: int = 0) -> dict:
    """Applies a status, or refreshes one the hero already has (a second
    Sleep doesn't stack into two spells to break).
    """
    registry = game_state.setdefault("heroStatus", {})
    existing = registry.setdefault(hero_id, [])
    for entry in existing:
        if entry.get("status") == status:
            entry["since"] = turn
            if misses_turns:
                entry["missesTurns"] = misses_turns
            return entry
    entry = {"status": status, "spell": spell, "since": turn}
    if misses_turns:
        entry["missesTurns"] = misses_turns
    existing.append(entry)
    return entry


def remove_status(game_state: dict, hero_id: str, status: str) -> bool:
    registry = game_state.get("heroStatus", {})
    entries = registry.get(hero_id, [])
    remaining = [e for e in entries if e.get("status") != status]
    if len(remaining) == len(entries):
        return False
    if remaining:
        registry[hero_id] = remaining
    else:
        registry.pop(hero_id, None)
    return True


def blocking_status(game_state: dict, hero_id: str) -> dict | None:
    """The status stopping this hero from acting, if any."""
    for entry in statuses_for(game_state, hero_id):
        if entry.get("status") in BLOCKING_STATUSES:
            return entry
    return None


def blocked_message(hero_name: str, entry: dict) -> str:
    return f"{hero_name} {BLOCKED_REASON.get(entry.get('status'), 'cannot act')}."


def is_afraid(game_state: dict, hero_id: str) -> bool:
    return any(e.get("status") == "afraid" for e in statuses_for(game_state, hero_id))


def attempt_break(game_state: dict, hero_id: str, hero_name: str, rolled_six: bool) -> tuple[bool, list[str]]:
    """The hero has rolled one red die per Mind Point and reports whether
    a 6 came up. Breaks every breakable spell on them at once? No -- one
    attempt, one spell: the cards are separate, so the FIRST breakable
    status is the one being rolled against.
    """
    entries = statuses_for(game_state, hero_id)
    breakable = [e for e in entries if e.get("status") in BLOCKING_STATUSES + ("afraid",) and e.get("status") != "becalmed"]
    if not breakable:
        raise SpellNotOnHeroError(f"{hero_name} is not under a spell that can be broken")

    entry = breakable[0]
    if not rolled_six:
        return False, [f"{hero_name} strains against the spell and fails -- no 6 among their Mind Point dice."]

    remove_status(game_state, hero_id, entry["status"])
    return True, [f"{hero_name} rolls a 6 and breaks free of {entry.get('spell', 'the spell')}."]


def expire_turn_statuses(game_state: dict, turn: int) -> list[str]:
    """Counts down the statuses that wear off by themselves (Tempest).

    Called when the hero phase ends: the hero has now missed the turn the
    card took from them.
    """
    log: list[str] = []
    registry = game_state.get("heroStatus", {})
    for hero_id in list(registry):
        remaining = []
        for entry in registry[hero_id]:
            if entry.get("missesTurns"):
                # Only counts down once the turn it landed on has passed.
                if entry.get("since", turn) < turn or entry.get("counted"):
                    entry["missesTurns"] = int(entry["missesTurns"]) - 1
                else:
                    entry["counted"] = True
                if entry["missesTurns"] <= 0:
                    log.append(f"The whirlwind around {hero_id} dies down -- they may act again next turn.")
                    continue
            remaining.append(entry)
        if remaining:
            registry[hero_id] = remaining
        else:
            registry.pop(hero_id, None)
    return log
