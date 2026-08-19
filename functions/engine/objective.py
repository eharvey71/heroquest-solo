"""Detects whether the quest's objective has been completed.

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
