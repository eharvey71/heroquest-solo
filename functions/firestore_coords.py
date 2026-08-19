"""Bidirectional conversion between the canonical [x,y] (or (x,y))
coordinate pairs used throughout validator/generator/engine, and the {"x":, "y":} map
representation Firestore actually stores.

Firestore rejects arrays whose direct elements are also arrays (hit in
practice on doors[].squares and blockedSquares -- see the generateQuest
history). generate_quest's write already converts every [x,y] pair to
{"x":,"y":} uniformly, not just the technically-broken fields, for one
consistent on-disk representation. Every read of a quest or game-state
document must run through from_firestore_coords() before the result
touches validator/generator/engine code, or a door's "squares" list of
maps silently becomes garbage tuples (tuple({"x":4,"y":1}) is
("x", "y"), not (4, 1)) -- exactly the class of bug this module exists
to prevent.
"""

from __future__ import annotations


def to_firestore_coords(value):
    # Tuples count: the engine's coords ARE tuples (Coord = tuple[int,
    # int]) and reach here whenever a set of them is written out, e.g.
    # revealed.corridorSquares. Handling only lists left those tuples
    # untouched, so Firestore saw a list whose elements were arrays --
    # the exact rejection this module exists to prevent -- and the
    # callable failed with INTERNAL on the party's first corridor step.
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and all(isinstance(v, int) for v in value):
            return {"x": value[0], "y": value[1]}
        return [to_firestore_coords(v) for v in value]
    if isinstance(value, dict):
        return {k: to_firestore_coords(v) for k, v in value.items()}
    return value


def from_firestore_coords(value):
    if isinstance(value, dict):
        if set(value.keys()) == {"x", "y"} and isinstance(value.get("x"), int) and isinstance(value.get("y"), int):
            return [value["x"], value["y"]]
        return {k: from_firestore_coords(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_firestore_coords(v) for v in value]
    return value
