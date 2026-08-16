# web/

Placeholder hosting root. `dist/` is what Firebase Hosting serves today
(a static stub) so `firebase deploy` and the hosting emulator have
something valid to point at.

The real app — React + SVG/Canvas board, fog of war, path input, Zargon
narration log (see CLAUDE.md Architecture) — gets scaffolded here in
Task 4 (board renderer). At that point `dist/` becomes a build output
directory (Vite or similar) rather than hand-written HTML.
