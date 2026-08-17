/**
 * Terrain layer: colored squares + wall lines for revealed squares only.
 * Fog of war isn't a separate overlay drawn on top -- an unrevealed
 * square simply never gets terrain, matching how the physical game
 * keeps hidden rooms secret (nothing to "uncover" visually, there's
 * nothing drawn there at all).
 */

import { useMemo } from "react";
import { CORRIDOR, type Board } from "../lib/board";
import { wallSegmentsForRevealed } from "../lib/boardGeometry";

interface BoardTerrainProps {
  board: Board;
  cellSize: number;
  revealed: ReadonlySet<string>;
}

const ROOM_FILL = "#3a3226";
const CORRIDOR_FILL = "#2a2420";
const WALL_STROKE = "#e8dfc8";

export function BoardTerrain({ board, cellSize, revealed }: BoardTerrainProps) {
  const walls = useMemo(() => wallSegmentsForRevealed(board, revealed), [board, revealed]);

  return (
    <g>
      <g>
        {[...revealed].map((key) => {
          const area = board.areaOf.get(key);
          if (area === undefined) return null;
          const [x, y] = key.split(",").map(Number);
          return (
            <rect
              key={key}
              x={x * cellSize}
              y={y * cellSize}
              width={cellSize}
              height={cellSize}
              fill={area === CORRIDOR ? CORRIDOR_FILL : ROOM_FILL}
              stroke="#00000033"
              strokeWidth={1}
            />
          );
        })}
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
    </g>
  );
}
