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

export type DoorState = "open" | "closed" | "secret";

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
  objective: string;
  completionText: string;
}

/** A side-quest scene as the generator wrote it (functions/generator/
 * side_quest_schema.py, canonical shape). Immutable quest content;
 * progress through it is game state (GameState.sideQuests). */
export interface SideQuestTest {
  kind: "combat_dice" | "mind" | "body" | "zargon";
  dice: number;
  needSkulls: number;
  success: string;
  failure: string;
}
export interface SideQuestChoice {
  id: string;
  label: string;
  requiresHero?: string;
  requiresElement?: string;
  requiresFlag?: string;
  setsFlag?: string;
  next?: string;
  test?: SideQuestTest | null;
}
export interface SideQuestPassage {
  text: string;
  choices: SideQuestChoice[];
}
export interface SideQuestTerminal {
  outcome: "success" | "partial" | "failure";
  text: string;
  effects: { type: string; [k: string]: unknown }[];
}
export interface SideQuest {
  id: string;
  kind: "optional" | "required";
  title: string;
  setting: string;
  hook: { when: "prologue" | "room"; room?: string; npcName?: string; figureHint?: string; text?: string };
  gateText?: string;
  start: string;
  passages: Record<string, SideQuestPassage>;
  terminals: Record<string, SideQuestTerminal>;
  retry?: { from: string; to: string; costText?: string } | null;
}
export interface QuestGate {
  kind: "ward" | "seal";
  sideQuestId: string;
  targetMonsterId?: string;
  targetName?: string;
  targetRoom?: string;
  text?: string;
}

export interface QuestMap {
  doors: QuestDoor[];
  /** Impassable squares -- the physical blocked-square tiles. Drawn
   * only once revealed, same as any other hidden quest content. */
  blockedSquares: Coord[];
  stairway: QuestStairway | null;
  furniture: QuestFurniture[];
  narrative: QuestNarrative | null;
  /** "expanded" when the quest carries side quests; absent/"traditional"
   * otherwise. The game decides separately how it is PLAYED. */
  mode: "traditional" | "expanded";
  /** The variant the quest was GENERATED with, whether or not its
   * scenes have arrived yet -- an expanded quest whose second call
   * failed or hasn't run reads "expanded" here and "traditional" in
   * `mode`. */
  requestedMode: "traditional" | "expanded";
  /** Where the scenes stand: pending (second call not finished),
   * ready, failed (retry offered), or null for a traditional quest. */
  sideQuestsStatus: "pending" | "ready" | "failed" | null;
  sideQuestErrors: string[];
  sideQuests: SideQuest[];
  gate: QuestGate | null;
}

const EMPTY: QuestMap = {
  doors: [],
  blockedSquares: [],
  stairway: null,
  furniture: [],
  narrative: null,
  mode: "traditional",
  requestedMode: "traditional",
  sideQuestsStatus: null,
  sideQuestErrors: [],
  sideQuests: [],
  gate: null,
};

interface RawFurniture {
  type: string;
  pos: Coord;
  orientation?: "N" | "S" | "E" | "W";
}

interface RawQuestDoc {
  doors?: QuestDoor[];
  blockedSquares?: Coord[];
  stairway?: QuestStairway;
  title?: string;
  backstory?: string;
  objective?: { description?: string };
  completionText?: string;
  rooms?: Record<string, { furniture?: RawFurniture[] }>;
  mode?: "traditional" | "expanded";
  sideQuestsStatus?: "pending" | "ready" | "failed";
  sideQuestErrors?: string[];
  sideQuests?: SideQuest[];
  gate?: QuestGate;
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

/** `version` re-fetches the same quest: the setup screen bumps it once
 * generateSideQuests has written the scenes onto a quest already
 * loaded. */
export function useQuestMap(questId: string | undefined, version = 0): QuestMap {
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
        blockedSquares: raw.blockedSquares ?? [],
        stairway: raw.stairway ?? null,
        furniture: extractFurniture(raw.rooms),
        mode: raw.mode === "expanded" && (raw.sideQuests?.length ?? 0) > 0 ? "expanded" : "traditional",
        requestedMode: raw.mode === "expanded" ? "expanded" : "traditional",
        sideQuestsStatus: raw.mode === "expanded" ? (raw.sideQuestsStatus ?? "pending") : null,
        sideQuestErrors: raw.sideQuestErrors ?? [],
        sideQuests: raw.sideQuests ?? [],
        gate: raw.gate ?? null,
        narrative:
          raw.title || raw.backstory
            ? {
                title: raw.title ?? "",
                backstory: raw.backstory ?? "",
                objective: raw.objective?.description ?? "",
                completionText: raw.completionText ?? "",
              }
            : null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [questId, version]);

  return map;
}
