# TX30 plan

Graph: 1 -> 3, 2 -> 3 (1 and 2 independent; 3 is docs).

| # | Commit | Files | Targeted tests |
|---|---|---|---|
| 1 | sync.test.ts: `sparseFile` (writeFileSync "" + truncateSync n), `privateDir` + `afterEach` rmSync | apps/web/scripts/lib/catalog-cli/sync.test.ts | `pnpm vitest run scripts/lib/catalog-cli/sync.test.ts` |
| 2 | absolute-literals.test.ts: scope root registered for `afterEach` cleanup instead of try/finally | apps/web/scripts/lib/absolute-literals.test.ts | `pnpm vitest run scripts/lib/absolute-literals.test.ts` |
| 3 | docs/units/TX30: audit, plan, measurements, retro | docs/units/TX30/* | none |

Single final gate: pinned `scripts/gate-dev --pr 753`.

## Premises
- P-46 (the PR trailer premise). Blast radius: two test files, no production code.
- A sparse file gives `statSync().size == n` on the CI filesystem (tmpfs or ext4). CRITICAL for commit 1; proved by the tests passing with exact-size assertions.
- No new literal values: `covers-`, `snapshot-`, `absolute-scope-` already existed; literal census equals its list.
