"""Reproduce/bisect the structured-outputs "compiled grammar is too
large" 400 against the live API, outside of Cloud Functions entirely.

Run from functions/ with the venv active (or any python that has the
pinned anthropic==0.123.0):

    ANTHROPIC_API_KEY=$(firebase functions:secrets:access ANTHROPIC_API_KEY) \
        python tools/repro_grammar.py

Each case sends the same request shape generator/client.py sends
(model, thinking, output_config) with a tiny prompt. A case that trips
the grammar compiler is rejected before generation (costs nothing); a
case that passes generates ~64 tokens (~half a cent). What the matrix
tells us:

- "current" FAILS here too -> the bug is the schema/model/server
  combination itself; the bisect rows then say which part.
- "current" PASSES here -> the deployed function is NOT running this
  code/these dependency versions, and the deploy pipeline is the bug.
- "trivial" FAILS -> structured outputs on this model is broken
  server-side, full stop; nothing in our schema matters.
"""

import copy
import json
import os
import sys

import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator.client import MAX_TOKENS, MODEL  # noqa: E402
from generator.schema import build_quest_json_schema  # noqa: E402
from validator.catalogs import load_catalogs  # noqa: E402


def current_schema():
    return build_quest_json_schema(load_catalogs())


def aug19_schema():
    """The last schema PROVEN against the live API (quests generated
    Aug 19). Reconstructed by stripping everything added since."""
    s = current_schema()
    defs = s["$defs"]
    defs["monster"]["properties"].pop("spells", None)
    defs["monster"]["required"] = ["id", "type", "pos"]
    contains = defs["furniture"]["properties"]["contains"]
    contains["properties"].pop("trapText", None)
    contains["properties"].pop("artifactId", None)
    contains["properties"]["trap"]["enum"] = ["pit", "falling_block", "none"]
    contains["required"] = ["trap", "treasure"]
    defs["trap"]["properties"]["type"]["enum"] = ["pit", "falling_block"]
    defs["door"]["properties"]["state"]["enum"] = ["open", "closed", "locked", "secret"]
    s["properties"]["objective"]["properties"]["target"]["properties"].pop("artifactId", None)
    s["properties"].pop("escapeDestination", None)
    s["required"] = [r for r in s["required"] if r not in ("escapeDestination", "corridorTraps")]
    return s


def pre_fix_schema():
    """The 15-optional shape that was failing before the
    required-with-sentinel conversion -- kept as the FAIL anchor."""
    s = current_schema()
    s["$defs"]["monster"]["required"] = ["id", "type", "pos"]
    s["$defs"]["furniture"]["properties"]["contains"]["required"] = ["trap", "treasure"]
    s["required"] = [r for r in s["required"] if r not in ("escapeDestination", "corridorTraps")]
    return s


def aug19_plus_spells_enum():
    s = aug19_schema()
    from engine.chaos_spells import spell_ids
    s["$defs"]["monster"]["properties"]["spells"] = {
        "type": "array",
        "items": {"type": "string", "enum": spell_ids()},
    }
    s["$defs"]["monster"]["required"] = ["id", "type", "spells", "pos"]
    return s


def aug19_plus_spells_plain():
    s = aug19_schema()
    s["$defs"]["monster"]["properties"]["spells"] = {"type": "array", "items": {"type": "string"}}
    s["$defs"]["monster"]["required"] = ["id", "type", "spells", "pos"]
    return s


def aug19_plus_traptext():
    s = aug19_schema()
    contains = s["$defs"]["furniture"]["properties"]["contains"]
    contains["properties"]["trapText"] = {"type": "string"}
    contains["properties"]["trap"]["enum"] = ["chest_trap", "pit", "falling_block", "none"]
    contains["required"] = ["trap", "trapText", "treasure"]
    s["$defs"]["trap"]["properties"]["type"]["enum"] = ["pit", "falling_block", "spear"]
    return s


def aug19_plus_artifacts():
    s = aug19_schema()
    s["$defs"]["furniture"]["properties"]["contains"]["properties"]["artifactId"] = {"type": "string"}
    s["properties"]["objective"]["properties"]["target"]["properties"]["artifactId"] = {"type": "string"}
    return s


def aug19_plus_escape():
    s = aug19_schema()
    s["properties"]["escapeDestination"] = {"type": "array", "items": {"type": "integer"}}
    s["required"] = s["required"] + ["escapeDestination", "corridorTraps"]
    return s


