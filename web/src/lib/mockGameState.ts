/**
 * Local dev-only sample game state for visually verifying the board
 * renderer before a real Firestore-backed game exists. R1/R2 are
 * revealed (heroes standing in R1, a monster in R2); R3 stays hidden to
 * demonstrate fog of war -- nothing about it should render at all.
 */

import type { GameState } from "./gameState";

export const mockGameState: GameState = {
  heroes: [
    { id: "barbarian", name: "Barbarian", pos: [2, 2], alive: true },
    { id: "wizard", name: "Wizard", pos: [3, 2], alive: true },
  ],
  monsters: [{ id: "M1", type: "orc", pos: [6, 2], currentBody: 1, alive: true }],
  revealed: {
    rooms: ["R1", "R2"],
    corridorSquares: [
      [3, 0],
      [4, 0],
      [5, 0],
    ],
  },
};
