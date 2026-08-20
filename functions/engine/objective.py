"""Detects whether the quest's objective has been completed, and
whether the party has since made it home.

Completing the objective is NOT the end of the quest. "To safely
complete a Quest, you must return to the stairway, for it is only
there that you are truly free from harm" (1989 rulebook, Hero
Movement). So the quest runs in two stages: the objective is met, and
then a hero has to walk back.

Who has to get back is a judgement call the app can't fully make: hero
death is physical (CLAUDE.md's boundary), so the app never knows who
survived and "all surviving heroes" isn't computable. ANY hero
reaching the stairway ends the quest -- it needs no extra state and no
extra typing mid-game. Tighten it only if hero death ever becomes
digital.

The four objective.type values (design/quest-schema.md) resolve to
exactly two digitally-verifiable triggers -- confirmed against real
generated quests, not guessed from the schema alone (the schema and
generator prompt give no per-type guidance on what `target` contains):

- kill_boss: target.monsterId's monster is no longer alive. Body
  points/alive are digital state (CLAUDE.md's boundary), so this is
  directly checkable.
- find_artifact / rescue / reach_exit: a hero has reached target.room
  (it's in game_state.revealed.rooms). Real generated quests for all
  three types only ever populate target.room -- there's no NPC or
  artifact entity anywhere in the schema, and treasure/NPC CONTENTS
  are physical-only per CLAUDE.md's boundary, so "the artifact was
  found" or "the captive was freed" can never be digitally confirmed
  beyond "the room was reached." That's the correct, and only
  verifiable, proxy for these three types.
"""

from __future__ import annotations

from .heroes import living_heroes


def check_objective_complete(quest: dict, game_state: dict) -> bool:
    objective = quest.get("objective", {})
    target = objective.get("target", {})

    if objective.get("type") == "kill_boss":
        monster_id = target.get("monsterId")
        if not monster_id:
            return False
        monster_state = game_state.get("monsters", {}).get(monster_id)
        return monster_state is not None and not monster_state.get("alive", True)

    room = target.get("room")
    if not room:
        return False
    return room in game_state.get("revealed", {}).get("rooms", [])


def _stairway_squares(quest: dict) -> set:
    pos = quest.get("stairway", {}).get("pos")
    if not pos:
        return set()
    x, y = pos
    return {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}


def hero_on_stairway(quest: dict, game_state: dict) -> bool:
    """Is any hero standing on the stairway's 2x2 footprint?"""
    squares = _stairway_squares(quest)
    if not squares:
        return False
    return any(tuple(h["pos"]) in squares for h in living_heroes(game_state))
