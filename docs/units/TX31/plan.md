# TX31 plan

Graph: 3 (config.ts seam, additive) -> 4 (test uses it). 1, 2 and 5 are docs only.

| Commit | Files | Targeted test |
|---|---|---|
| 1 audit | docs/units/TX31/audit.md | none |
| 2 plan | docs/units/TX31/plan.md | none |
| 3 seam | apps/web/src/identity/server/config.ts | `pnpm vitest run src/identity` (apps/web) |
| 4 test | apps/web/src/identity/server/handler.test.ts | same |
| 5 measure and retro | docs/units/TX31/{audit,retro}.md | none |

Final gate: pinned `scripts/gate-dev --pr 744` once.

Premises
- P-46 (the cold import, not the test body, is the cost; measured 455 ms first vs 9-32 ms others). Blast radius: this one test file. If broken, the change is still harmless.
- `configuredAuth` is the only state needing reset (audit finding 3). Blast radius: handler.test.ts only; CRITICAL if wrong (cross-test leakage); proven by the 4 existing assertions, which cover default/incomplete/invalid env in sequence.
- The seam does not change production behaviour: it only assigns `undefined`; no caller in `src/` besides the test.
