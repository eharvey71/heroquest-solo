"""Cordons the play area off with blocked-square tiles.

The official quests don't let the party wander the whole 26x19 board:
the printed maps fence the play area in with blocked-square tiles, so
corridors leading nowhere the quest uses are simply sealed. A generated
quest that populates 4 rooms out of 22 has the same problem in reverse
-- without a cordon the party can walk all 148 corridor squares looking
for content that isn't there.

The model does NOT place these. Sealing a corridor network is a graph
cut, and this board's corridors are a loop (a border ring plus cross
passages), so no single square ever seals a branch on its own -- a fence
is a SET of squares cut simultaneously, which an LLM is bad at and code
is good at. The pipeline therefore asks the model for no blockedSquares
at all (generator/prompt.py) and computes them here once a quest has
passed validation.

Method:
1. Skeleton -- the stairway, every square the quest needs (populated
   rooms, the objective room, both sides of every declared door,
   corridor traps) and the shortest paths joining them. Never cut, and
   connected to the stairway by construction, so no fence can strand
   anything the quest uses.
2. Sink -- everything reachable that lies more than `d` steps beyond the
   skeleton. That is the roaming space.
3. Minimum vertex cut between the two (max-flow on a split-node graph,
   corridor squares capacity 1, everything else infinite). Walk `d` out
   from 1 until the cut fits the tiles in the box: the smallest `d` that
   fits is the tightest fence the owner can actually build.

Tile budget is physical and small (8 single + 2 double = 12 squares), so
a fence that doesn't fit is no fence at all -- better an open board than
an instruction the owner can't follow.
"""

from __future__ import annotations

from collections import deque

from validator.balance import BLOCKED_SQUARE_CAP, blocked_squares_fit_tiles
from validator.catalogs import CORRIDOR, Catalogs
from validator.geometry import footprint_cells, furniture_squares
from validator.reachability import (
    NON_SECRET_STATES,
    _bfs,
    _door_edges,
    _objective_target_room,
)

Coord = tuple[int, int]

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))

# Sealing a 3-square alcove costs the same tile as sealing a wing, and
# the tiles don't recycle. Below this, leave the board open.
MIN_SEALED_SQUARES = 8

# How far past the quest's own squares the fence may sit. Beyond this the
# "fence" is so far out it isn't fencing anything.
MAX_HALO = 12

_INF = 1 << 30


def _neighbours(board, sq: Coord, door_edges) -> list[Coord]:
    """Orthogonal steps a figure could take: same area, or a declared
    door on that exact edge. Same rule as validator.reachability._bfs.
    """
    area = board.area_of.get(sq)
    out = []
    for dx, dy in _STEPS:
        n = (sq[0] + dx, sq[1] + dy)
        n_area = board.area_of.get(n)
        if n_area is None:
            continue
        if n_area == area or frozenset((sq, n)) in door_edges:
            out.append(n)
    return out


def _required_squares(quest: dict, board, reached: set[Coord]) -> set[Coord]:
    """Everything the party must still be able to walk to: every square
    of every populated room, the objective room, both sides of every
    declared door, and every corridor trap. Intersected with what was
    reachable before fencing, so furniture that already walled a square
    off doesn't become the fence's problem.
    """
    required: set[Coord] = set()
    for room_id in quest.get("rooms", {}):
        squares = board.room_squares.get(room_id)
        if squares:
            required |= squares
    objective_room = _objective_target_room(quest, board)
    if objective_room in board.room_squares:
        required |= board.room_squares[objective_room]
    for door in quest.get("doors", []):
        squares = door.get("squares", [])
        if len(squares) == 2:
            required.update(tuple(sq) for sq in squares)
    for trap in quest.get("corridorTraps", []):
        pos = trap.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            required.add(tuple(pos))
    return required & reached


def _skeleton(board, door_edges, blocked, start_cells, required: set[Coord]) -> set[Coord]:
    """The stairway, the required squares, and the shortest paths joining
    them -- the part of the board the quest actually needs walkable.
    """
    start = [c for c in start_cells if c not in blocked]
    parent: dict[Coord, Coord | None] = {c: None for c in start}
    q = deque(start)
    while q:
        cur = q.popleft()
        for n in _neighbours(board, cur, door_edges):
            if n in parent or n in blocked:
                continue
            parent[n] = cur
            q.append(n)

    keep = set(parent) & required
    keep |= set(start)
    for square in list(keep):
        node = square
        while node is not None:
            keep.add(node)
            node = parent.get(node)
    return keep


def _distance_from(board, door_edges, blocked, sources: set[Coord]) -> dict[Coord, int]:
    dist = {sq: 0 for sq in sources}
    q = deque(sources)
    while q:
        cur = q.popleft()
        for n in _neighbours(board, cur, door_edges):
            if n in dist or n in blocked:
                continue
            dist[n] = dist[cur] + 1
            q.append(n)
    return dist


