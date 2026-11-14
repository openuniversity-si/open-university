# ui-tokens: plan

Premises: P-03 (units stay logical; globals.css and the generator name these paths, medium), P-04, P-05 (layout.ts literals move to a D-063 catalog; the CSS keeps its baseline, no .css edits, low), P-07 (no export changes, high). CRITICAL: none.

Commits (each owns disjoint files):
1. `audit.md`, `plan.md`, `contract.md`.
2. `layout.ts` literals move to `vocabulary.ts`, registered in `literal-catalogs/ui.json`; `ui.json` baseline shrinks.
3. Manifest `battery.command`; `scripts/generate` outputs.
4. `retro.md` after the final gate.

One final `scripts/gate-dev --pr N`. D-069 items: 3 (layout.ts literals out), 5 (generated outputs), 8 (ownership), 14 (battery under the limit, never loosened), 15 (no text). D-067, D-029.
