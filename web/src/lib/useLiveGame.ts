/**
 * Subscribes to games/{gameId} and shapes the raw Firestore doc into
 * the GameState the renderer/action buttons use. Firestore's {x,y}
 * maps get converted back to [x,y] coords, and the monsters map
 * (monsterId -> {type,pos,currentBody,alive}, keyed for O(1) lookup by
 * the engine) becomes an id-tagged array, matching MonsterToken.
 */

import { doc, onSnapshot } from "firebase/firestore";
import { useEffect, useState } from "react";
import type { Coord } from "./board";
import { db } from "./firebase";
import { fromFirestoreCoords } from "./firestoreCoords";
import type { GameState, HeroToken, LogEntry, MonsterToken } from "./gameState";

interface RawGameDoc {
  questId: string;
  phase: "hero" | "zargon";
  status?: "in_progress" | "complete" | "lost";
  objectiveComplete?: boolean;
  turn: number;
  heroPhaseSegment?: number;
  heroes: HeroToken[];
  monsters: Record<string, Omit<MonsterToken, "id">>;
  revealed: GameState["revealed"];
  doors?: Record<string, string>;
  searched?: GameState["searched"];
  collapsedSquares?: Coord[];
  spellsCast?: string[];
  trapsTriggered?: string[];
  trapsFound?: GameState["trapsFound"];
  chaosSpellsCast?: string[];
  spellbooks?: Record<string, string[]>;
  monsterStatus?: GameState["monsterStatus"];
  heroStatus?: GameState["heroStatus"];
  undoDepth?: number;
  undoLabel?: string;
  pendingDefenses?: GameState["pendingDefenses"];
  placementInstructions?: string[];
  log?: LogEntry[];
}

function toGameState(raw: RawGameDoc): GameState {
  const monsters: MonsterToken[] = Object.entries(raw.monsters ?? {}).map(([id, m]) => ({ id, ...m }));
  return {
    heroes: raw.heroes ?? [],
    monsters,
    revealed: raw.revealed ?? { rooms: [], corridorSquares: [] },
    questId: raw.questId,
    phase: raw.phase,
    status: raw.status ?? "in_progress",
    objectiveComplete: raw.objectiveComplete ?? false,
    turn: raw.turn,
    heroPhaseSegment: raw.heroPhaseSegment ?? 1,
    doors: raw.doors ?? {},
    searched: raw.searched ?? {},
    collapsedSquares: raw.collapsedSquares ?? [],
    spellsCast: raw.spellsCast ?? [],
    trapsTriggered: raw.trapsTriggered ?? [],
    trapsFound: raw.trapsFound ?? {},
    chaosSpellsCast: raw.chaosSpellsCast ?? [],
    spellbooks: raw.spellbooks ?? {},
    monsterStatus: raw.monsterStatus ?? {},
    heroStatus: raw.heroStatus ?? {},
    // Without these two the Undo button is permanently greyed out and
    // the Chaos-spell panel never appears: this function builds the
    // client's GameState field by field, so anything not named here is
    // dropped on the floor no matter what the document holds.
    undoDepth: raw.undoDepth ?? 0,
    undoLabel: raw.undoLabel,
    pendingDefenses: raw.pendingDefenses ?? [],
    placementInstructions: raw.placementInstructions ?? [],
    log: raw.log ?? [],
  };
}

export function useLiveGame(gameId: string | null) {
  const [game, setGame] = useState<GameState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(gameId !== null);

  useEffect(() => {
    if (!gameId) {
      setGame(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const unsubscribe = onSnapshot(
      doc(db, "games", gameId),
      (snap) => {
        setLoading(false);
        if (!snap.exists()) {
          setError(`game '${gameId}' not found`);
          setGame(null);
          return;
        }
        const raw = fromFirestoreCoords(snap.data()) as RawGameDoc;
        setGame(toGameState(raw));
      },
      (err) => {
        setLoading(false);
        setError(err.message);
      }
    );
    return unsubscribe;
  }, [gameId]);

  return { game, loading, error };
}
