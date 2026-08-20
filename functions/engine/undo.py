"""Rolling the board back one action.

Solo play has no second pair of hands to catch a mis-dragged path, a
mistyped skull count or an early End Turn, and before this the only fix
was starting the game over.

The shape is a stack of full snapshots, not a diff: undoing has to be
able to make things DISAPPEAR -- a searched room, a spawned wandering
monster, a sprung trap, a revealed corridor -- and a field-by-field
merge can only ever add or overwrite. Each snapshot also carries the
label of the step below it, so an undo can name what is next in line
without a second read.

Pure dict-in/dict-out: main.py owns the Firestore transaction, the
subcollection and the coordinate conversion, exactly as it does for
every other engine module.
"""

from __future__ import annotations

# Bookkeeping that must NOT ride along inside a snapshot: createdAt
# belongs to the game document for good, and the undo pointers describe
# the stack rather than the state being stacked.
SKIPPED_FIELDS = ("createdAt", "undoDepth", "undoLabel")


class NothingToUndoError(ValueError):
    """The game is already back at its starting position."""


def snapshot_id(depth: int) -> str:
    """Zero-padded so the undo subcollection sorts in play order."""
    return f"{depth:05d}"


def build_snapshot(before: dict, label: str) -> tuple[int, dict, dict]:
    """(depth, snapshot document, updates for the game document).

    `before` is the game state as it stood BEFORE the action -- callers
    must deep-copy it at load time, since the action mutates its own
    copy in place.
    """
    depth = int(before.get("undoDepth") or 0) + 1
    entry = {
        "state": {k: v for k, v in before.items() if k not in SKIPPED_FIELDS},
        "label": label,
        "prevLabel": before.get("undoLabel"),
    }
    return depth, entry, {"undoDepth": depth, "undoLabel": label}


def restore(current: dict, entry: dict) -> dict:
    """The complete document to write back over the game doc.

    Takes the CURRENT doc only for the fields that outlive an undo
    (createdAt) -- everything else comes from the snapshot.
    """
    depth = int(current.get("undoDepth") or 0)
    if depth <= 0:
        raise NothingToUndoError("there is nothing left to undo")

    label = entry.get("label", "the last action")
    restored = dict(entry.get("state", {}))
    restored["undoDepth"] = depth - 1
    restored["undoLabel"] = entry.get("prevLabel")
    if "createdAt" in current:
        restored["createdAt"] = current["createdAt"]
    restored["log"] = list(restored.get("log", [])) + [
        {
            "turn": restored.get("turn", 0),
            "text": f"Undone: {label}. The board is back to where it stood before it.",
        }
    ]
    return restored
