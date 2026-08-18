"""Ends the hero phase and hands control to Zargon.

Per CLAUDE.md's Balance system, a lone hero (heroCount == 1) is meant
to take 2 actions per turn before ending it, compensating for playing
without a full party. NOT enforced here: "action" isn't defined at the
granularity this needs (a full move+act cycle, same as a normal
4-hero turn? any single button press?), and instrumenting a counter
around the wrong definition means rebuilding it. Flagged rather than
guessed -- see functions/main.py's module docstring for the open gap.
"""

from __future__ import annotations

from dataclasses import dataclass


class NotHeroPhaseError(ValueError):
    """Can't end a turn that isn't currently the hero phase."""


@dataclass
class EndTurnResult:
    new_phase: str
    log: list[str]


def resolve_end_turn(game_state: dict) -> EndTurnResult:
    if game_state.get("phase") != "hero":
        raise NotHeroPhaseError("it is not the hero phase")
    return EndTurnResult(new_phase="zargon", log=["The heroes end their turn."])
