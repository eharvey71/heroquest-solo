/**
 * Typed board model, loaded from data/board.json. Mirrors the shape of
 * functions/validator/catalogs.py's Board (room_squares / corridor_squares
 * / area_of) so the two stay conceptually in sync even though they're in
 * different languages.
 */

import rawBoard from "../data/board.json";

export type Coord = readonly [number, number];

export interface Room {
  id: string;
  label: string;
  squares: Coord[];
}

export const CORRIDOR = "CORRIDOR" as const;
export type AreaId = string | typeof CORRIDOR;

export interface Board {
  width: number;
  height: number;
  rooms: Map<string, Room>;
  corridorSquares: Set<string>;
  /** "x,y" -> room id or CORRIDOR. Squares not present are off-board (walls/void). */
  areaOf: Map<string, AreaId>;
}

export function squareKey(x: number, y: number): string {
  return `${x},${y}`;
}

export function coordKey(c: Coord): string {
  return squareKey(c[0], c[1]);
}

interface RawBoard {
  width: number;
  height: number;
  rooms: { id: string; label: string; squares: [number, number][] }[];
  corridorSquares: [number, number][];
}

function buildBoard(raw: RawBoard): Board {
  const rooms = new Map<string, Room>();
  const areaOf = new Map<string, AreaId>();

  for (const r of raw.rooms) {
    const squares: Coord[] = r.squares.map((s) => [s[0], s[1]] as const);
    rooms.set(r.id, { id: r.id, label: r.label, squares });
    for (const s of squares) {
      areaOf.set(coordKey(s), r.id);
    }
  }

  const corridorSquares = new Set<string>();
  for (const s of raw.corridorSquares) {
    const k = squareKey(s[0], s[1]);
    corridorSquares.add(k);
    areaOf.set(k, CORRIDOR);
  }

  return { width: raw.width, height: raw.height, rooms, corridorSquares, areaOf };
}

export const board: Board = buildBoard(rawBoard as RawBoard);
