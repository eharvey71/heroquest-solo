/**
 * Firebase client bootstrap. apiKey here is the public web API key
 * Firebase expects embedded in client code -- it identifies the
 * project, it isn't a secret; access is actually gated by
 * firestore.rules + Cloud Functions auth checks.
 *
 * Single-owner app (CLAUDE.md): firestore.rules currently allows any
 * signed-in user, with a TODO to lock to the owner's uid once a real
 * account exists. Anonymous auth satisfies that "signed in" bar today
 * without building a login screen for an app with exactly one user.
 */

import { initializeApp } from "firebase/app";
import { type User, getAuth, onAuthStateChanged, signInAnonymously } from "firebase/auth";
import { getFirestore } from "firebase/firestore";
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

let signInPromise: Promise<User> | null = null;

/** Resolves once a user (anonymous is fine) is signed in. Safe to call
 * repeatedly -- only triggers one sign-in attempt. */
export function ensureSignedIn(): Promise<User> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  if (signInPromise) return signInPromise;

  signInPromise = new Promise<User>((resolve, reject) => {
    const unsubscribe = onAuthStateChanged(
      auth,
      (user) => {
        if (user) {
          unsubscribe();
          resolve(user);
        }
      },
      (error) => {
        unsubscribe();
        reject(error);
      }
    );
    signInAnonymously(auth).catch((error) => {
      unsubscribe();
      reject(error);
    });
  });
  return signInPromise;
}
