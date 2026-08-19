"""Entry point: validate_quest() runs every check and returns one
ValidationResult. See design/quest-generator-design.md section 4
"Generation pipeline" — this is the VALIDATE step, called on parsed LLM
output before a quest reaches Firestore.
"""

from __future__ import annotations

from .balance import check_balance
from .catalogs import Catalogs, load_catalogs
from .geometry import check_geometry
from .narrative import check_narrative
from .reachability import check_reachability
from .result import ValidationResult


def validate_quest(quest: dict, params: dict, catalogs: Catalogs | None = None) -> ValidationResult:
    """params: {"heroCount": 1-4, "difficulty": "standard"|"hard",
    "size": "short"|"full"} — the same generation params used to build
    the prompt, needed here because budget/depth targets depend on them.
    Optional "stairwayRoom": the room generator.prompt.pick_stairway_room
    pre-selected and handed to the model as a hard constraint (fixing the
    model's strong prior toward always picking the same room) -- checked
    here so a model that ignores the constraint gets rejected and retried
    like any other hard-constraint violation, rather than silently
    landing wherever the model wanted.
    """
    catalogs = catalogs or load_catalogs()

    # Every check function is defensive about malformed input (unknown
    # ids/types are skipped, not crashed on), so all checks always run
    # and report together — the retry loop converges faster seeing every
    # error in one pass instead of geometry-then-everything-else.
    errors = []
    errors += check_geometry(quest, catalogs)
    errors += check_reachability(quest, catalogs)
    errors += check_balance(quest, params, catalogs)

    expected_stairway_room = params.get("stairwayRoom")
    actual_stairway_room = quest.get("stairway", {}).get("room")
    if expected_stairway_room and actual_stairway_room != expected_stairway_room:
        errors.append(
            f"stairway must be placed in room {expected_stairway_room} (pre-selected), "
            f"got {actual_stairway_room}"
        )

    warnings = check_narrative(quest)

    return ValidationResult(errors=errors, warnings=warnings)
