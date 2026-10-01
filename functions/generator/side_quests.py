"""The second model call of an expanded quest: writes the side quests
from a quest that has already validated (design/side-quests-design.md
section 10). Its own schema, its own retry loop, and a failure here
never costs the quest -- main.generate_quest saves the quest without
side quests (and without the gate) if this can't produce a valid set.

The model writes prose and a choice graph. Every choice ends in an
effect from engine/side_quests.py's closed list; validator/side_quests
is the gate that decides whether what came back is playable.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from validator.catalogs import Catalogs
from validator.side_quests import (
    MAX_DEPTH,
    MAX_NODES,
    MAX_PASSAGE_WORDS,
    MIN_NODES,
    OPTIONAL_BEST_MAX,
    REQUIRED_EXTRA_MAX,
    WORST_MIN,
    check_side_quests,
)
from engine.side_quests import ARMORY_REMINDER, ELEMENTS, HERO_IDS, REWARD_POINTS, SETTINGS

from .client import MAX_TOKENS, QuestGenerationMalformed, QuestGenerationTruncated, call_llm_raw
from .core import MALFORMED_RETRY_HINT, MAX_ATTEMPTS, notify, summarize_errors
from .prompt import build_retry_message
from .side_quest_schema import build_side_quest_json_schema, to_canonical_side_quests

REQUIRED_SIDE_QUEST_CHANCE = 1 / 3  # owner's call, design section 15
# Same budget as the quest call, for the same reason: adaptive thinking
# at high effort draws from it too, and the call streams. 9000 (set
# before streaming existed) cut off all three attempts of the first
# live expanded quest.
SIDE_QUEST_MAX_TOKENS = MAX_TOKENS
TRUNCATED_USER_MESSAGE = "the scenes were cut off by the length limit"
MALFORMED_USER_MESSAGE = "the answer wasn't valid JSON"

TRUNCATION_HINT = (
    "the previous response was cut off by the token limit before completing valid JSON -- "
    "return shorter scenes (fewer passages, shorter text)"
)


@dataclass
class SideQuestGenerationResult:
    side_quests: list
    attempts: int
    warnings: list = field(default_factory=list)


class SideQuestGenerationFailed(Exception):
    def __init__(self, errors: list, attempts: int):
        self.errors = errors
        self.attempts = attempts
        super().__init__(f"side quest generation failed after {attempts} attempts: {errors}")


def roll_required(rng: random.Random | None = None) -> bool:
    """The server's coin, rolled BEFORE the main quest prompt is built so
    the backstory can plant the ward or seal (generator/prompt.py's
    _side_quest_section). Never the model's decision."""
    return (rng or random.Random()).random() < REQUIRED_SIDE_QUEST_CHANCE


def build_gate_spec(quest: dict) -> dict | None:
    """What the required scene holds shut, from the validated quest's
    objective: a warded boss for kill_boss, a sealed goal room for the
    rest. None if the objective names neither (nothing to gate)."""
    objective = quest.get("objective", {})
    target = objective.get("target", {})
    if objective.get("type") == "kill_boss" and target.get("monsterId"):
        mid = target["monsterId"]
        name = mid
        for room in quest.get("rooms", {}).values():
            for m in room.get("monsters", []):
                if m.get("id") == mid:
                    name = m.get("name") or m.get("type", mid)
        return {"kind": "ward", "targetMonsterId": mid, "targetName": name}
    if target.get("room"):
        return {"kind": "seal", "targetRoom": target["room"]}
    return None


