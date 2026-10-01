"""engine/side_quests.py: beginning a scene, walking its passages, the
tests, the effects, and the gate. Pure functions, real board."""

import copy
import random

import pytest

from engine.end_turn import SideQuestPendingError, resolve_end_turn
from engine.side_quests import (
    SideQuestError,
    advance_side_quest,
    begin_side_quest,
    choice_visible,
    encounter_updates,
    hook_available,
    npc_placements,
    seal_blocks,
    ward_blocks,
)

SCENE = {
    "id": "SQ1",
    "kind": "optional",
    "title": "The Weeping Well",
    "setting": "cave",
    "hook": {"when": "room", "room": "R2", "npcName": "Old Hessa", "figureHint": "any robed figure", "text": "Hessa beckons."},
    "gateText": "",
    "start": "p1",
    "passages": {
        "p1": {
            "text": "The well breathes.",
            "choices": [
                {"id": "go", "label": "Climb down", "next": "p2"},
                {"id": "dwarf", "label": "The Dwarf tests the rope", "requiresHero": "dwarf", "next": "p2"},
                {"id": "fire", "label": "Light the shaft", "requiresElement": "Fire", "setsFlag": "lit", "next": "p2"},
            ],
        },
        "p2": {
            "text": "A gap.",
            "choices": [
                {"id": "leap", "label": "Leap", "test": {"kind": "combat_dice", "dice": 2, "needSkulls": 1, "success": "t_win", "failure": "p3"}},
                {"id": "seen", "label": "Use the light", "requiresFlag": "lit", "next": "t_win"},
                {"id": "back", "label": "Turn back", "next": "t_lose"},
            ],
        },
        "p3": {
            "text": "You slip.",
            "choices": [
                {"id": "again", "label": "Try again", "next": "p2"},
                {"id": "quit", "label": "Give up", "next": "t_lose"},
            ],
        },
    },
    "terminals": {
        "t_win": {"outcome": "success", "text": "Coin.", "effects": [{"type": "announce_reward", "kind": "gold", "text": "You find 40 gold."}]},
        "t_lose": {"outcome": "failure", "text": "Nothing.", "effects": [{"type": "announce_cost", "kind": "body", "text": "The cold bites."}]},
    },
    "retry": {"from": "p3", "to": "p2", "costText": "The second attempt costs 1 Body Point."},
}

QUEST = {
    "doors": [
        {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"},
        {"id": "D2", "squares": [[8, 2], [9, 2]], "state": "secret"},
    ],
    "objective": {"type": "kill_boss", "description": "x", "target": {"monsterId": "M1"}},
    "wanderingMonster": "orc",
    "rooms": {
        "R2": {
            "monsters": [{"id": "M1", "type": "chaos_warrior", "name": "Vorlag", "pos": [8, 3]}],
            "traps": [{"type": "pit", "pos": [7, 3]}],
            "furniture": [],
        }
    },
    "stairway": {"room": "R1", "pos": [1, 1]},
    "sideQuests": [SCENE],
    "gate": {"kind": "ward", "targetMonsterId": "M1", "targetName": "Vorlag", "sideQuestId": "SQ2", "text": "A ward."},
}


def _game(**overrides):
    game = {
        "mode": "expanded",
        "phase": "hero",
        "status": "in_progress",
        "turn": 3,
        "heroes": [
            {"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "alive": True},
            {"id": "wizard", "name": "Wizard", "pos": [5, 2], "alive": True},
        ],
        "monsters": {"M1": {"type": "chaos_warrior", "pos": [8, 3], "currentBody": 3, "alive": True}},
        "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
        "doors": {"D1": "open"},
        "spellbooks": {"wizard": ["Fire", "Earth", "Air"]},
        "spellsCast": [],
        "trapsFound": {},
        "trapsTriggered": [],
        "searched": {},
        "sideQuests": {},
        "pendingSideQuest": None,
        "gate": {"kind": "ward", "targetMonsterId": "M1", "targetName": "Vorlag", "sideQuestId": "SQ2", "state": "closed"},
        "log": [],
    }
    game.update(overrides)
    return game


def _begun(catalogs, **overrides):
    game = _game(**overrides)
    begin_side_quest(board=catalogs.board, quest=QUEST, game_state=game, sq_id="SQ1")
    return game


def _adv(catalogs, game, choice, report=None, seed=1, quest=QUEST):
    return advance_side_quest(
        board=catalogs.board, catalogs=catalogs, quest=quest, game_state=game,
        choice_id=choice, report=report, rng=random.Random(seed),
    )


# ---- begin ----


def test_begin_locks_the_game_and_opens_the_first_passage(catalogs):
    game = _game()
    step = begin_side_quest(board=catalogs.board, quest=QUEST, game_state=game, sq_id="SQ1")
    assert game["pendingSideQuest"] == "SQ1"
    assert game["sideQuests"]["SQ1"]["status"] == "active"
    assert step.passage_id == "p1"
    assert step.updates["pendingSideQuest"] == "SQ1"
    assert "Hessa beckons" in step.log[0]


def test_a_room_hook_needs_a_hero_in_the_room(catalogs):
    game = _game(heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "alive": True}])
    assert not hook_available(catalogs.board, game, SCENE)
    with pytest.raises(SideQuestError, match="standing in the room"):
        begin_side_quest(board=catalogs.board, quest=QUEST, game_state=game, sq_id="SQ1")


