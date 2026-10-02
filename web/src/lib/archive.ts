/**
 * Archiving hides a quest or game from the setup screen's lists without
 * touching any gameplay data -- reversible (see setup screen's "Show
 * removed" toggle), and never a delete, so "remove from the list" never
 * means "abandon a play in the database".
 *
 * Direct Firestore writes, not a Cloud Function: firestore.rules already
 * lets the owner write quests/games directly (see config/owner's
 * claim-by-write for the same pattern), and flipping a visibility flag
 * has no business logic, no transaction, and nothing to validate --
 * exactly the case that boundary was already built for.
 */

import { collection, deleteDoc, doc, getDoc, getDocs, query, updateDoc, where, writeBatch } from "firebase/firestore";
import { db } from "./firebase";

export async function setGameArchived(gameId: string, archived: boolean): Promise<void> {
  await updateDoc(doc(db, "games", gameId), { archived });
}

/** "Remove the entire stack": a quest and every game played on it,
 * together. Looks up ALL of the quest's games directly (not just
 * whatever useLibrary happened to have fetched) so a quest with more
 * playthroughs than the library's page size still archives completely. */
export async function setQuestStackArchived(questId: string, archived: boolean): Promise<void> {
  const gamesSnap = await getDocs(query(collection(db, "games"), where("questId", "==", questId)));
  const batch = writeBatch(db);
  batch.update(doc(db, "quests", questId), { archived });
  for (const gameDoc of gamesSnap.docs) {
    batch.update(gameDoc.ref, { archived });
  }
  await batch.commit();
}

/*
 * PERMANENT DELETION, for the owner clearing out test quests. The
 * archived flag is the safety gate: only a quest or game that has
 * ALREADY been removed can be deleted, checked against the server copy,
 * never local state. A game's undo snapshots (games/{id}/undo) do not
 * cascade in Firestore, so they are deleted first, in batches. Still
 * direct client writes, by the same reasoning as archiving -- the rules
 * already let the owner write these documents and their subcollections.
 */

const BATCH = 400;

async function deleteUndoSnapshots(gameId: string): Promise<void> {
  const snap = await getDocs(collection(db, "games", gameId, "undo"));
  for (let i = 0; i < snap.docs.length; i += BATCH) {
    const batch = writeBatch(db);
    for (const d of snap.docs.slice(i, i + BATCH)) batch.delete(d.ref);
    await batch.commit();
  }
}

/** Deletes one REMOVED game and its undo snapshots. Refuses a live one. */
export async function deleteGameForever(gameId: string): Promise<void> {
  const ref = doc(db, "games", gameId);
  const snap = await getDoc(ref);
  if (!snap.exists()) return;
  if (snap.data().archived !== true) throw new Error("Only a removed game can be deleted. Remove it first.");
  await deleteUndoSnapshots(gameId);
  await deleteDoc(ref);
}

/** Deletes a REMOVED quest and every removed game played on it. A game
 * restored on its own keeps the quest alive: the quest is deleted only
 * once no live game points at it. Returns what was deleted. */
export async function deleteQuestStackForever(questId: string): Promise<{ quest: boolean; games: number }> {
  const ref = doc(db, "quests", questId);
  const snap = await getDoc(ref);
  if (snap.exists() && snap.data().archived !== true) {
    throw new Error("Only a removed quest can be deleted. Remove it first.");
  }
  const gamesSnap = await getDocs(query(collection(db, "games"), where("questId", "==", questId)));
  let games = 0;
  let live = 0;
  for (const g of gamesSnap.docs) {
    if (g.data().archived === true) {
      await deleteUndoSnapshots(g.id);
      await deleteDoc(g.ref);
      games += 1;
    } else {
      live += 1;
    }
  }
  const quest = snap.exists() && live === 0;
  if (quest) await deleteDoc(ref);
  return { quest, games };
}

export interface RemovedItems {
  questIds: string[];
  gameIds: string[]; // removed games, including those under live quests and orphans
}

/** Everything currently removed, from live queries rather than the
 * library's page, so the count the owner confirms before the backend
 * purge (functionsClient.purgeData) is the real one. */
export async function findRemoved(): Promise<RemovedItems> {
  const [quests, games] = await Promise.all([
    getDocs(query(collection(db, "quests"), where("archived", "==", true))),
    getDocs(query(collection(db, "games"), where("archived", "==", true))),
  ]);
  return { questIds: quests.docs.map((d) => d.id), gameIds: games.docs.map((d) => d.id) };
}