def fixed_minus_spells_enum():
    """The full current schema, but chaos-spell ids as plain strings --
    the candidate final fix if the spells enum is the culprit."""
    s = current_schema()
    s["$defs"]["monster"]["properties"]["spells"]["items"] = {"type": "string"}
    return s


def current_minus_room_enums():
    """Current schema with the two 22-value room-id enums as plain
    strings (the validator's geometry checks already reject unknown
    room ids)."""
    s = current_schema()
    s["$defs"]["room"]["properties"]["roomId"] = {"type": "string"}
    s["$defs"]["targetRoomId"] = {"type": "string"}
    return s


def current_minus_all_big_enums():
    """Current schema with every catalog-sized enum (room ids, monster
    types, wandering monster, furniture types, chaos spells) as plain
    strings -- keeps only the small closed-set enums (door state, trap
    type, orientation, objective type). The validator rejects unknown
    values for every one of these inside the repair loop."""
    s = current_minus_room_enums()
    s["$defs"]["monster"]["properties"]["type"] = {"type": "string"}
    s["$defs"]["monster"]["properties"]["spells"]["items"] = {"type": "string"}
    s["$defs"]["furniture"]["properties"]["type"] = {"type": "string"}
    s["properties"]["wanderingMonster"] = {"type": "string"}
    return s


TRIVIAL = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


# Round 3: round 2 proved the aug19 schema sits at ~100% of
# claude-opus-4-8's grammar budget -- EVERY addition fails, even two
# plain strings -- so the fix is either real headroom (drop the big
# enums) or a model whose compiler has a bigger budget. `model` of None
# means generator/client.py's MODEL.
CASES = [
    ("current schema on claude-opus-5", current_schema, dict(thinking=True, model="claude-opus-5")),
    ("current schema on claude-sonnet-5", current_schema, dict(thinking=True, model="claude-sonnet-5")),
    ("current minus room-id enums (opus-4-8)", current_minus_room_enums, dict(thinking=True)),
    ("current minus ALL big enums (opus-4-8)", current_minus_all_big_enums, dict(thinking=True)),
    ("aug19 PASS anchor (opus-4-8)", aug19_schema, dict(thinking=True)),
]


def run_full_generation(client):
    """One real end-to-end generation through the ACTUAL pipeline
    (prompt-embedded schema, tolerant parse, validate + repair loop) --
    everything the deployed function does except the Firestore write.
    Costs one real generation (~a few cents to tens of cents)."""
    from generator.core import generate_quest

    result = generate_quest(
        {"heroCount": 2, "difficulty": "standard", "size": "short"},
        client,
        load_catalogs(),
    )
    q = result.quest
    print(f"PASS  full generation in {result.attempts} attempt(s)")
    print(f"      title: {q.get('title')!r}")
    print(f"      rooms populated: {sorted(q.get('rooms', {}).keys())}")
    print(f"      warnings: {result.validation.warnings or 'none'}")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("set ANTHROPIC_API_KEY (see module docstring)")
    client = anthropic.Anthropic(api_key=api_key)
    print(f"anthropic SDK {anthropic.__version__}, model {MODEL}\n")

    if "--full" in sys.argv:
        run_full_generation(client)
        return

    for name, schema_fn, opts in CASES:
        schema = schema_fn()
        kwargs = dict(
            model=opts.get("model") or MODEL,
            # Truncation is fine -- we only care whether the request is
            # ACCEPTED (grammar compiled) or 400-rejected.
            max_tokens=64,
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": schema},
            },
            system="You emit one minimal valid object.",
            messages=[{"role": "user", "content": "Emit an object."}],
        )
        if opts["thinking"]:
            kwargs["thinking"] = {"type": "adaptive"}
        size = len(json.dumps(schema))
        try:
            r = client.messages.create(**kwargs)
            print(f"PASS  {name}  ({size}B schema, stop_reason={r.stop_reason})")
        except anthropic.BadRequestError as e:
            msg = str(e)
            short = "GRAMMAR-TOO-LARGE" if "grammar is too large" in msg else msg[:160]
            print(f"FAIL  {name}  ({size}B schema): {short}")
        except Exception as e:  # noqa: BLE001 -- report anything else verbatim
            print(f"ERR   {name}  ({size}B schema): {type(e).__name__}: {str(e)[:160]}")

    # MAX_TOKENS imported to keep this file honest about what production
    # sends; the tiny value above is deliberate for the repro.
    _ = MAX_TOKENS


if __name__ == "__main__":
    main()
