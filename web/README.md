# web/

React + TypeScript + Vite. `npm run dev` for local dev, `npm run build`
outputs to `dist/` (what `firebase deploy` serves).

- `src/data/board.json` — synced from `design/board.json`; `src/lib/board.ts`
  loads it into a typed model (mirrors `functions/validator/catalogs.py`'s
  Board: room squares, corridor squares, per-square area lookup).
- `src/components/BoardTerrain.tsx` — the grid + walls, gated by fog of
  war: an unrevealed square renders nothing at all, not a grayed-out
  placeholder, matching how the physical game keeps hidden rooms secret.
- `src/components/Tokens.tsx` — hero/monster tokens, also fog-gated for
  monsters (heroes are always visible to their own party).
- `src/components/BoardView.tsx` + `src/hooks/usePathInput.ts` — movement
  path input (click a hero, then click/drag across adjacent squares).
  Per CLAUDE.md: movement is entered as a traced path, not a roll total,
  so traps can trigger mid-move and Zargon always knows hero positions.
  `BoardView`'s `onConfirmMove` callback isn't wired to anything yet —
  there's no movement-resolution backend until Task 5 (Zargon engine).
- `src/lib/mockGameState.ts` — local dev fixture (`App.tsx` renders it
  directly) until a real Firestore-backed game state exists.
