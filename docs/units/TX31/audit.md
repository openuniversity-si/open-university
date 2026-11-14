# TX31 audit: identity handler.test.ts timeout at the cause

Status: skeleton (findings are added as they are verified on base 891b835ae).

## Evidence re-verified on base
- apps/web/src/identity/server/handler.test.ts:8 `vi.resetModules()` in `beforeEach`; :15, :24, :36, :48 `await import("./handler.ts")` inside each test. Holds.
- apps/web/src/identity/server/config.ts:153 `let configuredAuth`, :163 `configuredAuth ??= createTowerAuth(...)`. The cache is the only module-level state in config.ts, deps.ts, mailer.ts and handler.ts (grep `^let|??=`). Holds (cited lines 153-165 are now 153-165).

## Findings
1. Cold load inside the timer: `handler.test.ts` reloads the module graph in `beforeEach` (`vi.resetModules()`, :8) and dynamic-imports `./handler.ts` in every test (:15, :24, :36, :48), so better-auth, `better-auth/api`, `better-auth/next-js` and the db modules load inside the first test's 5 s window.
2. Why the reset exists: `config.ts:153` caches `configuredAuth` at module level and `getAuth()` (:163) builds it once, so tests with different env would otherwise share one instance.
3. `configuredAuth` is the only module-level state in `config.ts`, `deps.ts`, `mailer.ts`, `handler.ts` (grep `^let|??=|cache`); the other three tests rely on a fresh module only for it.
4. Baseline, base 891b835ae, unloaded, first test (5 runs): 455, 271, 473, 275, 290 ms; 4 tests pass.
5. No other identity test uses `resetModules`; no existing test-seam naming convention in `src/` (grep `ForTest|__test`), so the seam is named `resetAuthForTests`.

## Measurements (first test, "returns an anonymous session…", vitest verbose)
Unloaded, 5 runs: before 455, 271, 473, 275, 290 ms; after 5, 5, 5, 5, 5 ms.
Loaded (2 busy loops per CPU, `before` run from an untracked copy of the base file), 5 runs: before 747, 707, 595, 699, 542 ms; after 5, 12, 14, 9, 6 ms.
Assertions: `expect(` count 13 before, 13 after; tests 4 before, 4 after; `pnpm vitest run src/identity` 75 passed (75) before and after.
Timeout check: `git diff origin/mod/roadmap-integration...HEAD | grep -nE '^[+-].*(timeout|_s"|_ms"|threshold)'` matches one line, the title of this file ("identity handler.test.ts timeout at the cause"); no config or test timeout changed.
