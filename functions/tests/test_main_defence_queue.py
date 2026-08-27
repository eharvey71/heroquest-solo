"""Fake-Firestore tests for the pendingDefenses queue in main.py.

main.py's _apply_* functions had no coverage at all -- they need a
transaction and a document reference, so nothing exercised them and a
write that only fails against real Firestore reached production. These
fakes are the minimum that lets the apply functions run: a document
snapshot, a collection lookup, and a transaction that records what it
was asked to write.
"""

import copy

import pytest

import main
from engine.undo import snapshot_id
from firestore_coords import to_firestore_coords

QUEST = {
    "doors": [{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}],
    "objective": {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
    "wanderingMonster": "orc",
    "rooms": {
        "R2": {
            "monsters": [{"id": "M1", "type": "chaos_warrior", "name": "Vorlag", "pos": [8, 3]}],
            "traps": [],
            "furniture": [],
        }
    },
    "stairway": {"room": "R1", "pos": [1, 1]},
}

GAME = {
    "questId": "Q1",
    "phase": "zargon",
    "status": "in_progress",
    "turn": 7,
    "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}],
    "monsters": {"M1": {"pos": [7, 3], "currentBody": 3, "alive": True}},
    "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
    "doors": {"D1": "open"},
    "log": [],
    "undoDepth": 0,
}


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, data, subcollections=None):
        self._data = data
        self._subcollections = subcollections or {}

    def get(self, transaction=None):
        return _Snap(self._data)

    def collection(self, name):
        return _Coll(self._subcollections.get(name, {}))


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def document(self, name):
        return _Ref(self._docs.get(name))


class _DB:
    def __init__(self, quest):
        self._quest = quest

    def collection(self, name):
        return _Coll({"Q1": to_firestore_coords(copy.deepcopy(self._quest))})


class _Txn:
    def __init__(self):
        self.updates = None
        self.snapshots = []

    def update(self, ref, updates):
        self.updates = updates

    def set(self, ref, entry):
        self.snapshots.append(entry)

    def delete(self, ref):
        pass


def _run_zargon_turn(turn_type, game=None, quest=None, lowest_bp="barbarian"):
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(copy.deepcopy(game or GAME)))
    main._apply_zargon_turn.to_wrap(txn, _DB(quest or QUEST), game_ref, turn_type, lowest_bp)
    return txn


@pytest.mark.parametrize("turn_type", ["normal", "cunning", "wandering"])
def test_every_turn_type_writes_a_defence_queue(turn_type):
    txn = _run_zargon_turn(turn_type)
    pending = txn.updates["pendingDefenses"]
    assert isinstance(pending, list)
    for entry in pending:
        assert set(entry) == {"id", "heroId", "heroName", "skulls", "monsterId", "monsterName", "pos", "turn"}
        assert entry["heroId"] == "barbarian"
        assert entry["skulls"] >= 0
        # The prompt has to say WHAT swung and where it stands, or the
        # player is told "3 skulls" with no figure to look for. monsterId
        # is what lets the client highlight the attacker's own token.
        assert entry["monsterId"]
        assert entry["monsterName"]
        assert len(entry["pos"]) == 2
        # The turn the attack happened -- game.turn advances to 8 in
        # this same write, and the defence roll's log line files here.
        assert entry["turn"] == 7


def test_an_adjacent_monster_queues_its_attack():
    # M1 starts orthogonally adjacent to the hero, so a normal turn
    # always produces exactly one prompt.
    txn = _run_zargon_turn("normal")
    assert len(txn.updates["pendingDefenses"]) == 1
    assert txn.updates["pendingDefenses"][0]["id"] == "7:M1"


def test_the_queue_is_written_whole_so_stale_prompts_cannot_leak():
    game = copy.deepcopy(GAME)
    game["pendingDefenses"] = [
        {"id": "6:M9", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2}
    ]
    txn = _run_zargon_turn("normal", game=game)
    assert all(e["id"] != "6:M9" for e in txn.updates["pendingDefenses"])


