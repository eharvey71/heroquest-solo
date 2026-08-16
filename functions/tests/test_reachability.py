from validator.reachability import check_reachability


def test_populated_room_unreachable_without_its_door(good_quest_4h, catalogs):
    # Drop the only door into R3 (D2); nothing else connects it.
    good_quest_4h["doors"] = [d for d in good_quest_4h["doors"] if d["id"] != "D2"]
    errors = check_reachability(good_quest_4h, catalogs)
    assert any("R3 is unreachable" in e for e in errors)


def test_objective_room_unreachable_entirely(good_quest_4h, catalogs):
    good_quest_4h["doors"] = [d for d in good_quest_4h["doors"] if d["id"] != "D6"]
    errors = check_reachability(good_quest_4h, catalogs)
    assert any("R12 is unreachable" in e for e in errors)


def test_objective_only_reachable_via_secret_door_without_hint_rejected(good_quest_4h, catalogs):
    for d in good_quest_4h["doors"]:
        if d["id"] == "D6":
            d["state"] = "secret"
    errors = check_reachability(good_quest_4h, catalogs)
    assert any("only reachable through a secret door" in e for e in errors)


def test_objective_only_reachable_via_secret_door_with_valid_hint_accepted(good_quest_4h, catalogs):
    for d in good_quest_4h["doors"]:
        if d["id"] == "D6":
            d["state"] = "secret"
    # R4 is reachable via the primary graph (D1-D5), so a hint pointing
    # there satisfies "a hint exists in a room reachable without secret
    # doors."
    good_quest_4h["objective"]["secretPathHint"] = {"room": "R4", "text": "A faded map shows a hidden stair."}
    errors = check_reachability(good_quest_4h, catalogs)
    assert not any("secret door" in e for e in errors)


def test_blocked_square_on_the_only_door_severs_reachability(good_quest_4h, catalogs):
    # D6's corridor-side square is (4, 9) -- the door's only way in.
    # Blocking that exact square removes it from the graph entirely, so
    # the door becomes unusable regardless of what else the corridor
    # network connects to (R12 has no other declared door).
    good_quest_4h["blockedSquares"] = [[4, 9]]
    errors = check_reachability(good_quest_4h, catalogs)
    assert any("R12 is unreachable" in e for e in errors)