def _quest_context(quest: dict, params: dict) -> str:
    rooms = []
    for room_id, room in quest.get("rooms", {}).items():
        monsters = [
            f"{m.get('id')} = {m.get('name') or m.get('type')} ({m.get('type')})" for m in room.get("monsters", [])
        ]
        pieces = [f.get("type") for f in room.get("furniture", [])]
        traps = [t.get("type") for t in room.get("traps", [])]
        rooms.append(
            f"- {room_id}: {room.get('revealText', '').strip()} | monsters: {', '.join(monsters) or 'none'}"
            f" | furniture: {', '.join(pieces) or 'none'} | traps: {len(traps)}"
        )
    artifacts_placed = []
    aid = quest.get("objective", {}).get("target", {}).get("artifactId")
    if aid:
        artifacts_placed.append(aid)
    for room in quest.get("rooms", {}).values():
        for piece in room.get("furniture", []):
            a = (piece.get("contains") or {}).get("artifactId")
            if a:
                artifacts_placed.append(a)
    return f"""QUEST
Title: {quest.get('title', '')}
Backstory: {quest.get('backstory', '')}
Objective ({quest.get('objective', {}).get('type', '')}): {quest.get('objective', {}).get('description', '')}
Completion text: {quest.get('completionText', '')}
Hero count: {params.get('heroCount')}
Stairway room: {quest.get('stairway', {}).get('room')}
Wandering monster: {quest.get('wanderingMonster')}
Artifacts already placed in this quest (never grant these): {', '.join(artifacts_placed) or 'none'}

POPULATED ROOMS (id: reveal text | monsters | furniture | traps)
{chr(10).join(rooms)}
"""


