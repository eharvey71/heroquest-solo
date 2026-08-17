/**
 * Purely visual: the traced path as a line + step dots. Pointer handling
 * lives in BoardView -- see its coordFromEvent for why interaction is
 * centralized there instead of per-square hit targets.
 */

import type { Coord } from "../lib/board";

interface PathOverlayProps {
  cellSize: number;
  path: Coord[];
}

const PATH_COLOR = "#ffd166";

export function PathOverlay({ cellSize, path }: PathOverlayProps) {
  if (path.length === 0) return null;

  const points = path.map(([x, y]) => `${x * cellSize + cellSize / 2},${y * cellSize + cellSize / 2}`).join(" ");

  return (
    <g pointerEvents="none">
      {path.length > 1 && (
        <polyline
          points={points}
          fill="none"
          stroke={PATH_COLOR}
          strokeWidth={cellSize * 0.14}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={0.85}
        />
      )}
      {path.map(([x, y], i) => (
        <circle
          key={`${x},${y}-${i}`}
          cx={x * cellSize + cellSize / 2}
          cy={y * cellSize + cellSize / 2}
          r={cellSize * 0.1}
          fill={PATH_COLOR}
        />
      ))}
    </g>
  );
}
