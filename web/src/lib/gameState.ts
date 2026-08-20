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

export interface LogEntry {
  turn: number;
  text: string;
}

export interface GameState {
  heroes: HeroToken[];
  monsters: MonsterToken[];
  revealed: Revealed;
  // The renderer (BoardView) only needs the three fields above --
  // mockGameState.ts omits the rest. A live game (see useLiveGame.ts)
  // always has them, straight off design/quest-schema.md section 4.
  questId?: string;
  phase?: "hero" | "zargon";
  status?: "in_progress" | "complete";
  /** Stage 1 of the ending: objective met, but the party still has to
   * walk back to the stairway (see main._mark_objective_if_complete). */
  objectiveComplete?: boolean;
  turn?: number;
  /** Lone-hero parties play the hero phase twice per turn (1 | 2). */
  heroPhaseSegment?: number;
  doors?: Record<string, string>;
  // treasureBy: hero ids that searched this room (one search per hero
  // per room, 1989 rulebook). treasure: legacy per-room flag from the
  // old rule -- ignored, kept only so old game docs still parse.
  searched?: Record<string, { treasure?: boolean; treasureBy?: string[]; traps?: boolean; secretDoors?: boolean }>;
  /** Squares sealed by a sprung falling block -- impassable for good. */
  collapsedSquares?: Coord[];
  /** Traps already sprung. */
  trapsTriggered?: string[];
  /** Traps the party found by searching -- known, but still armed.
   * Only found traps appear here; unfound ones stay hidden in quest data. */
  trapsFound?: Record<string, { type: string; pos: Coord }>;
  log?: LogEntry[];
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
