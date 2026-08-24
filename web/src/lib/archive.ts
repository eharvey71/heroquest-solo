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

import { collection, doc, getDocs, query, updateDoc, where, writeBatch } from "firebase/firestore";
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