def test_a_prologue_hook_is_always_available(catalogs):
    prologue = {**SCENE, "hook": {"when": "prologue", "room": "", "text": "The road in."}}
    game = _game(heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "alive": True}])
    assert hook_available(catalogs.board, game, prologue)


def test_a_traditional_game_has_no_side_quests(catalogs):
    with pytest.raises(SideQuestError, match="traditional"):
        begin_side_quest(board=catalogs.board, quest=QUEST, game_state=_game(mode="traditional"), sq_id="SQ1")


def test_a_finished_scene_cannot_be_begun_again(catalogs):
    game = _game(sideQuests={"SQ1": {"status": "success", "passageId": "t_win"}})
    with pytest.raises(SideQuestError, match="already over"):
        begin_side_quest(board=catalogs.board, quest=QUEST, game_state=game, sq_id="SQ1")


def test_end_turn_refuses_while_a_scene_is_in_progress(catalogs):
    game = _begun(catalogs)
    with pytest.raises(SideQuestPendingError):
        resolve_end_turn(game)


# ---- choices ----


def test_tagged_choices_are_hidden_from_a_party_without_them(catalogs):
    game = _begun(catalogs)
    progress = game["sideQuests"]["SQ1"]
    choices = {c["id"]: c for c in SCENE["passages"]["p1"]["choices"]}
    assert choice_visible(choices["go"], game, progress, SCENE)
    assert not choice_visible(choices["dwarf"], game, progress, SCENE)  # no dwarf in the party
    assert choice_visible(choices["fire"], game, progress, SCENE)  # the wizard holds Fire, unspent
    game["spellsCast"] = ["ball_of_flame", "fire_of_wrath", "courage"]
    assert not choice_visible(choices["fire"], game, progress, SCENE)  # every Fire card spent


def test_a_hidden_choice_is_refused_by_the_server(catalogs):
    game = _begun(catalogs)
    with pytest.raises(SideQuestError, match="isn't on offer"):
        _adv(catalogs, game, "dwarf")


def test_a_plain_choice_moves_to_the_next_passage(catalogs):
    game = _begun(catalogs)
    step = _adv(catalogs, game, "go")
    assert step.passage_id == "p2" and not step.finished
    assert game["sideQuests"]["SQ1"]["passageId"] == "p2"
    assert game["sideQuests"]["SQ1"]["history"] == ["go"]


