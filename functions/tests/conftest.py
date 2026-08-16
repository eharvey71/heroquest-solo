import copy
import json
from pathlib import Path

import pytest

from validator.catalogs import load_catalogs

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def catalogs():
    return load_catalogs()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def good_quest_4h():
    """4-hero, full-size quest. Deep-copied per test so mutations in one
    test never leak into another."""
    return copy.deepcopy(load_fixture("good_4h_full.json"))


@pytest.fixture
def good_quest_4h_params():
    return {"heroCount": 4, "difficulty": "standard", "size": "full"}


@pytest.fixture
def good_quest_1h():
    """1-hero, short-size quest, deliberately built at several caps'
    exact boundaries (room-cap, wandering-monster cost, MIN_DEPTH)."""
    return copy.deepcopy(load_fixture("good_1h_short.json"))


@pytest.fixture
def good_quest_1h_params():
    return {"heroCount": 1, "difficulty": "standard", "size": "short"}
