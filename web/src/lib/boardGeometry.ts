/**
 * Pure geometry helpers for rendering the board: wall segments (drawn
 * wherever two adjacent squares belong to different areas, or a square
 * borders off-board void) and neighbor lookups used by path input.
 */

import { type Board, type Coord, squareKey } from "./board";

export interface WallSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** The four squares orthogonally adjacent to (x, y). HeroQuest movement
 * and line-of-sight are both orthogonal-only -- no diagonal steps. */
export function orthogonalNeighbors(x: number, y: number): Coord[] {
  return [
    [x + 1, y],
    [x - 1, y],
    [x, y + 1],
    [x, y - 1],
  ];
}

export function isOrthogonallyAdjacent(a: Coord, b: Coord): boolean {
  const dx = Math.abs(a[0] - b[0]);
  const dy = Math.abs(a[1] - b[1]);
  return dx + dy === 1;
}

/**
 * Wall segments visible from the given set of revealed squares. A wall is
 * drawn on the edge between (x,y) and its neighbor whenever the neighbor
 * is off-board or in a different area -- matches how a hero standing in a
 * room sees that room's walls without having opened the far door yet.
 */
export function wallSegmentsForRevealed(board: Board, revealed: ReadonlySet<string>): WallSegment[] {
  const segments: WallSegment[] = [];
  const seen = new Set<string>();

  const addSegment = (x1: number, y1: number, x2: number, y2: number) => {
    const key = x1 < x2 || y1 < y2 ? `${x1},${y1}-${x2},${y2}` : `${x2},${y2}-${x1},${y1}`;
    if (seen.has(key)) return;
    seen.add(key);
    segments.push({ x1, y1, x2, y2 });
  };

  for (const key of revealed) {
    const [xs, ys] = key.split(",");
    const x = Number(xs);
    const y = Number(ys);
    const area = board.areaOf.get(key);

    // East edge
    const eastKey = squareKey(x + 1, y);
    if (board.areaOf.get(eastKey) !== area) {
      addSegment(x + 1, y, x + 1, y + 1);
    }
    // South edge
    const southKey = squareKey(x, y + 1);
    if (board.areaOf.get(southKey) !== area) {
      addSegment(x, y + 1, x + 1, y + 1);
    }
    // West edge
    const westKey = squareKey(x - 1, y);
    if (board.areaOf.get(westKey) !== area) {
      addSegment(x, y, x, y + 1);
    }
    // North edge
    const northKey = squareKey(x, y - 1);
    if (board.areaOf.get(northKey) !== area) {
      addSegment(x, y, x + 1, y);
    }
  }

  return segments;
}
