# TX20 audit: web tests that read engine files

Base: `mod/roadmap-integration` 891b835ae (28/10 04:38Z). Every line below was re-read on that base.

## Findings

1. **The reader.** `apps/web/src/site/domain/no-github-actions.test.ts:19` reads `scripts/merge-phase` (`readFileSync(join(ROOT, "scripts/merge-phase"))`, with `ROOT` from `git rev-parse --show-toplevel` at :9). Line :15 also checks that `.github/workflows` is absent.
2. **The plan cannot see it.** `scripts/lib/gate_areas.py:430` `plan_for` builds stages only from the areas of the changed paths. `scripts/**` is the `delivery` area (`scripts/lib/gate-areas.json`: groups `script-tests`), so a diff that only touches scripts never plans `install (frozen lockfile)` or `unit tests`.
   - Replaying #722 (merge d889e6a14, 23 files) gives `unit tests: skipped (not required by engine-units, engine-config, docs, delivery)` and no web-check stage. This is audit row 1 in the program audit.
3. **The unit stage runs only when it is planned.** `scripts/lib/gate-runner.sh:150` `gate_want` runs a stage only if the dev plan lists it (`scripts/lib/gate-fixed.sh:117`). With no `unit tests` in the plan, no web test runs at all.
4. **Inside a planned stage, selection is full for engine paths.** `scripts/lib/gate_select.py:73-80` marks as `full` any path that is outside `gate.scoped_globs` (`apps/web/src/**`) and is not documentation. So once the plan lists the unit stage for a `scripts/merge-phase` change, the whole unit project runs, `no-github-actions.test.ts` included. Narrowing that run is not needed for soundness.
5. **Gap: a documentation path read by a web test.**
   - Several tests read docs:
     - `apps/web/scripts/lib/intents.test.ts:12-13` reads `docs/domain/CONTRACT.md` and `docs/domain/DECISIONS.md`.
     - `apps/web/src/catalog/domain/areas.test.ts:8` reads `docs/catalog/areas.md`.
     - `apps/web/scripts/preview-deploy.test.ts:82` reads `AGENTS.md`.
   - `gate_select.py:74` treats a documentation path as `continue`. A docs-only diff therefore selects `scoped` with no tests, and the unit stage would run only its coverage tail, not the reader.
   - Closing this needs `gate_select` to accept a test list. That file is outside TX20's files and belongs to engine-gate-plan. TX20 leaves documentation paths out (the brief's no-regression item: a docs-only diff plans exactly what it planned before). The gap is recorded here and in the retro.
6. **Read idioms in the 332 web test files.** 133 of them call a read function. The ones that reach outside `apps/web` are:
   - a repository root: `join(ROOT, "scripts/merge-phase")`, `join(repo, "scripts/tower-catalog")` (`apps/web/scripts/tower-catalog.heavy.test.ts:12`)
   - a URL relative to the test: `new URL("../../../scripts/preview-policy.json", import.meta.url)` (`apps/web/scripts/preview-deploy.test.ts:36,91`)
   - path segments: `join(app, "..", "..", "docs", "catalog", "areas.md")` (`areas.test.ts:8`)
   - a repository URL: `new URL("docs/domain/CONTRACT.md", repository)` (`apps/web/scripts/lib/contexts.test.ts:7`)
   - a helper: `read(repository, "docs/domain/DECISIONS.md")` (`intents.test.ts:13`)
   
   A static scan of string literals and segment runs, normalised and matched against the repository's top-level entries, finds all of these. Paths built from variables are not static.
7. **Which stage runs a test.** `apps/web/vitest.config.ts:84-127`:
   - `**/*.int.test.ts` runs in `integration tests`.
   - `battery.alone_globs` / `battery.alone_int_globs` (`**/*.perf.test.ts`, `**/*.heavy.test.ts`, `**/*.perf.int.test.ts`) run in `performance tests`. Its needs in `scripts/lib/gate-stages.json` are `build (production)` and `e2e smoke`.
   - Every other `*.test.ts` runs in `unit tests` (needs `install (frozen lockfile)`).
   
   So a heavy reader, e.g. `tower-catalog.heavy.test.ts` reading `scripts/tower-catalog`, needs the performance stage and what it needs.
8. **Which checkout.** `gate_policy.select_dev_plan` (`scripts/lib/gate_policy.py:60`) calls `plan_for` with a revision source. Reading all 332 tests through `git show` would cost seconds. The map is read from the tool checkout's working tree instead. This is sound: a head that changes which files a test reads changes `apps/web`, and that already plans web-check.
