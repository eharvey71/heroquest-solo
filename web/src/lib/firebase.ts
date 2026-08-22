/**
 * Firebase client bootstrap. apiKey here is the public web API key
 * Firebase expects embedded in client code -- it identifies the
 * project, it isn't a secret; access is gated by firestore.rules and
 * the owner check in functions/owner.py.
 *
 * Single-owner app: sign-in is Google, and the account that signs in
 * first CLAIMS the app by writing config/owner. After that the claim is
 * immutable and everything else in Firestore is readable only by that
 * uid (firestore.rules). Anonymous sign-in used to stand in for a login
 * screen; it also meant anyone with the URL could list the owner's
 * games and spend the owner's Anthropic key on quest generation.
 */

import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  type User,
  getAuth,
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
} from "firebase/auth";
import { doc, getDoc, getFirestore, serverTimestamp, setDoc } from "firebase/firestore";
import { getFunctions } from "firebase/functions";

const firebaseConfig = {
  projectId: "hq-zargon-solo",
  appId: "1:491946016614:web:b1d2714528f77509a052a7",
  storageBucket: "hq-zargon-solo.firebasestorage.app",
  apiKey: "AIzaSyApjPkuUp9vOjhJspT2XxaaDFcdNd7AJyw",
  authDomain: "hq-zargon-solo.firebaseapp.com",
  messagingSenderId: "491946016614",
};

export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);
export const functions = getFunctions(app, "us-central1");

/** Fires whenever the signed-in user changes, and once on startup with
 * whatever the persisted session holds (null when signed out). */
export function watchUser(onChange: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth, onChange);
}

export function signInWithGoogle(): Promise<User> {
  const provider = new GoogleAuthProvider();
  // The owner has exactly one account and no reason to be asked twice,
  // but the chooser makes it obvious WHICH account is claiming the app.
  provider.setCustomParameters({ prompt: "select_account" });
  return signInWithPopup(auth, provider).then((result) => result.user);
}

export function signOut(): Promise<void> {
  return firebaseSignOut(auth);
}

/**
 * Claims the app for this account if nobody has yet.
 *
 * The rules allow exactly one create of config/owner, only naming the
 * caller, and no update or delete afterwards -- so this is safe to call
 * on every sign-in: it either writes the claim or is refused, and being
 * refused is the normal case forever after. The refusal is swallowed
 * because a non-owner signing in is a legitimate outcome (they simply
 * can't use the app), not an error worth showing twice.
 */
export async function claimOwnershipIfUnclaimed(user: User): Promise<void> {
  try {
    await setDoc(doc(db, "config", "owner"), {
      uid: user.uid,
      email: user.email ?? null,
      claimedAt: serverTimestamp(),
    });
  } catch {
    // Already claimed (by this account or another) -- nothing to do.
  }
}

/**
 * Claims the app if it is unclaimed, then reports whether this account
 * owns it.
 *
 * Ownership is established by what Firestore will let the account do,
 * not by comparing uids in the client: config/owner is readable only by
 * the owner (firestore.rules), so a successful read IS the proof. That
 * keeps the client honest -- there is no string it can lie about.
 */
export async function verifyOwnership(user: User): Promise<boolean> {
  await claimOwnershipIfUnclaimed(user);
  try {
    const snapshot = await getDoc(doc(db, "config", "owner"));
    return snapshot.exists();
  } catch {
    return false; // permission denied: someone else got here first
  }
}
