/**
 * Terrain layer: the full board (every room + corridor, always), doors,
 * and the stairway marker.
 *
 * The physical board is entirely physical (CLAUDE.md's boundary) -- the
 * owner already has the whole printed layout, room shapes, and floor
 * textures sitting on their table, at all times, whether or not the
 * party has explored a given room yet. Hiding room GEOMETRY behind fog
 * of war (an earlier version of this component did exactly that) was a
 * mistake: it gave the player nothing to visually match against the
 * physical board and no way to tell which room they're looking at.
 * Every room renders its label (the same floor-texture description
 * board.json already carries, e.g. "wood parquet" -- these are the
 * player's actual landmark for finding a room on their table) at all
 * times. Unrevealed rooms just render dimmer, to still distinguish
 * "explored" from "not yet" without hiding the room's existence.
 *
 * What genuinely stays hidden until discovered: doors (quest-owned
 * overlay tiles -- the 1989 board has no printed doorways at all, so
 * there's nothing physical to see until the app reveals one) and
 * monster/trap contents (rendered by sibling layers, gated on
 * `revealed` same as before). The stairway is the one placed-tile
 * exception that's always shown regardless of `revealed` -- it's set
 * up before turn 1 begins, not discovered mid-quest.
 */

import { useMemo } from "react";
import { CORRIDOR, type Board, type Coord } from "../lib/board";
import { edgeBetween, segmentKey, wallSegmentsForRevealed } from "../lib/boardGeometry";
import type { QuestDoor, QuestStairway } from "../lib/useQuestMap";

interface BoardTerrainProps {
  board: Board;
  cellSize: number;
  revealed: ReadonlySet<string>;
  doors?: QuestDoor[];
  stairway?: QuestStairway | null;
}

const ROOM_FILL = "#3a3226";
const ROOM_FILL_UNREVEALED = "#231f19";
const CORRIDOR_FILL = "#2a2420";
const CORRIDOR_FILL_UNREVEALED = "#1c1916";
const WALL_STROKE = "#e8dfc8";
const LABEL_FILL_REVEALED = "#c9bfa0";
const LABEL_FILL_UNREVEALED = "#5a5347";
const STAIRWAY_STROKE = "#e8c34a";
const DOOR_COLORS: Record<string, string> = {
  open: "#7fd67f",
  closed: "#d69a4a",
  locked: "#c23b3b",
};

export function BoardTerrain({ board, cellSize, revealed, doors = [], stairway }: BoardTerrainProps) {
  const allSquareKeys = useMemo(() => new Set(board.areaOf.keys()), [board]);

  const visibleDoors = useMemo(
    () => doors.filter((d) => d.state !== "secret" && d.squares.some((sq) => revealed.has(`${sq[0]},${sq[1]}`))),
    [doors, revealed]
  );

  const doorEdgeKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const d of visibleDoors) {
      const seg = edgeBetween(d.squares[0], d.squares[1]);
      keys.add(segmentKey(seg.x1, seg.y1, seg.x2, seg.y2));
    }
    return keys;
  }, [visibleDoors]);

  // Walls render for the WHOLE board -- geometry is always visible, per
  // the module doc above -- not just currently-revealed squares.
  const walls = useMemo(
    () => wallSegmentsForRevealed(board, allSquareKeys, doorEdgeKeys),
    [board, allSquareKeys, doorEdgeKeys]
  );

  const roomLabelAnchors = useMemo(() => {
    const anchors: { roomId: string; label: string; pos: Coord }[] = [];
    for (const room of board.rooms.values()) {
      const anchor = room.squares.reduce((best, sq) => (sq[1] < best[1] || (sq[1] === best[1] && sq[0] < best[0]) ? sq : best));
      anchors.push({ roomId: room.id, label: room.label, pos: anchor });
    }
    return anchors;
  }, [board]);

  return (
    <g>
      <g>
        {[...allSquareKeys].map((key) => {
          const area = board.areaOf.get(key);
          if (area === undefined) return null;
          const isRevealed = revealed.has(key);
          const [x, y] = key.split(",").map(Number);
          const fill =
            area === CORRIDOR
              ? isRevealed
                ? CORRIDOR_FILL
                : CORRIDOR_FILL_UNREVEALED
              : isRevealed
                ? ROOM_FILL
                : ROOM_FILL_UNREVEALED;
          return (
            <rect
              key={key}
              x={x * cellSize}
              y={y * cellSize}
              width={cellSize}
              height={cellSize}
              fill={fill}
              stroke="#00000033"
              strokeWidth={1}
            />
          );
        })}
      </g>
      <g>
        {roomLabelAnchors.map(({ roomId, label, pos }) => (
          <text
            key={roomId}
            x={pos[0] * cellSize + 3}
            y={pos[1] * cellSize + cellSize * 0.6}
            fontSize={cellSize * 0.28}
            fill={revealed.has(`${pos[0]},${pos[1]}`) ? LABEL_FILL_REVEALED : LABEL_FILL_UNREVEALED}
            pointerEvents="none"
          >
            {roomId} &middot; {label}
          </text>
        ))}
      </g>
      <g>
        {walls.map((w) => (
          <line
            key={`${w.x1},${w.y1}-${w.x2},${w.y2}`}
            x1={w.x1 * cellSize}
            y1={w.y1 * cellSize}
            x2={w.x2 * cellSize}
            y2={w.y2 * cellSize}
            stroke={WALL_STROKE}
            strokeWidth={2}
            strokeLinecap="square"
          />
        ))}
      </g>
      <g>
        {visibleDoors.map((d) => {
          const seg = edgeBetween(d.squares[0], d.squares[1]);
          return (
            <line
              key={d.id}
              x1={seg.x1 * cellSize}
              y1={seg.y1 * cellSize}
              x2={seg.x2 * cellSize}
              y2={seg.y2 * cellSize}
              stroke={DOOR_COLORS[d.state] ?? WALL_STROKE}
              strokeWidth={4}
              strokeLinecap="butt"
            />
          );
        })}
      </g>
      {stairway && (
        <g pointerEvents="none">
          <rect
            x={stairway.pos[0] * cellSize + 2}
            y={stairway.pos[1] * cellSize + 2}
            width={cellSize * 2 - 4}
            height={cellSize * 2 - 4}
            fill="none"
            stroke={STAIRWAY_STROKE}
            strokeWidth={2}
            strokeDasharray="4 3"
          />
          <text
            x={stairway.pos[0] * cellSize + cellSize}
            y={stairway.pos[1] * cellSize + cellSize}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={cellSize * 0.3}
            fill={STAIRWAY_STROKE}
          >
            STAIRS
          </text>
        </g>
      )}
    </g>
  );
}
