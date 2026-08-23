"""Ends the hero phase and hands control to Zargon.

Per CLAUDE.md's Balance system, a lone hero (heroCount == 1) takes 2
actions per turn, compensating for playing without a full party.
Settled granularity: an "action" is a FULL move+action cycle -- the
same thing one hero's turn already means physically. The app doesn't
count individual button presses for 2-4 hero parties (turn structure
inside the hero phase is trusted to the table), so the lone-hero rule
is enforced the same way, one level up: the hero phase runs TWICE
before the phase flips to Zargon, tracked as heroPhaseSegment (1 or
2). The hero rolls fresh movement dice each segment, exactly as if a
second hero were taking a turn.

Roster size at game creation decides lone-hero status (that's what the
quest budget was priced against) -- a 4-hero party whittled down to
one survivor does NOT start getting double turns.
"""

from __future__ import annotations

from dataclasses import dataclass


class NotHeroPhaseError(ValueError):
    """Can't end a turn that isn't currently the hero phase."""


class DefencesPendingError(ValueError):
    """Can't hand off to Zargon with a shield report still outstanding.

    resolve_zargon_turn REPLACES pendingDefenses wholesale on its next
    call, so an unanswered prompt left standing here doesn't wait
    quietly -- it gets silently overwritten the next time Zargon acts,
    and the hit it represented is gone from the record for good. A
    confused click on End Turn used to let exactly that happen.
    """


@dataclass
class EndTurnResult:
    new_phase: str
    new_segment: int
    log: list[str]


def resolve_end_turn(game_state: dict) -> EndTurnResult:
    if game_state.get("phase") != "hero":
        raise NotHeroPhaseError("it is not the hero phase")
    if game_state.get("pendingDefenses"):
        raise DefencesPendingError("report the outstanding defence roll(s) before ending the turn")

    lone_hero = len(game_state.get("heroes", [])) == 1
    # Older game docs predate the field; they behave as segment 1.
    segment = game_state.get("heroPhaseSegment", 1)

    if lone_hero and segment == 1:
        return EndTurnResult(
            new_phase="hero",
            new_segment=2,
            log=["The lone hero presses on -- second action of the turn."],
        )

    return EndTurnResult(new_phase="zargon", new_segment=1, log=["The heroes end their turn."])