def test_the_undo_snapshot_keeps_the_queue_it_replaced():
    game = copy.deepcopy(GAME)
    game["pendingDefenses"] = [
        {"id": "6:M9", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2}
    ]
    txn = _run_zargon_turn("normal", game=game)
    assert txn.snapshots[0]["state"]["pendingDefenses"][0]["id"] == "6:M9"


def test_answering_a_prompt_removes_only_that_one():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2},
        {"id": "7:M2", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 3},
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 2, 1, "7:M1")
    assert [e["id"] for e in txn.updates["pendingDefenses"]] == ["7:M2"]


def test_a_client_that_sends_no_id_falls_back_to_first_match():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2},
        {"id": "7:M2", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 3},
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 3, 1, None)
    assert [e["id"] for e in txn.updates["pendingDefenses"]] == ["7:M1"]


def test_a_wandering_monster_card_names_what_walked_in():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["heroes"][0]["pos"] = [6, 2]
    game["monsters"] = {}
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_search_treasure.to_wrap(txn, _DB(QUEST), game_ref, "barbarian", "R2", True)

    # The player has never seen this figure: the prompt must say what it
    # is and where to stand it, and a placement line must accompany it.
    prompt = txn.updates["pendingDefenses"][-1]
    assert prompt["monsterId"] == "W1"
    assert prompt["monsterName"] == "orc"
    assert prompt["pos"]
    assert any("orc" in line for line in txn.updates["placementInstructions"])


def test_ending_the_hero_phase_clears_stale_placements():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["placementInstructions"] = ["Place the orc mini at square [6,1]."]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_end_turn.to_wrap(txn, game_ref)
    assert txn.updates["placementInstructions"] == []


def test_ending_the_hero_phase_is_blocked_while_a_defence_is_pending():
    # This is what let the reported bug happen: a player pressed End
    # Turn with an unanswered "N skulls" prompt still on screen, which
    # advanced the game into Zargon's next turn -- whose whole-queue
    # write would have silently discarded that hit for good.
    from engine.end_turn import DefencesPendingError

    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 1}
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    with pytest.raises(DefencesPendingError):
        main._apply_end_turn.to_wrap(txn, game_ref)
    # Nothing should have been written -- the transaction never reached
    # its update() call.
    assert txn.updates is None


PENDING_DEFENSE_GATED_CALLS = {
    "movement": lambda txn, game_ref: main._apply_movement.to_wrap(
        txn, _DB(QUEST), game_ref, "barbarian", [[7, 2], [7, 3]]
    ),
    "open_door": lambda txn, game_ref: main._apply_open_door.to_wrap(txn, _DB(QUEST), game_ref, "barbarian", "D1"),
    "search_treasure": lambda txn, game_ref: main._apply_search_treasure.to_wrap(
        txn, _DB(QUEST), game_ref, "barbarian", "R2", False
    ),
    "search_traps": lambda txn, game_ref: main._apply_search_traps_and_secret_doors.to_wrap(
        txn, _DB(QUEST), game_ref, "barbarian", "R2", "traps"
    ),
    "trap_action": lambda txn, game_ref: main._apply_trap_action.to_wrap(
        txn, _DB(QUEST), game_ref, "barbarian", "R2:1,1", "jump", "white_shield", None, False
    ),
    "cast_spell": lambda txn, game_ref: main._apply_cast_spell.to_wrap(
        txn, _DB(QUEST), game_ref, "barbarian", "heal_body", None, None, None, False
    ),
    "hero_attack": lambda txn, game_ref: main._apply_hero_attack.to_wrap(txn, _DB(QUEST), game_ref, "M1", 3),
}


