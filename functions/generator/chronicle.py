"""Turns a finished game's mechanical log into read-aloud prose -- the
"what happened" record for one playthrough of a quest.

Deliberately NOT the structured-outputs path generator/client.py uses
for quest generation: a chronicle is prose, not schema-constrained data,
so this is a plain text completion. No retry/validate loop either --
there's no hard-constraint failure a chronicle can have the way a quest
can fail reachability or budget, so a truncated or refused response is
just reported, not retried.

Model choice matches generator/client.py's MODEL rather than picking a
new one -- one LLM configuration for the app's own writing, not two to
keep in sync.
"""

from __future__ import annotations

from .client import MODEL

CHRONICLE_MAX_TOKENS = 1200

SYSTEM_PROMPT = """You are the chronicler for a HeroQuest campaign, writing in the
1989 quest-book's own voice -- the same register as a quest's backstory and
completion text: second person, a little archaic, evocative but not
purple.

You will be given a quest's own text (title, backstory, objective,
completion text) and the mechanical turn log from one playthrough --
every reveal, attack, defence, death, and outcome, exactly as it happened.

Write a SINGLE chronicle entry: one page of read-aloud prose (roughly
150-300 words) telling the story of this playthrough as a campaign
record. Requirements:
- Open by naming the quest and its outcome (the party triumphed, or
  fell).
- Reference what actually happened in the log: named monsters
  defeated or that defeated a hero, whether any hero fell (and if the
  log doesn't say a hero fell, don't invent one), anything the
  completion text says was recovered or accomplished.
- If the log or completion text names an artifact recovered, treat it
  as a real, ongoing fact -- future quests may reference this
  character carrying it.
- Do NOT invent mechanical details the log doesn't support (extra
  monsters, a different outcome, artifacts never mentioned). You may
  invent atmosphere and flavor, never facts.
- The log carries the app's own bookkeeping labels for your eyes only
  -- room ids (R16), square coordinates ([14,9]), trap/monster ids
  (R2-T1, W1), turn markers. NEVER print one of these verbatim. Turn
  them into narrative language instead: "the room beyond", "a deeper
  chamber", "the crypt's heart". The player reads this over a physical
  board with no room numbers on it -- a label from the log means
  nothing to them and breaks the voice.
- Plain prose, no headings, no bullet points, no markdown.
- Output ONLY the chronicle text -- no preamble, no title line, no
  quotation marks around it."""


def build_chronicle_prompt(quest: dict, game: dict) -> str:
    heroes = game.get("heroes", [])
    roster_lines = "\n".join(
        f"- {h.get('name', h.get('id'))}: {'fell in battle' if h.get('alive') is False else 'survived'}"
        for h in heroes
    )
    log_lines = "\n".join(f"[{e.get('turn', 0)}] {e.get('text', '')}" for e in game.get("log", []))
    outcome = "victory" if game.get("status") == "complete" else "defeat"

    return f"""QUEST
Title: {quest.get('title', '')}
Backstory: {quest.get('backstory', '')}
Objective: {quest.get('objective', {}).get('description', '')}
Completion text: {quest.get('completionText', '')}

OUTCOME: {outcome}

HEROES
{roster_lines}

TURN LOG
{log_lines}
"""


class ChronicleRefused(Exception):
    """The model declined to write a chronicle (safety refusal)."""

    def __init__(self, stop_details):
        self.stop_details = stop_details
        super().__init__(f"LLM refused to write a chronicle: {stop_details}")


class ChronicleTruncated(Exception):
    """The response was cut off by max_tokens before it finished."""

    def __init__(self, stop_reason):
        self.stop_reason = stop_reason
        super().__init__(f"chronicle response truncated (stop_reason={stop_reason})")


def call_chronicle_llm(client, quest: dict, game: dict) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=CHRONICLE_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_chronicle_prompt(quest, game)}],
    )

    if response.stop_reason == "refusal":
        raise ChronicleRefused(response.stop_details)
    if response.stop_reason not in ("end_turn", "stop_sequence", None):
        raise ChronicleTruncated(response.stop_reason)

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise ChronicleRefused(None)
    return text.strip()
