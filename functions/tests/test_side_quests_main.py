"""main.py's side-quest wiring against fake Firestore (same conventions
as test_main_defence_queue.py): the begin/advance endpoints, the ward on
hero attacks, the seal on the objective, the lock on every other
action, and how a game is created in each mode."""

import copy

import pytest

import main
from engine.create_game import build_initial_game_state
from firestore_coords import from_firestore_coords, to_firestore_coords
from tests.test_side_quests_engine import QUEST as ENGINE_QUEST, SCENE

QUEST = copy.deepcopy(ENGINE_QUEST)

GAME = {
    "questId": "Q1",
    "mode": "expanded",
    "phase": "hero",
    "status": "in_progress",
    "turn": 3,
    "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True}],
    "monsters": {"M1": {"type": "chaos_warrior", "pos": [8, 3], "currentBody": 3, "alive": True}},
    "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
    "doors": {"D1": "open"},
    "sideQuests": {},
    "pendingSideQuest": None,
    "gate": {"kind": "ward", "targetMonsterId": "M1", "targetName": "Vorlag", "sideQuestId": "SQ1", "state": "closed", "text": "A ward."},
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
    def __init__(self, data):
        self._data = data

    def get(self, transaction=None):
        return _Snap(self._data)

    def collection(self, name):
        return _Coll({})


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def document(self, name):
        return _Ref(self._docs.get(name))


class _DB:
    def __init__(self, quest=None):
        self._quest = quest or QUEST

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


def _game(**overrides):
    game = copy.deepcopy(GAME)
    game.update(overrides)
    return _Ref(to_firestore_coords(game))


def test_begin_writes_the_lock_and_an_undo_snapshot():
    txn = _Txn()
    step = main._apply_begin_side_quest.to_wrap(txn, _DB(), _game(), "SQ1")
    assert txn.updates["pendingSideQuest"] == "SQ1"
    assert txn.updates["sideQuests.SQ1"]["status"] == "active"
    assert step.passage_id == "p1"
    assert txn.snapshots and txn.snapshots[0]["label"] == "beginning the side quest"


def test_begin_refuses_in_a_traditional_game():
    # The endpoint maps SideQuestError to FAILED_PRECONDITION; the
    # transactional body raises the engine's own error.
    with pytest.raises(main.SideQuestError, match="traditional"):
        main._apply_begin_side_quest.to_wrap(_Txn(), _DB(), _game(mode="traditional"), "SQ1")


def test_every_other_action_is_locked_while_a_scene_runs():
    game = _game(pendingSideQuest="SQ1", sideQuests={"SQ1": {"status": "active", "passageId": "p1", "flags": [], "history": []}})
    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        main._apply_movement.to_wrap(_Txn(), _DB(), game, "barbarian", [[6, 2], [7, 2]])
    assert "side quest" in exc_info.value.message


def test_advance_to_a_terminal_hands_the_game_back():
    game = _game(pendingSideQuest="SQ1", sideQuests={"SQ1": {"status": "active", "passageId": "p2", "flags": [], "history": ["go"]}})
    txn = _Txn()
    step = main._apply_advance_side_quest.to_wrap(txn, _DB(), game, "leap", {"skulls": 2})
    assert step.finished and step.outcome == "success"
    assert txn.updates["pendingSideQuest"] is None
    assert txn.updates["sideQuests.SQ1"]["status"] == "success"
    assert any("40 gold" in e["text"] for e in txn.updates["log"])
    assert txn.snapshots[0]["label"] == "the side quest step"


def test_a_warded_boss_takes_no_damage_from_a_hero_attack():
    txn = _Txn()
    result = main._apply_hero_attack.to_wrap(txn, _DB(), _game(), "M1", 3)
    assert result.damage == 0 and result.body_points_after == 3
    assert "monsters.M1.currentBody" not in txn.updates
    line = next(e["text"] for e in txn.updates["log"] if "warded" in e["text"])
    # The first blocked blow is when the party learns the gate exists:
    # the Journal may list the required scene from here on. The line
    # names no scene the party hasn't met.
    assert txn.updates["gate.noticed"] is True
    assert "(See the Journal.)" in line and "The Black Candle" not in line


def test_the_ward_notice_names_the_scene_once_met():
    game = _game(sideQuests={"SQ1": {"status": "known"}}, gate={**GAME["gate"], "noticed": True})
    txn = _Txn()
    main._apply_hero_attack.to_wrap(txn, _DB(), game, "M1", 3)
    line = next(e["text"] for e in txn.updates["log"] if "warded" in e["text"])
    assert "(Journal: " in line
    assert "gate.noticed" not in txn.updates


def test_an_open_gate_lets_the_attack_land():
    game = _game(gate={**GAME["gate"], "state": "open"})
    txn = _Txn()
    main._apply_hero_attack.to_wrap(txn, _DB(), game, "M1", 3)
    assert "monsters.M1.currentBody" in txn.updates


def test_a_cracked_ward_adds_a_defend_die(monkeypatch):
    seen = {}

    def fake_defend(game_state, monster_id, dice):
        seen["dice"] = dice
        return dice

    monkeypatch.setattr(main, "monster_defend_dice", fake_defend)
    game = _game(gate={**GAME["gate"], "state": "cracked"})
    game._data["monsters"]["M1"]["bonusDefend"] = 1
    main._apply_hero_attack.to_wrap(_Txn(), _DB(), game, "M1", 1)
    assert seen["dice"] == 5  # chaos_warrior defends 4, +1 for the cracked ward


def test_a_sealed_goal_does_not_complete_and_says_why_once():
    quest = copy.deepcopy(QUEST)
    quest["objective"] = {"type": "find_artifact", "description": "x", "target": {"room": "R2"}}
    game = copy.deepcopy(GAME)
    game["gate"] = {"kind": "seal", "targetRoom": "R2", "sideQuestId": "SQ1", "state": "closed", "text": "The rite holds it."}
    updates, log = {}, []
    assert main._mark_objective_if_complete(quest, game, updates, log, 3) is False
    assert "objectiveComplete" not in updates
    assert updates["gate.noticed"] is True
    assert any("sealed" in e["text"] for e in log)
    # A second call stays quiet.
    updates, log = {}, []
    main._mark_objective_if_complete(quest, game, updates, log, 3)
    assert log == []


def test_lifting_the_seal_completes_a_goal_already_reached():
    quest = copy.deepcopy(QUEST)
    quest["objective"] = {"type": "find_artifact", "description": "x", "target": {"room": "R2"}}
    quest["sideQuests"] = [{**SCENE, "kind": "required"}]
    game = _game(
        gate={"kind": "seal", "targetRoom": "R2", "sideQuestId": "SQ1", "state": "closed", "text": ""},
        pendingSideQuest="SQ1",
        sideQuests={"SQ1": {"status": "active", "passageId": "p2", "flags": [], "history": ["go"]}},
    )
    txn = _Txn()
    main._apply_advance_side_quest.to_wrap(txn, _DB(quest), game, "leap", {"skulls": 2})
    assert txn.updates["gate.state"] == "open"
    assert txn.updates["objectiveComplete"] is True


# ---- creating a game in each mode ----


def test_parse_generation_params_defaults_to_traditional():
    assert main._parse_generation_params({"heroCount": 4})["mode"] == "traditional"
    assert main._parse_generation_params({"heroCount": 4, "mode": "expanded"})["mode"] == "expanded"
    with pytest.raises(main.https_fn.HttpsError):
        main._parse_generation_params({"heroCount": 4, "mode": "hardcore"})


def test_parse_create_game_request_carries_the_mode():
    _, _, _, mode = main._parse_create_game_request({"questId": "Q1", "heroes": [{"id": "barbarian"}], "mode": "expanded"})
    assert mode == "expanded"
    _, _, _, mode = main._parse_create_game_request({"questId": "Q1", "heroes": [{"id": "barbarian"}]})
    assert mode == "traditional"


def test_an_expanded_game_starts_with_its_gate_closed(catalogs, good_quest_4h):
    quest = {**good_quest_4h, "sideQuests": [SCENE], "gate": {"kind": "ward", "targetMonsterId": "M17", "sideQuestId": "SQ1"}}
    game = build_initial_game_state(quest=quest, catalogs=catalogs, heroes=[{"id": "barbarian"}], mode="expanded")
    assert game["mode"] == "expanded"
    assert game["gate"]["state"] == "closed"
    assert game["sideQuests"] == {} and game["pendingSideQuest"] is None


def test_a_traditional_game_on_an_expanded_quest_has_no_gate(catalogs, good_quest_4h):
    quest = {**good_quest_4h, "sideQuests": [SCENE], "gate": {"kind": "ward", "targetMonsterId": "M17", "sideQuestId": "SQ1"}}
    game = build_initial_game_state(quest=quest, catalogs=catalogs, heroes=[{"id": "barbarian"}], mode="traditional")
    assert game["mode"] == "traditional" and game["gate"] is None


def test_expanded_on_a_quest_without_side_quests_is_just_traditional(catalogs, good_quest_4h):
    game = build_initial_game_state(quest=good_quest_4h, catalogs=catalogs, heroes=[{"id": "barbarian"}], mode="expanded")
    assert game["mode"] == "traditional" and game["gate"] is None


def test_firestore_round_trip_keeps_a_scene_intact():
    # Side quests hold no [x,y] pairs, so the coordinate conversion must
    # leave them exactly as written -- a dice pair like [2, 1] anywhere
    # would silently become {x, y}.
    wire = to_firestore_coords(copy.deepcopy(SCENE))
    assert from_firestore_coords(wire) == SCENE


# ---- the second call: writing the scenes onto a saved quest ----


def _expanded_quest(good_quest_4h, required=False):
    return {
        **copy.deepcopy(good_quest_4h),
        "mode": "expanded",
        "generationParams": {"heroCount": 4, "difficulty": "standard", "size": "full", "mode": "expanded"},
        "sideQuestsStatus": "pending",
        "sideQuestPlan": {"required": required},
    }


def test_write_side_quests_marks_the_quest_ready(good_quest_4h):
    from tests.test_side_quests_generator import ScriptedClient, _wire
    from tests.test_side_quests_validator import _scene

    client = ScriptedClient([{"sideQuests": [_wire(_scene())]}])
    stages = []
    updates = main._write_side_quests(_expanded_quest(good_quest_4h), client, lambda stage, detail: stages.append(stage))
    assert updates["sideQuestsStatus"] == "ready"
    assert [sq["id"] for sq in updates["sideQuests"]] == ["SQ1"]
    assert "gate" not in updates
    assert stages[0] == "writing_side_quests" and "validating_side_quests" in stages


def test_write_side_quests_builds_the_gate_when_the_plan_asked_for_one(good_quest_4h):
    from tests.test_side_quests_generator import ScriptedClient, _wire
    from tests.test_side_quests_validator import _required, _scene

    client = ScriptedClient([{"sideQuests": [_wire(_scene()), _wire(_required(good_quest_4h))]}])
    updates = main._write_side_quests(_expanded_quest(good_quest_4h, required=True), client)
    assert updates["gate"]["kind"] == "ward"
    assert updates["gate"]["sideQuestId"] == "SQ2"
    assert updates["gate"]["targetMonsterId"] == "M17"


def test_write_side_quests_raises_so_the_endpoint_can_record_the_failure(good_quest_4h):
    from generator.side_quests import SideQuestGenerationFailed
    from tests.test_side_quests_generator import ScriptedClient, _wire
    from tests.test_side_quests_validator import _scene

    bad = _scene()
    bad["passages"]["p1"]["text"] = "Walk to R12."
    client = ScriptedClient([{"sideQuests": [_wire(bad)]}] * 3)
    with pytest.raises(SideQuestGenerationFailed):
        main._write_side_quests(_expanded_quest(good_quest_4h), client)


def test_job_progress_swallows_write_failures():
    class _BadRef:
        def set(self, *a, **k):
            raise RuntimeError("firestore down")

    class _BadDB:
        def collection(self, name):
            return self

        def document(self, name):
            return _BadRef()

    progress = main._JobProgress(_BadDB(), "job-1")
    progress("writing", "still fine")  # must not raise
    assert main._JobProgress(_BadDB(), None)("x") is None


def test_generation_params_carry_the_job_id():
    assert main._parse_generation_params({"heroCount": 4, "jobId": "abc"})["jobId"] == "abc"
    assert "jobId" not in main._parse_generation_params({"heroCount": 4})
    with pytest.raises(main.https_fn.HttpsError):
        main._parse_generation_params({"heroCount": 4, "jobId": "x" * 81})


# ---- discovery through the endpoints ----


def test_walking_into_the_hook_room_makes_the_scene_known():
    # The hero starts outside R2 and walks in; SCENE's hook is Old Hessa in R2.
    game = _game(heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [5, 1], "alive": True}])
    txn = _Txn()
    main._apply_movement.to_wrap(txn, _DB(), game, "barbarian", [[5, 1], [5, 2]])
    assert txn.updates["sideQuests.SQ1"] == {"status": "known"}
    assert any("Old Hessa" in e["text"] for e in txn.updates["log"])


def test_opening_the_door_only_asks_for_the_figure():
    quest = copy.deepcopy(QUEST)
    quest["doors"][0]["state"] = "closed"
    game = _game(
        heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [4, 1], "alive": True}],
        revealed={"rooms": ["R1"], "corridorSquares": []},
        doors={},
    )
    txn = _Txn()
    main._apply_open_door.to_wrap(txn, _DB(quest), game, "barbarian", "D1")
    assert any("figure for Old Hessa" in line and "R2" in line for line in txn.updates["placementInstructions"])
    assert "sideQuests.SQ1" not in txn.updates  # nobody has met her yet


def test_a_spawned_wanderer_can_be_attacked():
    # A scene's spawn_wandering (and every other runtime spawn) lives
    # only in game state; the attack used to fail "not found in quest".
    game = _game(monsters={**GAME["monsters"], "W1": {"type": "orc", "pos": [2, 2], "currentBody": 1, "alive": True}})
    txn = _Txn()
    result = main._apply_hero_attack.to_wrap(txn, _DB(), game, "W1", 3)
    assert result.monster_name == "Orc"
    assert result.skulls_faced == 3
