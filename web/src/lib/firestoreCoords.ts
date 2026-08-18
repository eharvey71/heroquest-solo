/**
 * Client-side mirror of functions/firestore_coords.py's
 * from_firestore_coords -- Firestore stores [x,y] pairs as {x,y} maps
 * (it rejects arrays-of-arrays), so every doc read back from
 * games/{gameId} needs this before it's treated as a Coord anywhere in
 * the app. The client never writes raw game/quest docs (all writes go
 * through Cloud Functions), so no toFirestoreCoords is needed here.
 */

export function fromFirestoreCoords(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(fromFirestoreCoords);
  }
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj);
    if (
      keys.length === 2 &&
      keys.includes("x") &&
      keys.includes("y") &&
      typeof obj.x === "number" &&
      typeof obj.y === "number"
    ) {
      return [obj.x, obj.y];
    }
    const result: Record<string, unknown> = {};
    for (const k of keys) {
      result[k] = fromFirestoreCoords(obj[k]);
    }
    return result;
  }
  return value;
}