def test_flags_set_by_one_choice_unlock_another(catalogs):
    game = _begun(catalogs)
    _adv(catalogs, game, "fire")
    assert "lit" in game["sideQuests"]["SQ1"]["flags"]
    step = _adv(catalogs, game, "seen")
    assert step.finished and step.outcome == "success"


# ---- tests (dice) ----


def test_a_combat_dice_test_needs_the_skull_report(catalogs):
    game = _begun(catalogs)
    _adv(catalogs, game, "go")
    with pytest.raises(SideQuestError, match="report the skulls"):
        _adv(catalogs, game, "leap")
    with pytest.raises(SideQuestError):
        _adv(catalogs, game, "leap", report={"skulls": 5})


def test_enough_skulls_takes_the_success_branch(catalogs):
    game = _begun(catalogs)
    _adv(catalogs, game, "go")
    step = _adv(catalogs, game, "leap", report={"skulls": 1})
    assert step.finished and step.outcome == "success"
    assert game["pendingSideQuest"] is None
    assert game["sideQuests"]["SQ1"]["status"] == "success"
    assert any("40 gold" in line for line in step.log)


def test_too_few_skulls_takes_the_failure_branch(catalogs):
    game = _begun(catalogs)
    _adv(catalogs, game, "go")
    step = _adv(catalogs, game, "leap", report={"skulls": 0})
    assert step.passage_id == "p3" and not step.finished


def test_a_mind_test_is_reported_as_pass_or_fail(catalogs):
    scene = copy.deepcopy(SCENE)
    scene["passages"]["p2"]["choices"][0]["test"] = {"kind": "mind", "dice": 0, "needSkulls": 0, "success": "t_win", "failure": "t_lose"}
    quest = {**QUEST, "sideQuests": [scene]}
    game = _game()
    begin_side_quest(board=catalogs.board, quest=quest, game_state=game, sq_id="SQ1")
    _adv(catalogs, game, "go", quest=quest)
    with pytest.raises(SideQuestError, match="Mind Point"):
        _adv(catalogs, game, "leap", quest=quest)
    step = _adv(catalogs, game, "leap", report={"passed": False}, quest=quest)
    assert step.outcome == "failure"


def test_a_zargon_test_is_rolled_by_the_app(catalogs):
    scene = copy.deepcopy(SCENE)
    scene["passages"]["p2"]["choices"][0]["test"] = {"kind": "zargon", "dice": 3, "needSkulls": 1, "success": "t_win", "failure": "t_lose"}
    quest = {**QUEST, "sideQuests": [scene]}
    outcomes = set()
    for seed in range(20):
        game = _game()
        begin_side_quest(board=catalogs.board, quest=quest, game_state=game, sq_id="SQ1")
        _adv(catalogs, game, "go", quest=quest)
        step = _adv(catalogs, game, "leap", seed=seed, quest=quest)
        assert step.finished
        outcomes.add(step.outcome)
        assert any("Zargon rolls 3 combat dice" in line for line in step.log)
    assert outcomes == {"success", "failure"}


# ---- retry ----


def test_the_retry_edge_is_offered_once_and_costs_what_it_says(catalogs):
    game = _begun(catalogs)
    _adv(catalogs, game, "go")
    _adv(catalogs, game, "leap", report={"skulls": 0})  # -> p3
    step = _adv(catalogs, game, "again")  # the retry edge
    assert step.passage_id == "p2"
    assert game["sideQuests"]["SQ1"]["retried"] is True
    assert any("costs 1 Body Point" in line for line in step.log)
    _adv(catalogs, game, "leap", report={"skulls": 0})  # -> p3 again
    with pytest.raises(SideQuestError, match="isn't on offer"):
        _adv(catalogs, game, "again")


# ---- effects ----


