# U3b media: retro

Whole unit, from the launch brief to the accepted gate. Facts with evidence; times are commit times (UTC) and gate
logs in the session scratchpad.

## 1. Brief quality

- **Ambiguous: the branch name.** The brief says work branch `mod/u3b-media-addresses`; the session's git rule
  designates `claude/u3b-media-addresses-k989tc`. The session rule was followed; the PR body states it. Fix: the
  brief template states one branch name per session.
- **Missing: Node-run code.** The brief says "rewrite every cross-unit import in the lane's own files" but not that
  files loaded by Node tooling (next.config, `scripts/*.ts`, the catalog CLI) cannot resolve `@ou/` aliases. Four
  merged U3b lanes had already hit this; the brief did not carry their rule. The gate found it (run 1). Fix: a U3b
  brief template line: "a file in a Node closure keeps relative imports (D-069 item 7)".
- **Wrong: the audit reading list.** The brief points at the v3 audit by commit; the note "P-05 CONFIRMED" etc. was
  accurate. No problem found.
- **Ambiguous: "test census identical".** Defined as the type-check file count plus the test file count. The vitest
  test-name census is a stronger check and was added by the session. Fix: the brief names the census command.

## 2. Audit and plan

- **Premises held:** P-03 (addresses resolve, U3a map complete for the lane); P-13 (every touched file owned by a
  media unit).
- **Premise broke:** "a rewrite resolves wherever it is loaded". It holds for the vitest and tsc graphs (Vite and
  tsconfig paths) but not for Node's ESM loader. The plan's blast-radius table listed "@ou resolution in vitest" but
  not "Node-run files". The plan changed after gate run 1: 28 Node-reached files revert to relative imports
  (commit a325a554, Plan 4).
- **Plan change, documented:** the plan's per-unit counts (32 / 58 / 76) were superseded by the revert. The PR body
  and a PR comment record the new counts.

## 3. Execution (timeline, UTC)

| Time | Event |
|---|---|
| 06:47:03 | audit commit (af906b48) |
| 06:47:19 | plan commit (b7bdefc5); PR #589 opened as draft from the first push |
| 06:48:41 | media-domain rewrite (a3644d28): types battery red (Node loads `domain/types.ts`), kept relative; green |
| 06:49:17 | media-application rewrite (81084939): green on first try |
| 06:49:59 | media-server rewrite (d5756d9f): green; `public-hosts.ts` kept relative (Node) |
| ~06:52 | gate-dev run 1 on d5756d9f: FAILED (273 s): build (test engine), unit tests, performance tests |
| ~06:55 | root cause: Node ESM cannot resolve `@ou/`; closure computed; first closure missed files reached through `@ou/` imports (`ERR_MODULE_NOT_FOUND` on `server/objects.ts`); fixed to a fixed point |
| 06:57:12 | Node-closure revert (a325a554): 28 files; local perf tests 6/6 pass, transport test 10/10 pass alone |
| ~07:02 | gate-dev run 2 on a325a554: PASS, 285 s wall (over the 180 s ceiling: warning, D-064 f) |

Waits: gate runs were the only waits (273 s and 285 s). No waits on other PRs; none needed (base unchanged).

Dead ends: the first Node-closure traversal (relative imports only, on the rewritten tree) missed 9 files; the
`media-cache --help` check exposed it. Cost: one extra revert round.

## 4. Gate

- **Runs:** 2 (run 1 red: 3 stages; run 2 green on the exact head).
- **Run 1 failures and class:**
  - `build (test engine)`: `Cannot find package '@ou/media-server'` from `media/application/operations.ts`, reached
    by `media:cache`. **Class: code** (the PR's own rewrite into a Node-run file). Fixed.
  - `performance tests`: the tower-catalog CLI tests; they call the Node media CLI and failed for the same cause.
    **Class: code**, same cause. Verified fixed locally (6/6) and in run 2.
  - `unit tests`: `catalog-cli/transport.test.ts` "keeps the process alive until the deadline". **Class: flake
    under load** (passes alone, 10/10). Not in the known-timing list; not changed.
- **Known defects hit:** none of the named timing-sensitive tests (tower-catalog cover concurrency, read latency).
- **Gate time:** 273 s and 285 s (both over the 180 s ceiling, warnings). Stage time leaders: integration tests,
  lint, unit tests. Not this PR's concern; recorded for the gate owners.

## 5. Lessons

| Problem | Concrete change that prevents it | Owner |
|---|---|---|
| Node-run files rewritten to `@ou/` (run 1) | The U3b brief template states the Node-closure rule (D-069 item 7) and names the closure command. Better: a `scripts/units check` rule that flags an `@ou/` import in any file reached from a `scripts/**` entry or `next.config.ts`, so the rewrite is refused at structure check, not at the gate. | Unit tooling (U2/U3a owners); brief template: coordinator (CO1) |
| Closure computed on the rewritten tree misses files | The closure tool follows `@ou/` specifiers through `unit_addresses.resolve` from the start (done in this session's script, not committed). Put it into `scripts/lib/unit_addresses.py` as the shared helper. | U3a owner |
| Branch name conflict (brief vs session) | Brief template: one designated branch per session. | CO1 (coordinator) |
| Test census ambiguous | The brief names the census command: `pnpm exec vitest list <files> --json` plus the battery counts. | CO1 (coordinator) |
| Gate over the 180 s ceiling (both runs) | Not a U3b change; logged for the gate owners (the ceiling is a warning, D-064 f). | Gate owner (GV1/gate speed work) |
| Commit message miscount ("Two imports", there were three) | Commit messages are checked against the audit before push: a line-count check in the rewrite step. Recorded in a PR comment, not amended (pushed). | Session habit; no shared mechanism needed beyond the PR comment |

## Decision record

- Node-run files keep relative imports: the precedent of 3c0ffb84 (config), a0cccfff (factory), 2d7d70e2 (postinstall).
- Flake `transport.test.ts`: not changed, not quarantined (no owner rule applied here; the owner of the catalog CLI
  should decide whether to add it to quarantine, per M7).
