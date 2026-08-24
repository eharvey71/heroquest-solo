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
    contains = defs["furniture"]["properties"]["contains"]
    contains["properties"].pop("trapText", None)
    contains["properties"].pop("artifactId", None)
    contains["properties"]["trap"]["enum"] = ["pit", "falling_block", "none"]
    defs["trap"]["properties"]["type"]["enum"] = ["pit", "falling_block"]
    defs["door"]["properties"]["state"]["enum"] = ["open", "closed", "locked", "secret"]
    s["properties"]["objective"]["properties"]["target"]["properties"].pop("artifactId", None)
    s["properties"].pop("escapeDestination", None)
    return s


def no_spells_enum():
    s = current_schema()
    s["$defs"]["monster"]["properties"]["spells"]["items"] = {"type": "string"}
    return s


TRIVIAL = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


CASES = [
    ("current (as deployed)", current_schema, dict(thinking=True)),
    ("current, no thinking param", current_schema, dict(thinking=False)),
    ("current minus chaos-spells enum", no_spells_enum, dict(thinking=True)),
    ("aug19 last-proven schema", aug19_schema, dict(thinking=True)),
    ("trivial one-field schema", lambda: copy.deepcopy(TRIVIAL), dict(thinking=True)),
]


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("set ANTHROPIC_API_KEY (see module docstring)")
    client = anthropic.Anthropic(api_key=api_key)
    print(f"anthropic SDK {anthropic.__version__}, model {MODEL}\n")

    for name, schema_fn, opts in CASES:
        schema = schema_fn()
        kwargs = dict(
            model=MODEL,
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
