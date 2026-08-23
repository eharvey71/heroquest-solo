"""Loads the static, code-owned catalogs (board, monsters, furniture) that
quests are validated against. Pure data loading — no validation logic here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CORRIDOR = "CORRIDOR"


@dataclass(frozen=True)
class Board:
    width: int
    height: int
    room_squares: dict  # room_id -> frozenset[(x, y)]
    corridor_squares: frozenset  # frozenset[(x, y)]
    area_of: dict = field(default_factory=dict)  # (x, y) -> room_id | CORRIDOR

    @property
    def room_ids(self) -> frozenset:
        return frozenset(self.room_squares.keys())

    def in_bounds(self, pos) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height


def load_board(path: Path | None = None) -> Board:
    path = path or DATA_DIR / "board.json"
    raw = json.loads(path.read_text())

    room_squares = {
        room["id"]: frozenset(tuple(sq) for sq in room["squares"])
        for room in raw["rooms"]
    }
    corridor_squares = frozenset(tuple(sq) for sq in raw["corridorSquares"])

    area_of = {}
    for room_id, squares in room_squares.items():
        for sq in squares:
            area_of[sq] = room_id
    for sq in corridor_squares:
        area_of[sq] = CORRIDOR

    return Board(
        width=raw["width"],
        height=raw["height"],
        room_squares=room_squares,
        corridor_squares=corridor_squares,
        area_of=area_of,
    )


def load_monsters(path: Path | None = None) -> dict:
    """type -> {move, attack, defend, body, mind, roomCap, threatCost}.

    threatCost is computed (attack + defend + body), not stored, per
    CLAUDE.md's Balance system definition — it can't drift from the stats.
    """
    path = path or DATA_DIR / "monsters.json"
    raw = json.loads(path.read_text())
    catalog = {}
    for name, stats in raw.items():
        catalog[name] = {
            **stats,
            "threatCost": stats["attack"] + stats["defend"] + stats["body"],
        }
    return catalog


def load_furniture(path: Path | None = None) -> dict:
    """type -> {footprint: (w, h), owned: int}."""
    path = path or DATA_DIR / "furniture.json"
    raw = json.loads(path.read_text())
    return {
        name: {"footprint": tuple(v["footprint"]), "owned": v["owned"]}
        for name, v in raw.items()
    }


def load_artifacts(path: Path | None = None) -> dict:
    """id -> {name, summary} for the ten 1989 Artifact Cards.

    Empty until the real card text is transcribed -- see data/README.md.
    An empty dict is a valid, meaningful catalog (not a loading error):
    every caller treats "no artifacts known yet" as "the mechanism stays
    dormant," the same way an empty CHAOS_SPELLS would.
    """
    path = path or DATA_DIR / "artifacts.json"
    return json.loads(path.read_text())


@dataclass(frozen=True)
class Catalogs:
    board: Board
    monsters: dict
    furniture: dict
    artifacts: dict


def load_catalogs() -> Catalogs:
    return Catalogs(
        board=load_board(),
        monsters=load_monsters(),
        furniture=load_furniture(),
        artifacts=load_artifacts(),
    )