def _finish_with(catalogs, effects, kind="optional", outcome="success", game=None):
    scene = copy.deepcopy(SCENE)
    scene["kind"] = kind
    scene["terminals"]["t_win"] = {"outcome": outcome, "text": "Done.", "effects": effects}
    quest = copy.deepcopy(QUEST)
    quest["sideQuests"] = [scene]
    if kind == "required":
        quest["gate"]["sideQuestId"] = "SQ1"
    game = game or _game()
    if kind == "required":
        game["gate"]["sideQuestId"] = "SQ1"
    begin_side_quest(board=catalogs.board, quest=quest, game_state=game, sq_id="SQ1")
    _adv(catalogs, game, "go", quest=quest)
    step = _adv(catalogs, game, "leap", report={"skulls": 2}, quest=quest)
    assert step.finished
    return game, step


def test_grant_artifact_records_the_holder_and_names_the_card(catalogs):
    game, step = _finish_with(catalogs, [{"type": "grant_artifact", "artifactId": "ring_of_return", "heroId": "wizard"}])
    assert game["artifactsHeld"] == {"ring_of_return": "wizard"}
    assert step.updates["artifactsHeld.ring_of_return"] == "wizard"
    assert any("Ring of Return" in line for line in step.log)


def test_weaken_monster_changes_body_or_defend(catalogs):
    game, step = _finish_with(catalogs, [{"type": "weaken_monster", "monsterId": "M1", "stat": "body"}])
    assert game["monsters"]["M1"]["currentBody"] == 2
    game, step = _finish_with(catalogs, [{"type": "weaken_monster", "monsterId": "M1", "stat": "defend"}])
    assert game["monsters"]["M1"]["bonusDefend"] == -1
    assert step.updates["monsters.M1.bonusDefend"] == -1


def test_weaken_monster_never_kills(catalogs):
    game = _game()
    game["monsters"]["M1"]["currentBody"] = 1
    game, _ = _finish_with(catalogs, [{"type": "weaken_monster", "monsterId": "M1", "stat": "body"}], game=game)
    assert game["monsters"]["M1"]["currentBody"] == 1 and game["monsters"]["M1"]["alive"]


def test_remove_monster_takes_it_off_the_board(catalogs):
    game, step = _finish_with(catalogs, [{"type": "remove_monster", "monsterId": "M1"}])
    assert game["monsters"]["M1"]["alive"] is False
    assert step.updates["monsters.M1.alive"] is False


def test_reveal_traps_marks_the_room_as_searched_and_its_traps_as_found(catalogs):
    game, step = _finish_with(catalogs, [{"type": "reveal_traps", "room": "R2"}])
    assert game["trapsFound"]["R2-T1"] == {"type": "pit", "pos": [7, 3]}
    assert game["searched"]["R2"]["traps"] is True
    assert step.updates["searched.R2.traps"] is True


def test_reveal_secret_doors_finds_them_and_calls_for_the_tile(catalogs):
    game, step = _finish_with(catalogs, [{"type": "reveal_secret_doors", "room": "R2"}])
    assert game["doors"]["D2"] == "closed"
    assert any("secret door tile" in p for p in step.placements)


def test_spawn_wandering_adds_a_monster_and_a_placement(catalogs):
    game, step = _finish_with(catalogs, [{"type": "spawn_wandering"}])
    wanderers = [m for mid, m in game["monsters"].items() if mid.startswith("W")]
    assert len(wanderers) == 1 and wanderers[0]["type"] == "orc" and wanderers[0]["currentBody"] == 1
    assert step.placements and "orc mini" in step.placements[0]


def test_miss_turn_leaves_a_hero_dazed_for_a_turn(catalogs):
    game, step = _finish_with(catalogs, [{"type": "miss_turn", "heroId": "barbarian"}])
    entry = game["heroStatus"]["barbarian"][0]
    assert entry["status"] == "dazed" and entry["missesTurns"] == 1
    assert "heroStatus" in step.updates


def test_announcements_only_reach_the_log(catalogs):
    game, step = _finish_with(catalogs, [{"type": "announce_reward", "kind": "potion", "text": "A healing potion is yours."}])
    assert any("healing potion" in line and "hero sheet" in line for line in step.log)
    assert not any(k.startswith("heroes") for k in step.updates)


