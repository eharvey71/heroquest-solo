from engine.objective import check_objective_complete


def _quest(obj_type, target):
    return {"objective": {"type": obj_type, "target": target}}


def test_kill_boss_incomplete_while_alive():
    quest = _quest("kill_boss", {"monsterId": "M7", "room": "R4"})
    game_state = {"monsters": {"M7": {"alive": True}}}
    assert check_objective_complete(quest, game_state) is False


def test_kill_boss_complete_once_dead():
    quest = _quest("kill_boss", {"monsterId": "M7", "room": "R4"})
    game_state = {"monsters": {"M7": {"alive": False}}}
    assert check_objective_complete(quest, game_state) is True


def test_kill_boss_incomplete_if_monster_not_in_game_state():
    quest = _quest("kill_boss", {"monsterId": "M7", "room": "R4"})
    assert check_objective_complete(quest, {"monsters": {}}) is False


def test_kill_boss_missing_monster_id_never_completes():
    quest = _quest("kill_boss", {"room": "R4"})
    game_state = {"monsters": {"M7": {"alive": False}}}
    assert check_objective_complete(quest, game_state) is False


def test_reach_exit_incomplete_until_room_revealed():
    quest = _quest("reach_exit", {"room": "R15"})
    game_state = {"revealed": {"rooms": ["R1"]}}
    assert check_objective_complete(quest, game_state) is False


def test_reach_exit_complete_once_room_revealed():
    quest = _quest("reach_exit", {"room": "R15"})
    game_state = {"revealed": {"rooms": ["R1", "R15"]}}
    assert check_objective_complete(quest, game_state) is True


def test_find_artifact_uses_same_room_reached_trigger():
    quest = _quest("find_artifact", {"room": "R22"})
    game_state = {"revealed": {"rooms": ["R22"]}}
    assert check_objective_complete(quest, game_state) is True


def test_rescue_uses_same_room_reached_trigger():
    quest = _quest("rescue", {"room": "R16"})
    game_state = {"revealed": {"rooms": ["R16"]}}
    assert check_objective_complete(quest, game_state) is True


def test_missing_target_room_never_completes():
    quest = _quest("reach_exit", {})
    game_state = {"revealed": {"rooms": ["R1"]}}
    assert check_objective_complete(quest, game_state) is False
