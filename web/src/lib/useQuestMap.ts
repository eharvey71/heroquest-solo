/**
 * Static, quest-owned content that lives on the quest doc rather than
 * the (live, mutable) game doc: door/stairway geometry, furniture, and
 * the narrative text (title/backstory/completionText) the LLM writes
 * per design/generator-prompt.md's STYLE section. A quest never changes
 * after generation, so this is a one-time fetch, not a live subscription.
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

export interface QuestFurniture {
  type: string;
  pos: Coord;
  orientation: "N" | "S" | "E" | "W";
  roomId: string;
}

export interface QuestNarrative {
  title: string;
  backstory: string;
  completionText: string;
}

export interface QuestMap {
  doors: QuestDoor[];
  stairway: QuestStairway | null;
  furniture: QuestFurniture[];
  narrative: QuestNarrative | null;
}

const EMPTY: QuestMap = { doors: [], stairway: null, furniture: [], narrative: null };

interface RawFurniture {
  type: string;
  pos: Coord;
  orientation?: "N" | "S" | "E" | "W";
}

interface RawQuestDoc {
  doors?: QuestDoor[];
  stairway?: QuestStairway;
  title?: string;
  backstory?: string;
  completionText?: string;
  rooms?: Record<string, { furniture?: RawFurniture[] }>;
}

function extractFurniture(rooms: RawQuestDoc["rooms"]): QuestFurniture[] {
  const items: QuestFurniture[] = [];
  for (const [roomId, room] of Object.entries(rooms ?? {})) {
    for (const f of room.furniture ?? []) {
      items.push({ type: f.type, pos: f.pos, orientation: f.orientation ?? "N", roomId });
    }
  }
  return items;
}

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
      const raw = fromFirestoreCoords(snap.data()) as RawQuestDoc;
      setMap({
        doors: raw.doors ?? [],
        stairway: raw.stairway ?? null,
        furniture: extractFurniture(raw.rooms),
        narrative:
          raw.title || raw.backstory
            ? { title: raw.title ?? "", backstory: raw.backstory ?? "", completionText: raw.completionText ?? "" }
            : null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [questId]);

  return map;
}
