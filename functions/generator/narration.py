"""Colors one closed turn of the mechanical log with a short flavor
paragraph -- not a summary of the whole game (that's the chronicle), just
this turn's events read as a Dungeon Master would narrate them at the
table.

Same shape as chronicle.py: plain text completion, no retry/validate
loop, and the same model as quest generation (one LLM configuration for
the app's own writing). Fires once per turn, forward from whenever a
game is opened with this feature live -- never backfilled for turns that
closed before the client asked, so an old finished game doesn't fire one
LLM call per historical turn at once (see GameView.tsx's trigger).
"""

from __future__ import annotations

from .client import MODEL

NARRATION_MAX_TOKENS = 300

SYSTEM_PROMPT = """You are Zargon, narrating one turn of a HeroQuest game to the
players at the table, in the 1989 quest-book's own voice: second person,
a little archaic, evocative but not purple.

You will be given a quest's own text (title, backstory) and the
mechanical log lines from ONE turn -- reveals, moves, attacks, defences,
deaths, exactly as they happened.

Write ONE short flavor paragraph (2-4 sentences, roughly 40-80 words)
narrating this turn. Requirements:
- Reference only what the log lines actually say -- don't invent a
  monster, a hit, or an outcome the log doesn't support.
- If the turn was uneventful (a search that found nothing, a move with no
  encounter), a short atmospheric line is fine -- don't manufacture
  drama that didn't happen.
- Plain prose, no headings, no bullet points, no markdown, no turn
  number.
- Output ONLY the paragraph -- no preamble, no quotation marks around
  it."""


def build_narration_prompt(quest: dict, turn: int, lines: list[str]) -> str:
    log_lines = "\n".join(f"- {line}" for line in lines)
    return f"""QUEST
Title: {quest.get('title', '')}
Backstory: {quest.get('backstory', '')}

TURN {turn} LOG
{log_lines}
"""


class NarrationRefused(Exception):
    """The model declined to narrate this turn (safety refusal)."""

    def __init__(self, stop_details):
        self.stop_details = stop_details
        super().__init__(f"LLM refused to narrate this turn: {stop_details}")


class NarrationTruncated(Exception):
    """The response was cut off by max_tokens before it finished."""

    def __init__(self, stop_reason):
        self.stop_reason = stop_reason
        super().__init__(f"narration response truncated (stop_reason={stop_reason})")


def call_turn_narration_llm(client, quest: dict, turn: int, lines: list[str]) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=NARRATION_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_narration_prompt(quest, turn, lines)}],
    )

    if response.stop_reason == "refusal":
        raise NarrationRefused(response.stop_details)
    if response.stop_reason not in ("end_turn", "stop_sequence", None):
        raise NarrationTruncated(response.stop_reason)

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise NarrationRefused(None)
    return text.strip()
