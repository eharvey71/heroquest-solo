/**
 * Door + stairway geometry live on the quest doc (design/quest-schema.md:
 * both are quest-owned, since the 1989 board has no printed doorways or
 * fixed stairway), not the game doc -- game.doors only holds state
 * *overrides* keyed by door id. A quest never changes after generation,
 * so this is a one-time fetch, not a live subscription.
 */

import { doc, getDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import type { Coord } from "./board";
import { db } from "./firebase";
import { fromFirestoreCoords } from "./firestoreCoords";

export type DoorState = "open" | "closed" | "locked" | "secret";

export interface QuestDoor {
  id: string;
  squares: [Coord, Coord];
  state: DoorState;
}

export interface QuestStairway {
  room: string;
  pos: Coord;
}

export interface QuestMap {
  doors: QuestDoor[];
  stairway: QuestStairway | null;
}

const EMPTY: QuestMap = { doors: [], stairway: null };

export function useQuestMap(questId: string | undefined): QuestMap {
  const [map, setMap] = useState<QuestMap>(EMPTY);

  useEffect(() => {
    if (!questId) {
      setMap(EMPTY);
      return;
    }
    let cancelled = false;
    getDoc(doc(db, "quests", questId)).then((snap) => {
      if (cancelled || !snap.exists()) return;
      const raw = fromFirestoreCoords(snap.data()) as { doors?: QuestDoor[]; stairway?: QuestStairway };
      setMap({ doors: raw.doors ?? [], stairway: raw.stairway ?? null });
    });
    return () => {
      cancelled = true;
    };
  }, [questId]);

  return map;
}
