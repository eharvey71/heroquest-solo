"""Checks the ten 1989 Artifact Cards are used the way the box allows:
each one is a single physical card, so a quest may place it AT MOST
ONCE, and only as an id the catalog actually knows.

Two independent placements, either or both, per quest:

- The `find_artifact` objective can name which artifact is the goal
  (`objective.target.artifactId`) -- the quest's whole point is to go
  get it. Completion is still "a hero reached target.room" (unchanged,
  see engine/objective.py): naming the artifact is narration, not a new
  completion trigger, because whether it was actually picked up is the
  same physical-treasure question CLAUDE.md already puts out of scope.
- Any furniture piece can hold one as loot along the way
  (`furniture[].contains.artifactId`) -- found, not the objective.

Cross-QUEST uniqueness (the same physical card can't turn up in two
different quests) is out of scope here: this module only ever sees one
quest at a time. That's campaign-continuity's job once it exists.
"""

from __future__ import annotations


def check_artifacts(quest: dict, catalogs) -> list:
    errors = []
    known = catalogs.artifacts
    seen: dict[str, list[str]] = {}

    def _reference(artifact_id: str, where: str) -> None:
        if artifact_id not in known:
            errors.append(f"{where} references unknown artifact '{artifact_id}'")
            return
        seen.setdefault(artifact_id, []).append(where)

    objective = quest.get("objective", {})
    if objective.get("type") == "find_artifact":
        artifact_id = objective.get("target", {}).get("artifactId")
        if artifact_id:
            _reference(artifact_id, "objective.target.artifactId")

    for room_id, room in quest.get("rooms", {}).items():
        for piece in room.get("furniture", []):
            artifact_id = (piece.get("contains") or {}).get("artifactId")
            if artifact_id:
                _reference(artifact_id, f"{room_id} furniture ({piece.get('type', '?')})")

    for artifact_id, wheres in seen.items():
        if len(wheres) > 1:
            errors.append(
                f"artifact '{artifact_id}' is placed {len(wheres)} times ({', '.join(wheres)}), "
                f"but there is one physical card of each"
            )

    return errors
