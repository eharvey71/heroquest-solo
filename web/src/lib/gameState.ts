/**
 * Runtime game-state shapes, per design/quest-schema.md section 4. This
 * is the subset the renderer needs (positions + fog state) -- turn/phase/
 * doors/log aren't rendered by the board yet.
 */

import { type Board, type Coord, squareKey } from "./board";

export interface HeroToken {
  id: string;
  name: string;
  pos: Coord;
  active: boolean;
}

export interface MonsterToken {
  id: string;
  type: string;
  pos: Coord;
  currentBody: number;
  alive: boolean;
}

export interface Revealed {
  rooms: string[];
  corridorSquares: Coord[];
}

export interface GameState {
  heroes: HeroToken[];
  monsters: MonsterToken[];
  revealed: Revealed;
}

/** Expands revealed room ids + explicit corridor squares into the full
 * set of visible square keys, for the terrain/token fog-of-war check. */
export function revealedSquareKeys(board: Board, revealed: Revealed): Set<string> {
  const keys = new Set<string>();
  for (const roomId of revealed.rooms) {
    const room = board.rooms.get(roomId);
    if (!room) continue;
    for (const sq of room.squares) {
      keys.add(squareKey(sq[0], sq[1]));
    }
  }
  for (const sq of revealed.corridorSquares) {
    keys.add(squareKey(sq[0], sq[1]));
  }
  return keys;
}
