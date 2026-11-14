# TX20 retro

## Brief quality

The brief was precise on the evidence, the files and the done list. Every cited file and line held on base 891b835ae.

One item needed a decision: documentation. A doc a web test reads (`docs/domain/DECISIONS.md`, `AGENTS.md`) falls under T3/T5. But the brief also asks that a docs-only diff plan what it planned before. In addition, `gate_select` gives a docs-only diff a scoped selection with no tests, so planning the unit stage would not run the reader anyway (audit finding 5). Documentation stays out, and the gap is recorded.

## What changed

- `scripts/lib/gate_web_readers.py` builds a static map of the web tests that read repository files outside `apps/web`: 24 readers, 6 of them unknown, in about 0.25 s.
- `plan_for` adds each reader's stage and its `needs` through one call.
- An unknown reader (anchored at the root, with a computed read path) is selected by any `scripts/**` change.
- A map that cannot be built selects every test stage.
- The flag `gate-web-readers.enabled` is the rollback.

## Premises

- **P-46** held. The verdict is the pinned base gate, so this PR's own plan is computed by the base code and the new rule applies after merge.
- **TX20-a** (working-tree map) held. Every replayed merge gave the same plan whether the map came from the base or the head.
- **TX20-b** (docs out) held as a known gap.

## Failures and root-cause class

1. Fixture paths in my own test had the wrong `../` depth. Class: code (mine), fixed before the commit.
2. Two registry refusals came from `structure-check`: an object default needs `x-text`, and the number 2 is a literal. Class: code (mine). Fixed by three string keys and `parent.parent.parent`.
3. `test_gate_areas` expected a scripts-only diff to need no web stage. Class: contract.
   - That row encoded the unsound behaviour of #722. `no-legacy-email.test.ts` reads every tracked file and `database-target.test.ts` reads `scripts/lib/neon_pr.py`.
   - The expectations now name the reader stages, and the "no install" case keeps a config path. Assertions: 116 before, 116 after.
4. `cloud-tail.test.sh` fails `test_network_mode_dry_run_does_not_require_secret_env` on the base too, without this diff. Class: env (not this PR's).
5. The pinned gate on ca82875e failed `invoker-tooling.test.sh`. Class: code (mine).
   - `stages_for` read `scripts/lib/gate-stages.json` before its fail-closed path. That fixture copies `scripts/lib/*.py` and `gate-areas.json` only, so `plan_for` raised and the gate-db classification crashed.
   - Fixed in a4a9e62: the table is read only when a reader is found, and any error selects every test stage (or every stage). Tests cover both cases.
   - Lesson: a fail-closed module keeps every read inside its fail-closed path. Fixtures copy `scripts/lib` partially.
6. `credentials.test.sh` and `github-cli.test.sh` failed on both the base and the head while the GitHub client's back-off was active. Class: env.
   - The machine-wide record (`429 ... wait N s`) leaks into hermetic tests that expect a 401 or a timeout. Both passed once it expired.
   - The same back-off stopped the first pinned gate at `gate pin` (`cannot read PR #747 head/base`), 04:47Z-05:20Z. It also blocked comments and the pre-push hook. `OU_CONFIG_STORE=file` let the pushes through.

## Cost

Every `scripts/**` diff now plans `install (frozen lockfile)` and `unit tests`. Selection is full for engine paths, so the whole unit project runs. This is the cost of the 6 unknown readers. The worst of them, `no-legacy-email.test.ts`, really does read every file.

7. `apps/web/scripts/lib/architecture-engine.test.ts` was red on the base since TX21 (feda4cc76). Class: base-red, not this PR's.
   - `units.py` gained the covers companion rule; the TypeScript tree did not.
   - TX21's gate never ran this web test, because it reads `units/**` through a computed path. That is the hole TX20 closes, and this PR's new selection found it on its first run.
   - Fix ported verbatim from open PR #759 (`scripts/lib/architecture/tree.mjs`, engine-lane).
8. `scripts/tests/prepush.test.sh` was red on the base since #742. Class: base-red, not this PR's.
   - TX22 changed the census message, while TX01's test pins the old wording.
   - No fix PR existed, so the proposed patch is posted on #747 instead of widening this PR.

## Gate runs

1. ae45c90: stopped at `gate pin` (GitHub 429 back-off), no verdict.
2. ca82875e: pinned FAILED (`invoker-tooling`, failure 5). The advisory run with the head's tooling PASSED and ran the newly planned `unit tests`.
3. 5cd1991c: pinned FAILED on `claude-session` (env: the shared preflight stamp was written during the run; it reproduces on the base and passes alone) and on `gate-report-skips` (did not reproduce). The advisory run FAILED `unit tests` on `architecture-engine.test.ts`, which is base-red (failure 7).
4. e916832: the advisory `unit tests` PASSED with the #759 port. Pinned and advisory FAILED on `prepush.test.sh`, which is base-red (failure 8).
5. The final run follows the base fix for failure 8.

## Lessons (rule or tool change, owner)

1. **Narrow the unit run to the readers** (engine-gate-plan, follow-up). `gate_select` could take `gate_web_readers` readers as its test list for engine paths, and for documentation paths, which closes finding 5.
2. **Make the unknown readers static** (apps lane). Five of the six build a path from a variable that a literal list would fix:
   - `architecture-engine`
   - `check-architecture`
   - `domain-literals.kernel`
   - `intents`
   - `tower-catalog.heavy`: fixed here by allowing `Number(...)`, since a file descriptor is not a path.
3. **Isolate the forge back-off in hermetic tests** (engine-github). `test_credentials` and `test_github_cli` should not read the machine's 429 record.
4. **One PR, one message change** (the train, D-065). #742 merged two units whose tests disagree. A message change and every test that pins it belong in one commit; failure 8 is the evidence.
5. **Widen `unknown_globs` past `scripts/**`?** A full-tree reader such as `no-legacy-email` arguably needs every path (engine-gate-plan, registry decision).