def test_armory_visit_reads_the_reminder(catalogs):
    _, step = _finish_with(catalogs, [{"type": "armory_visit"}])
    assert any("Armory is open" in line for line in step.log)


# ---- the gate ----


def test_break_gate_opens_the_ward(catalogs):
    game, step = _finish_with(catalogs, [{"type": "break_gate"}], kind="required")
    assert game["gate"]["state"] == "open"
    assert step.updates["gate.state"] == "open"
    assert not ward_blocks(game, "M1")


def test_crack_gate_on_a_ward_makes_the_boss_hittable_but_tougher(catalogs):
    game, step = _finish_with(catalogs, [{"type": "crack_gate"}], kind="required", outcome="failure")
    assert game["gate"]["state"] == "cracked"
    assert game["monsters"]["M1"]["currentBody"] == 4
    assert game["monsters"]["M1"]["bonusDefend"] == 1
    assert not ward_blocks(game, "M1")


def test_crack_gate_on_a_seal_costs_body_and_wakes_a_wanderer(catalogs):
    game = _game(gate={"kind": "seal", "targetRoom": "R2", "sideQuestId": "SQ1", "state": "closed"})
    game, step = _finish_with(catalogs, [{"type": "crack_gate"}], kind="required", outcome="failure", game=game)
    assert game["gate"]["state"] == "cracked"
    assert not seal_blocks(game)
    assert any("1 Body Point" in line for line in step.log)
    assert any(mid.startswith("W") for mid in game["monsters"])


def test_a_required_scene_can_never_end_with_the_gate_closed(catalogs):
    # The model forgot both gate effects: success still breaks it ...
    game, _ = _finish_with(catalogs, [], kind="required", outcome="success")
    assert game["gate"]["state"] == "open"
    # ... and any other outcome cracks it.
    game, _ = _finish_with(catalogs, [], kind="required", outcome="partial")
    assert game["gate"]["state"] == "cracked"


def test_an_optional_scene_leaves_the_gate_alone(catalogs):
    game, _ = _finish_with(catalogs, [], kind="optional", outcome="failure")
    assert game["gate"]["state"] == "closed"
    assert ward_blocks(game, "M1")


# ---- discovery: the Journal learns of a scene only when the party meets it ----


def test_revealing_the_room_only_asks_for_a_figure(catalogs):
    lines = npc_placements(QUEST, _game(), ["R2"])
    assert lines == ["Place a figure for Old Hessa anywhere in R2 (any robed figure)."]
    assert npc_placements(QUEST, _game(), ["R1"]) == []
    assert npc_placements(QUEST, _game(mode="traditional"), ["R2"]) == []


def test_a_hero_in_the_room_makes_the_scene_known_once(catalogs):
    game = _game()  # heroes stand in R2
    updates, log = encounter_updates(catalogs.board, QUEST, game)
    assert updates == {"sideQuests.SQ1": {"status": "known"}}
    assert game["sideQuests"]["SQ1"] == {"status": "known"}
    assert any("Old Hessa: Hessa beckons." in line and "Journal" in line for line in log)
    # Idempotent: the second visit writes nothing.
    assert encounter_updates(catalogs.board, QUEST, game) == ({}, [])


def test_a_hero_elsewhere_learns_nothing(catalogs):
    game = _game(heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "alive": True}])
    assert encounter_updates(catalogs.board, QUEST, game) == ({}, [])


def test_a_known_scene_can_be_begun_and_a_finished_one_cannot(catalogs):
    game = _game(sideQuests={"SQ1": {"status": "known"}})
    begin_side_quest(board=catalogs.board, quest=QUEST, game_state=game, sq_id="SQ1")
    assert game["sideQuests"]["SQ1"]["status"] == "active"
    assert game["sideQuests"]["SQ1"]["passageId"] == "p1"
