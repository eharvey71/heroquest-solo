"""Who this app belongs to.

Cloud Functions run with the Admin SDK, which bypasses firestore.rules
entirely -- so the rules locking the database to one uid do nothing for
the callable endpoints. This module is the same check on the server
side, and every endpoint runs it.

The owner's uid is not baked into the source: it lives in the
config/owner document, claimed once by the first Google sign-in (see
firestore.rules). That means no deploy can lock the owner out by
shipping the wrong constant, and the uid can be corrected in the
console without a release.

Before the claim exists, endpoints fall back to "any signed-in user" --
the state the app was in before this module existed. That window should
last about as long as it takes to press the sign-in button once; the
claim happens automatically on the owner's first visit.
"""

from __future__ import annotations

CONFIG_COLLECTION = "config"
OWNER_DOC = "owner"

# Function instances are reused between calls, so the lookup happens
# once per instance rather than once per request. The uid never changes
# (the rules make config/owner immutable once written), so a cached hit
# can't go stale; a cached MISS is retried, since the claim may land
# after this instance started.
_cached_uid: str | None = None


def owner_uid(db) -> str | None:
    """The claimed owner's uid, or None if nobody has claimed it yet."""
    global _cached_uid
    if _cached_uid is not None:
        return _cached_uid

    snapshot = db.collection(CONFIG_COLLECTION).document(OWNER_DOC).get()
    if not snapshot.exists:
        return None
    uid = (snapshot.to_dict() or {}).get("uid")
    if isinstance(uid, str) and uid:
        _cached_uid = uid
    return _cached_uid


def check_owner(db, auth_uid: str | None) -> tuple[bool, str]:
    """(allowed, reason). Kept free of firebase_functions imports so it
    can be unit-tested without the Functions runtime.
    """
    if not auth_uid:
        return False, "unauthenticated"
    claimed = owner_uid(db)
    if claimed is None:
        return True, "unclaimed"  # pre-claim window; see the module docstring
    if auth_uid != claimed:
        return False, "not_owner"
    return True, "owner"


def reset_cache() -> None:
    """Tests only -- the process-wide cache would otherwise leak between
    cases."""
    global _cached_uid
    _cached_uid = None
