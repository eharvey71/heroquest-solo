/**
 * The quests generated so far and the games started from them.
 *
 * A quest is immutable once generated (see useQuestMap), so replaying
 * one costs nothing but a createGame call -- there was simply no way to
 * name an old questId from the UI, which meant generating a fresh quest
 * for every single test run. Both lists are one-time fetches, newest
 * first, refreshed by bumping `refreshKey`.
 */

import { collection, getDocs, limit, orderBy, query } from "firebase/firestore";
import { useEffect, useState } from "react";
import { db } from "./firebase";

const QUEST_LIMIT = 25;
const GAME_LIMIT = 15;

export interface QuestSummary {
  id: string;
  title: string;
  objective: string;
  heroCount: number | null;
  difficulty: string | null;
  size: string | null;
  theme: string | null;
  createdAt: Date | null;
  /** Hidden from the setup screen's list, but never deleted -- see
   * lib/archive.ts. Removing a quest archives its games with it. */
  archived: boolean;
}

export interface GameSummary {
  id: string;
  questId: string | null;
  questTitle: string | null;
  heroNames: string[];
  turn: number;
  status: string;
  objectiveComplete: boolean;
  createdAt: Date | null;
  /** Bumped by every mutating action (main._push_undo) and by undo
   * itself -- when the game was last actually played, not just
   * started. Falls back to createdAt for a game with no actions yet,
   * or one from before this field existed. */
  lastActionAt: Date | null;
  /** A finished game gets its chronicle written automatically; this is
   * whether that has happened yet -- only games with one can be named
   * as a campaign's predecessor (generateQuest's continuesFromGameId). */
  hasChronicle: boolean;
  /** Hidden from the setup screen's list, but never deleted -- see
   * lib/archive.ts. */
  archived: boolean;
}

export interface Library {
  quests: QuestSummary[];
  games: GameSummary[];
  loading: boolean;
  error: string | null;
}

function toDate(value: unknown): Date | null {
  // Firestore Timestamp, or null while a serverTimestamp() write is
  // still pending on the server.
  const ts = value as { toDate?: () => Date } | null | undefined;
  return typeof ts?.toDate === "function" ? ts.toDate() : null;
}

export function useLibrary(refreshKey = 0): Library {
  const [library, setLibrary] = useState<Library>({ quests: [], games: [], loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    setLibrary((prev) => ({ ...prev, loading: true, error: null }));

    Promise.all([
      getDocs(query(collection(db, "quests"), orderBy("createdAt", "desc"), limit(QUEST_LIMIT))),
      getDocs(query(collection(db, "games"), orderBy("createdAt", "desc"), limit(GAME_LIMIT))),
    ])
      .then(([questSnap, gameSnap]) => {
        if (cancelled) return;

        const quests: QuestSummary[] = questSnap.docs.map((d) => {
          const data = d.data() as Record<string, never> & {
            title?: string;
            objective?: { description?: string };
            generationParams?: { heroCount?: number; difficulty?: string; size?: string; theme?: string };
            createdAt?: unknown;
            archived?: boolean;
          };
          const params = data.generationParams ?? {};
          return {
            id: d.id,
            title: data.title ?? "(untitled quest)",
            objective: data.objective?.description ?? "",
            heroCount: params.heroCount ?? null,
            difficulty: params.difficulty ?? null,
            size: params.size ?? null,
            theme: params.theme ?? null,
            createdAt: toDate(data.createdAt),
            archived: Boolean(data.archived),
          };
        });

        const titleById = new Map(quests.map((q) => [q.id, q.title]));
        const games: GameSummary[] = gameSnap.docs.map((d) => {
          const data = d.data() as {
            questId?: string;
            heroes?: { name?: string; id?: string }[];
            turn?: number;
            status?: string;
            objectiveComplete?: boolean;
            createdAt?: unknown;
            lastActionAt?: unknown;
            chronicle?: string;
            archived?: boolean;
          };
          return {
            id: d.id,
            questId: data.questId ?? null,
            // Only the most recent quests are fetched, so an old game's
            // quest may not be in the map -- the id still identifies it.
            questTitle: data.questId ? titleById.get(data.questId) ?? null : null,
            heroNames: (data.heroes ?? []).map((h) => h.name || h.id || "?").filter(Boolean),
            turn: data.turn ?? 1,
            status: data.status ?? "in_progress",
            objectiveComplete: Boolean(data.objectiveComplete),
            createdAt: toDate(data.createdAt),
            // Absent on a game with no actions yet, or one from before
            // this field existed -- created is the only date it has.
            lastActionAt: toDate(data.lastActionAt) ?? toDate(data.createdAt),
            hasChronicle: Boolean(data.chronicle),
            archived: Boolean(data.archived),
          };
        });

        setLibrary({ quests, games, loading: false, error: null });
      })
      .catch((e) => {
        if (cancelled) return;
        setLibrary({ quests: [], games: [], loading: false, error: e instanceof Error ? e.message : String(e) });
      });

    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  return library;
}