class _MaxFlow:
    """Dinic. The graph is ~1000 nodes and the flow value is bounded by
    the tile budget, so this never has to be clever.
    """

    def __init__(self, size: int):
        self.adj: list[list[int]] = [[] for _ in range(size)]
        self.to: list[int] = []
        self.cap: list[int] = []

    def add_edge(self, u: int, v: int, cap: int) -> None:
        self.adj[u].append(len(self.to))
        self.to.append(v)
        self.cap.append(cap)
        self.adj[v].append(len(self.to))
        self.to.append(u)
        self.cap.append(0)

    def _levels(self, s: int, t: int) -> list[int] | None:
        level = [-1] * len(self.adj)
        level[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for e in self.adj[u]:
                v = self.to[e]
                if self.cap[e] > 0 and level[v] < 0:
                    level[v] = level[u] + 1
                    q.append(v)
        return level if level[t] >= 0 else None

    def _augment(self, u: int, t: int, flow: int, level, it) -> int:
        if u == t:
            return flow
        while it[u] < len(self.adj[u]):
            e = self.adj[u][it[u]]
            v = self.to[e]
            if self.cap[e] > 0 and level[v] == level[u] + 1:
                pushed = self._augment(v, t, min(flow, self.cap[e]), level, it)
                if pushed:
                    self.cap[e] -= pushed
                    self.cap[e ^ 1] += pushed
                    return pushed
            it[u] += 1
        return 0

    def max_flow(self, s: int, t: int, limit: int) -> int:
        total = 0
        while total <= limit:
            level = self._levels(s, t)
            if level is None:
                break
            it = [0] * len(self.adj)
            while True:
                pushed = self._augment(s, t, _INF, level, it)
                if not pushed:
                    break
                total += pushed
                if total > limit:
                    return total
        return total

    def source_side(self, s: int) -> set[int]:
        seen = {s}
        q = deque([s])
        while q:
            u = q.popleft()
            for e in self.adj[u]:
                v = self.to[e]
                if self.cap[e] > 0 and v not in seen:
                    seen.add(v)
                    q.append(v)
        return seen


def _min_vertex_cut(
    board,
    door_edges,
    region: set[Coord],
    sources: set[Coord],
    sinks: set[Coord],
    cuttable: set[Coord],
    limit: int,
) -> list[Coord] | None:
    """Smallest set of `cuttable` squares whose removal disconnects
    `sinks` from `sources` inside `region`, or None if that needs more
    than `limit` squares. Split-node max-flow: each square is an in-node
    and an out-node joined by an edge of capacity 1 (cuttable) or
    infinity (not), so a finite cut can only consist of squares.
    """
    index = {sq: i for i, sq in enumerate(sorted(region))}
    n = len(index)
    flow = _MaxFlow(2 * n + 2)
    source, sink = 2 * n, 2 * n + 1

    for sq, i in index.items():
        flow.add_edge(2 * i, 2 * i + 1, 1 if sq in cuttable else _INF)
        for nb in _neighbours(board, sq, door_edges):
            j = index.get(nb)
            if j is not None:
                flow.add_edge(2 * i + 1, 2 * j, _INF)
    for sq in sources:
        flow.add_edge(source, 2 * index[sq], _INF)
    for sq in sinks:
        flow.add_edge(2 * index[sq] + 1, sink, _INF)

    if flow.max_flow(source, sink, limit) > limit:
        return None

    reachable = flow.source_side(source)
    return sorted(
        sq for sq, i in index.items()
        if sq in cuttable and 2 * i in reachable and 2 * i + 1 not in reachable
    )


def compute_fence(quest: dict, catalogs: Catalogs, *, budget: int = BLOCKED_SQUARE_CAP) -> list[Coord]:
    """Blocked squares fencing this quest's play area in. Returns [] when
    there is nothing worth sealing, or when no fence fits the tiles.
    """
    board = catalogs.board
    stairway = quest.get("stairway") or {}
    if stairway.get("room") not in board.room_squares or "pos" not in stairway:
        return []  # malformed quest; the validator reports it

    start_cells = footprint_cells(tuple(stairway["pos"]), (2, 2))
    # Secret doors count as passable: the party can find them, so a fence
    # must not assume a route stays shut.
    door_edges = _door_edges(quest, NON_SECRET_STATES | {"secret"})
    furniture = furniture_squares(quest, catalogs)

    region = _bfs(board, start_cells, door_edges, furniture)
    required = _required_squares(quest, board, region)
    keep = _skeleton(board, door_edges, furniture, start_cells, required)
    # Only corridor squares are ever tiled over: what happens inside a
    # room is the quest's own business, and a room the quest doesn't use
    # has no declared door to reach it by anyway.
    cuttable = {sq for sq in region if board.area_of.get(sq) == CORRIDOR} - keep

    dist = _distance_from(board, door_edges, furniture, keep)
    for halo in range(1, MAX_HALO + 1):
        sinks = {sq for sq in region if dist.get(sq, _INF) > halo}
        if not sinks:
            return []  # the quest already uses everything it can reach
        cut = _min_vertex_cut(board, door_edges, region, keep, sinks, cuttable, budget)
        if cut is None or not blocked_squares_fit_tiles(cut):
            continue
        sealed = region - _bfs(board, start_cells, door_edges, furniture | set(cut))
        if len(sealed) - len(cut) < MIN_SEALED_SQUARES:
            return []
        return cut
    return []


def apply_fence(quest: dict, catalogs: Catalogs) -> list[Coord]:
    """Sets quest["blockedSquares"] to the computed cordon and returns it.

    Replaces whatever was there: the model is told to declare none
    (generator/prompt.py), and the tile budget is far too small to spend
    on decoration the app didn't ask for.
    """
    fence = compute_fence(quest, catalogs)
    quest["blockedSquares"] = [list(sq) for sq in fence]
    return fence