def build_side_quest_system_prompt(catalogs: Catalogs, gate: dict | None) -> str:
    artifact_lines = "\n".join(
        f"- {aid}: {card.get('name', aid)} -- {card.get('text', '')}" for aid, card in sorted(catalogs.artifacts.items())
    )
    gate_lines = ""
    if gate:
        if gate["kind"] == "ward":
            gate_lines = f"""
### THE REQUIRED SIDE QUEST (the server rolled one this time)
Exactly ONE of your side quests has kind "required". Its job: it is the
deed that breaks the WARD on {gate.get('targetName')} (monster id
{gate.get('targetMonsterId')}) -- until it is done the heroes' blows
and spells cannot harm that villain. The quest's backstory already
hints at this; you invent the specifics (what the ward is, who knows
how to break it, what must be done). Write gateText: one or two
sentences the app shows the party when a blow turns aside, saying why.
Its success terminals MUST include the effect break_gate; its failure
and partial terminals include crack_gate (the ward weakens instead of
breaking -- the villain becomes hittable but tougher). Never give a
required scene an ending that leaves the quest unwinnable.
"""
        else:
            gate_lines = f"""
### THE REQUIRED SIDE QUEST (the server rolled one this time)
Exactly ONE of your side quests has kind "required". Its job: it is the
deed that lifts the SEAL on the quest's goal (the room {gate.get('targetRoom')})
-- until it is done, reaching the goal completes nothing. The quest's
backstory already hints at this; you invent the specifics. Write
gateText: one or two sentences the app shows the party when they reach
the sealed goal, saying why it holds. Its success terminals MUST include
the effect break_gate; its failure and partial terminals include
crack_gate (the seal cracks: the goal can be forced at a cost). Never
give a required scene an ending that leaves the quest unwinnable.
"""
    else:
        gate_lines = """
### NO REQUIRED SIDE QUEST THIS TIME
Every side quest has kind "optional". Do not use break_gate or
crack_gate, and do not write gateText (set it to "").
"""
    reward_prices = ", ".join(f"{k} {v}" for k, v in REWARD_POINTS.items())
    return f"""You are the quest-book writer for the 1989 North American edition of
HeroQuest, adding SIDE QUESTS to a quest that already exists. A side
quest is a short branching scene the players read and play in the app
in 10-15 minutes: five to ten short passages, two or three choices
each, a die roll or two, one decision that matters, then back to the
dungeon. The board does not move while it plays; the story leaves the
dungeon and comes back. Voice: the quest book's -- second person, a
little archaic, evocative but not purple.

Write 1-2 OPTIONAL side quests{' plus the 1 REQUIRED one described below' if gate else ''}.
Each must grow out of THIS quest's backstory, villain, rooms and
monsters -- a thread of the same story, never a generic errand.
{gate_lines}
### WHERE A SCENE HAPPENS
setting is one of {list(SETTINGS)}. Town, forest, cave, shrine, road
are places the party reaches in the fiction (a stair to the surface, a
crawlway, a hidden chapel, a memory of the road in); vision is a dream
or sending. ONLY a town scene mentions the Armory: every terminal of a
town scene includes the effect armory_visit (the app then shows this
reminder: "{ARMORY_REMINDER}"). Every other setting rewards the party
with something FOUND -- an Artifact card, or an announced piece of
equipment, potion, purse of gold -- never a shop.

### HOW A SCENE IS OFFERED (hook)
hook.when "prologue": offered at game start, before the first move --
the road in, a tavern rumour, a messenger. hook.room "".
hook.when "room": offered when that room is revealed, by someone or
something IN it -- an old prisoner, a shrine, a body with a letter, a
whispering idol. hook.room is one of the quest's populated room ids;
hook.npcName names the figure (or "" for a thing), hook.figureHint
says what spare miniature could stand in ("any robed figure"). A
required scene's hook must be met BEFORE the objective room -- a room
fewer doors from the stairway than the objective's, or the prologue.
hook.text: 1-3 sentences, read aloud, offering the scene.

### PASSAGES AND CHOICES
- {MIN_NODES}-{MAX_NODES} nodes in total (passages + terminals), the longest
  route at most {MAX_DEPTH} passages deep. Passage text 60-{MAX_PASSAGE_WORDS} words.
- Each passage has 2-3 choices. A choice either has "next" (a passage
  or terminal id, and test.kind "none") or a "test" (and next "").
- Tests, on the app's terms (the app never learns hero stats):
  combat_dice: the hero rolls `dice` (1-3) combat dice at the table
  and reports skulls; `needSkulls` or more succeeds. mind / body: the
  hero rolls a red die against their own Mind or Body Points and
  reports pass or fail (dice/needSkulls 0). zargon: the app itself
  rolls `dice` combat dice (a guardian's swing, a trap's spring) and
  succeeds on `needSkulls`. Each test names a success and a failure
  node.
- A choice may be reserved with requiresHero ({list(HERO_IDS)}),
  requiresElement ({list(ELEMENTS)}: shown only if a caster in the
  party still holds an unspent card of that element), or requiresFlag
  (a flag an earlier choice set with setsFlag). Use "" for none. EVERY
  passage keeps at least one choice with no requirement, and a success
  ending must be reachable through unrequired choices alone.
- No loops, except at most ONE declared retry: retry.from/retry.to name
  an edge some choice already takes backwards (a failed test tried
  again), and retry.costText says what the second attempt costs ("The
  second climb costs you 1 Body Point"). The app offers it once. If no
  retry, set from/to/costText to "".
- terminals: each has outcome success | partial | failure, epilogue
  text (40-100 words) and an effects list. A required scene needs at
  least one success terminal reachable through unrequired choices.

### EFFECTS (the only things a choice can do -- the app applies them)
App-owned, really applied:
- grant_artifact {{artifactId, heroId or ""}} -- 3 points. The physical card is
  handed over. Cards:
{artifact_lines}
- weaken_monster {{monsterId, stat: body|defend}} -- 2 points. A named foe of this quest.
- remove_monster {{monsterId}} -- an ally slays it, it deserts. Never the objective's boss.
- reveal_traps {{room}} / reveal_secret_doors {{room}} -- 1 point each.
- spawn_wandering -- -1 point: the quest's wandering monster picks up the trail.
- miss_turn {{heroId or ""}} -- -1 point: a hero is left reeling for a turn.
Announced (the player applies them at the table):
- announce_reward {{kind: gold|potion|equipment|body, text}} -- points: {reward_prices}.
  text says exactly what: "Old Hessa presses 50 gold into your hand."
- announce_cost {{kind: body|gold, text}} -- -1 point: "The thorns take 1 Body Point from each hero."
- armory_visit -- town scenes only, every terminal.
- break_gate / crack_gate -- the required scene only (see above).
Caps: an optional scene's best terminal totals at most {OPTIONAL_BEST_MAX} points
and its worst at least {WORST_MIN}; a required scene's success carries at
most {REQUIRED_EXTRA_MAX} points on top of break_gate. Unused effect fields are "".

### PROSE RULES
- Never print a room id (R7), a square coordinate ([14,9]), a monster
  or trap id (M3, R2-T1) in any text the players read -- titles,
  passages, labels, terminals, hook text, gateText. Say "the crypt
  beyond", "the eastern chamber". Ids go ONLY in the id fields.
- Never state hero Body Points, gold or inventory as numbers the app
  knows; the app doesn't. "You feel weaker" plus an announce effect.
- Plain prose, no markdown inside strings.

### OUTPUT
Return ONE JSON object {{"sideQuests": [...]}} matching the schema you
were given, no markdown, no commentary."""


