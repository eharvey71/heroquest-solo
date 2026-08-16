"""Cloud Functions entry points for the HeroQuest Zargon app.

Two responsibilities live here, kept strictly separate (see CLAUDE.md):

1. Quest generation (generate_quest): prompt build -> LLM call -> validate
   -> auto-repair -> retry (max 3) -> Firestore write. The client never
   sees an unvalidated quest.
2. The Zargon rules engine (movement, target choice, combat resolution):
   deterministic code only. The LLM is never in the rules path.

This file is currently a skeleton (Task 1: project scaffold). The
generator and engine modules land in later tasks.
"""

from firebase_admin import initialize_app
from firebase_functions import https_fn, options

initialize_app()

# All callable functions default to this region; change once the owner
# picks a home region for the project.
options.set_global_options(region="us-central1")


@https_fn.on_call()
def health_check(req: https_fn.CallableRequest) -> dict:
    """Trivial callable to confirm the Functions deploy pipeline works."""
    return {"status": "ok", "service": "heroquest-zargon"}


@https_fn.on_call()
def generate_quest(req: https_fn.CallableRequest) -> dict:
    """Generate a new quest and write the validated result to Firestore.

    Not yet implemented — see design/quest-generator-design.md and
    design/generator-prompt.md for the design this will follow.

    IMPORTANT before this calls an LLM for real: callable functions do
    NOT inherit the Firestore auth rule (that only guards direct client
    reads/writes). This function needs its own `if req.auth is None:
    raise HttpsError(UNAUTHENTICATED, ...)` check, or an unauthenticated
    caller can trigger paid LLM calls.
    """
    raise https_fn.HttpsError(
        code=https_fn.FunctionsErrorCode.UNIMPLEMENTED,
        message="generate_quest is not implemented yet (Task 2+).",
    )
