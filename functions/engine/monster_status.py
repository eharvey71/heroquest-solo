"""Spells that hold a MONSTER: Sleep and Tempest.

The mirror of engine/hero_status.py, and deliberately a separate module
because the two sides of the board are not symmetrical. A held HERO is
enforced by refusing their actions and the break roll is the player's
own red dice. A held MONSTER is enforced by Zargon skipping its turn --
and since monster Mind Points are digital (monsters.json), the APP rolls
the break itself, the way it rolls every other Zargon die.

    asleep     Sleep -- "cannot move, attack, or defend itself"
    becalmed   Tempest -- "will miss its next turn"

"Cannot defend itself" is the interesting one: it makes a sleeping
monster roll no defend dice at all against a hero's attack, which is
the difference between a nuisance and a genuinely good card.
"""

from __future__ import annotations

import random

BLOCKING_STATUSES = ("asleep", "becalmed")


def statuses_for(game_state: dict, monster_id: str) -> list[dict]:
    return list(game_state.get("monsterStatus", {}).get(monster_id, []))


def add_status(
    game_state: dict, monster_id: str, *, status: str, spell: str, turn: int, misses_turns: int = 0
) -> dict:
    registry = game_state.setdefault("monsterStatus", {})
    entries = registry.setdefault(monster_id, [])
    for entry in entries:
        if entry.get("status") == status:
            entry["since"] = turn
            if misses_turns:
                entry["missesTurns"] = misses_turns
            return entry
    entry = {"status": status, "spell": spell, "since": turn}
    if misses_turns:
        entry["missesTurns"] = misses_turns
    entries.append(entry)
    return entry


def remove_status(game_state: dict, monster_id: str, status: str) -> bool:
    registry = game_state.get("monsterStatus", {})
    entries = registry.get(monster_id, [])
    remaining = [e for e in entries if e.get("status") != status]
    if len(remaining) == len(entries):
        return False
    if remaining:
        registry[monster_id] = remaining
    else:
        registry.pop(monster_id, None)
    return True


def is_held(game_state: dict, monster_id: str) -> dict | None:
    for entry in statuses_for(game_state, monster_id):
        if entry.get("status") in BLOCKING_STATUSES:
            return entry
    return None


def is_asleep(game_state: dict, monster_id: str) -> bool:
    return any(e.get("status") == "asleep" for e in statuses_for(game_state, monster_id))


def defend_dice_for(game_state: dict, monster_id: str, defend_dice: int) -> int:
    """A sleeping monster "cannot ... defend itself" -- no dice at all."""
    return 0 if is_asleep(game_state, monster_id) else defend_dice


def roll_break_attempts(
    game_state: dict, monster_defs: dict, catalogs, turn: int, rng: random.Random | None = None
) -> list[str]:
    """Zargon's own saving rolls, taken at the top of his turn.

    Sleep: one red die per Mind Point, a 6 frees it. Tempest can't be
    rolled against -- it simply costs the turn it took.
    """
    rng = rng or random
    log: list[str] = []
    registry = game_state.get("monsterStatus", {})

    for monster_id in list(registry):
        for entry in list(registry.get(monster_id, [])):
            status = entry.get("status")
            name = monster_defs.get(monster_id, {}).get("name") or monster_id

            if status == "becalmed":
                if entry.get("since", turn) < turn:
                    remove_status(game_state, monster_id, "becalmed")
                    log.append(f"The whirlwind around {name} dies down.")
                continue

            if status != "asleep":
                continue

            mtype = monster_defs.get(monster_id, {}).get("type")
            mind = catalogs.monsters.get(mtype, {}).get("mind", 1)
            if any(rng.randint(1, 6) == 6 for _ in range(max(1, mind))):
                remove_status(game_state, monster_id, "asleep")
                log.append(f"{name} rolls a 6 among its {mind} Mind Point dice and wakes.")
            else:
                log.append(f"{name} sleeps on -- no 6 among its {mind} Mind Point dice.")
    return log
