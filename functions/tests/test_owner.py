"""The server-side half of the single-owner lock.

firestore.rules covers direct client reads and writes; Cloud Functions
bypass those rules entirely, so owner.py has to make the same decision
independently. These tests are that decision, without a Firestore.
"""

import pytest

from owner import check_owner, reset_cache


class FakeSnapshot:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data


class FakeDb:
    """Just enough Firestore to answer db.collection(...).document(...).get()."""

    def __init__(self, owner_doc=None):
        self.owner_doc = owner_doc
        self.reads = 0

    def collection(self, name):
        assert name == "config"
        return self

    def document(self, name):
        assert name == "owner"
        return self

    def get(self):
        self.reads += 1
        return FakeSnapshot(self.owner_doc)


@pytest.fixture(autouse=True)
def clear_cache():
    reset_cache()
    yield
    reset_cache()


def test_signed_out_is_refused():
    allowed, reason = check_owner(FakeDb({"uid": "owner-uid"}), None)
    assert allowed is False
    assert reason == "unauthenticated"


def test_the_owner_is_allowed():
    allowed, reason = check_owner(FakeDb({"uid": "owner-uid"}), "owner-uid")
    assert (allowed, reason) == (True, "owner")


def test_anyone_else_is_refused():
    allowed, reason = check_owner(FakeDb({"uid": "owner-uid"}), "some-stranger")
    assert (allowed, reason) == (False, "not_owner")


def test_before_the_claim_any_signed_in_user_passes():
    # The pre-claim window: the app behaves as it did before the lock
    # existed, so a fresh deploy isn't bricked between deploying and
    # signing in once.
    allowed, reason = check_owner(FakeDb(None), "whoever")
    assert (allowed, reason) == (True, "unclaimed")


def test_a_malformed_claim_is_treated_as_unclaimed():
    allowed, reason = check_owner(FakeDb({"uid": ""}), "whoever")
    assert (allowed, reason) == (True, "unclaimed")


def test_the_uid_is_read_once_per_instance():
    db = FakeDb({"uid": "owner-uid"})
    for _ in range(5):
        check_owner(db, "owner-uid")
    assert db.reads == 1


def test_an_unclaimed_lookup_is_retried():
    # The claim can land after this instance started, so a miss must not
    # be cached -- otherwise a warm instance stays permanently open.
    db = FakeDb(None)
    check_owner(db, "whoever")
    check_owner(db, "whoever")
    assert db.reads == 2