@pytest.mark.parametrize("name", sorted(PENDING_DEFENSE_GATED_CALLS))
def test_hero_actions_are_blocked_while_a_defence_is_pending(name):
    # Server-side half of the client-side lock: a stale tab or a direct
    # call must not be able to do what the hidden buttons already
    # prevent. _require_no_pending_defenses runs before any other
    # validation, so these dummy args never actually get used.
    game = copy.deepcopy(GAME)
    game["pendingDefenses"] = [
        {"id": "7:M9", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 1}
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        PENDING_DEFENSE_GATED_CALLS[name](txn, game_ref)
    assert exc_info.value.code == main.https_fn.FunctionsErrorCode.FAILED_PRECONDITION
    assert "defence" in exc_info.value.message
    # Nothing should have been written.
    assert txn.updates is None


def test_record_hero_defense_itself_is_not_blocked_by_the_queue_it_clears():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 1}
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    # Must not raise -- this is the one action that's supposed to work.
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 1, 1, "7:M1")
    assert txn.updates is not None


def test_undo_restores_turn_and_phase_after_zargons_turn():
    # Resolving Zargon's turn advances turn+1 and flips phase back to
    # "hero" -- undoing that action has to put BOTH back, or the header
    # ("Turn N -- Hero/Zargon phase") would read one step ahead of what
    # the board actually shows.
    txn1 = _Txn()
    game_ref1 = _Ref(to_firestore_coords(copy.deepcopy(GAME)))
    main._apply_zargon_turn.to_wrap(txn1, _DB(QUEST), game_ref1, "normal", None)

    assert txn1.updates["turn"] == GAME["turn"] + 1
    assert txn1.updates["phase"] == "hero"
    undo_entry = txn1.snapshots[0]
    assert undo_entry["state"]["turn"] == GAME["turn"]
    assert undo_entry["state"]["phase"] == "zargon"

    # Build the document as it stands right after that turn resolved
    # (Firestore-coord shape, same as _apply_undo reads it): the base
    # game plus every simple top-level field the turn touched.
    after_zargon = to_firestore_coords(copy.deepcopy(GAME))
    for key, value in txn1.updates.items():
        if "." not in key:
            after_zargon[key] = value

    game_ref2 = _Ref(after_zargon, subcollections={"undo": {snapshot_id(1): undo_entry}})
    txn2 = _Txn()
    main._apply_undo.to_wrap(txn2, game_ref2)

    restored = txn2.snapshots[0]
    assert restored["turn"] == GAME["turn"]
    assert restored["phase"] == "zargon"
    assert restored["undoDepth"] == 0
    # And the defence prompts that Zargon's turn raised are gone with
    # it -- they belonged to a turn that no longer happened.
    assert restored.get("pendingDefenses", []) == []


def test_defence_log_line_files_under_the_attack_turn():
    # The Fimir swung in turn 7; the player answered after "--- Turn 8 ---"
    # was already logged. The line must splice in at the end of turn 7,
    # under turn 7's number -- not dangle at the bottom under turn 8 --
    # so turn 7's narration (which waits for open defences) can see
    # whether the blow landed.
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["turn"] = 8
    game["log"] = [
        {"turn": 7, "text": "Fimir attacks Barbarian: 3 dice, 2 skull(s)."},
        {"turn": 7, "text": "Zargon ends his turn."},
        {"turn": 8, "text": "--- Turn 8 ---"},
    ]
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2, "turn": 7},
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 2, 2, "7:M1")

    log = txn.updates["log"]
    texts = [e["text"] for e in log]
    defence_index = next(i for i, t in enumerate(texts) if "defends" in t)
    assert log[defence_index]["turn"] == 7
    assert defence_index == 2  # after "Zargon ends his turn", before "--- Turn 8 ---"
    assert txn.updates["pendingDefenses"] == []


def test_defence_from_a_legacy_prompt_without_a_turn_logs_under_now():
    # Queue entries written before the turn stamp existed still resolve;
    # they just file under the current turn as before.
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["turn"] = 8
    game["log"] = [{"turn": 8, "text": "--- Turn 8 ---"}]
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2},
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 2, 0, "7:M1")

    assert txn.updates["log"][-1]["turn"] == 8