def generate_side_quests(
    quest: dict, params: dict, client, catalogs: Catalogs, gate: dict | None, on_progress=None
) -> SideQuestGenerationResult:
    """Retries with the validator's errors like generate_quest does.
    Raises SideQuestGenerationFailed when no attempt validates; the
    caller decides that means "the quest stays playable as traditional".
    `on_progress` as in core.generate_quest."""
    schema = build_side_quest_json_schema(catalogs, quest)
    system_prompt = build_side_quest_system_prompt(catalogs, gate)
    message = _quest_context(quest, params)
    what = "one or two optional scenes plus the required one" if gate else "one or two optional scenes"
    # `last_errors` is what the model is told (retry hints); `last_reason`
    # is what the player is told -- on the status line while the next
    # attempt runs, and stored on the quest if every attempt fails.
    last_errors = ["no attempt completed"]
    last_reason = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        after = f" (attempt {attempt - 1}: {last_reason})" if last_reason else ""
        notify(
            on_progress,
            "writing_side_quests",
            f"Writing the side quests -- attempt {attempt} of {MAX_ATTEMPTS}{after}: {what}. Another 1-2 minutes.",
        )
        try:
            payload = call_llm_raw(client, system_prompt, message, schema, max_tokens=SIDE_QUEST_MAX_TOKENS)
        except QuestGenerationTruncated:
            last_errors = [TRUNCATION_HINT]
            last_reason = TRUNCATED_USER_MESSAGE
            message = build_retry_message(last_errors)
            notify(on_progress, "retrying_side_quests", f"Attempt {attempt}: {last_reason}. Asking for shorter ones.")
            continue
        except QuestGenerationMalformed:
            last_errors = [MALFORMED_RETRY_HINT]
            last_reason = MALFORMED_USER_MESSAGE
            message = build_retry_message(last_errors)
            notify(on_progress, "retrying_side_quests", f"Attempt {attempt}: {last_reason}. Asking again.")
            continue

        notify(on_progress, "validating_side_quests", "Checking the scenes: every path ends, no dead ends, rewards within caps, no ids in the prose.")
        side_quests = to_canonical_side_quests(payload if isinstance(payload, dict) else {})
        errors = check_side_quests(side_quests, quest, catalogs, required_gate=gate)
        if not errors:
            return SideQuestGenerationResult(side_quests=side_quests, attempts=attempt)
        last_errors = errors
        last_reason = f"failed {len(errors)} check(s): {summarize_errors(errors)}"
        message = build_retry_message(last_errors)
        notify(on_progress, "retrying_side_quests", f"Attempt {attempt}: the scenes {last_reason}. Asking for a fix.")

    # Validator errors are readable as they are; a cutoff or bad JSON
    # stores the player's sentence, not the hint written for the model.
    stored = last_errors if last_errors not in ([TRUNCATION_HINT], [MALFORMED_RETRY_HINT]) else [f"{last_reason} on every attempt"]
    raise SideQuestGenerationFailed(errors=stored, attempts=MAX_ATTEMPTS)


def required_side_quest(side_quests: list) -> dict | None:
    return next((sq for sq in side_quests if sq.get("kind") == "required"), None)


def describe_for_log(side_quests: list) -> str:
    return json.dumps([{"id": sq.get("id"), "kind": sq.get("kind"), "title": sq.get("title")} for sq in side_quests])
