# TX32 retro

## Brief quality

- Goal and DONE list were precise and testable. One claim was stale: the aliases were **already** generated from the
  manifests and drift-checked (`scripts/generate addresses`, U3a `ca301ea28`); what remained was that the generated
  map was written *into* the hand-written `apps/web/tsconfig.json`, so every unit PR still edited it. Re-verifying the
  evidence first (as the brief asks) turned "build a generator" into "move its output".
- "DO NOT TOUCH any unit manifest" collided with `unit_check` (a new production file must belong to a unit). Resolved
  with the one reversible option: one path added to `units/web-build/unit.json`, the unit that already owns
  `apps/web/tsconfig.json` (decision comment on #750).
- "ONE BRANCH, ONE PR" vs "a file in another lane is a separate PR": four engine-lane files assumed the map's file is
  the project tsconfig, so the prerequisite went to #755 (engine-lane), as the brief allows for the generator.

## Premises

| Premise | Held? |
|---|---|
| P-46 (verdict from the pinned gate) | held: #755 gated with the pinned path; #750 is green only on a base that has #755, proved with `scripts/gate-batch` on the union |
| tsc / Next / typescript-eslint resolve `paths` through `extends` | held: `tsc --showConfig` of base vs head, whole resolved config, empty diff; `pnpm typecheck` green |
| No engine change needed | **broken**: `unit_battery.types_project` extended the addresses output (would have lost `strict`/`jsx` on a paths-only file); two engine tests read the literal path |

## Failures and root-cause class

| Failure | Class | Fix |
|---|---|---|
| `test_aggregates`, `test_gate_areas` red after the move | code (engine readers used a literal path, not the registry) | #755: read `generate.targets` › addresses `output` and `gate-areas.db_tsconfig` |
| architecture parity `afterAll` (data rules find more than the oracle) | code (frozen pre-U2 oracle reads `apps/web/tsconfig.json` by literal) | the fixture hands the oracle the same aliases at its old path; oracle unchanged |
| `unit_check`: production file of no unit | contract (brief rule vs repository check) | one manifest path, CODEOWNERS regenerated |
| new drift test timed out at 5 s | env (a subprocess without `OU_CONFIG_STORE=file` waits ~9 s for the config store) | the spawned generator runs on the fixture's file store, as other hermetic script tests do; no timeout changed |

## Gate runs

- #755 pinned gate: PASSED on `54fa707c` (`pr.ready #755`), 294.5 s (script tests 238.7 s; report-only ceiling 180 s). Merged.
- Union #755 + #750 (`scripts/gate-batch`, base 891b835ae): red. Heavy parity (mine, fixed `fc96df99`); bundle 695469 > 695296 (same on the bare base, fixed by #757); `media:cache` (an unseeded media dir on the box, seeded by A Torre; the prefetch in `gate-fixed.sh:77-82` ignores its exit, so it surfaced as a `code`-class build failure).
- Union rerun after the base moved: stages killed by stage timeouts under CPU load (env); superseded.
- Pinned gate on #750 `383660d0` (base ee091f9d, `OU_GATE_OFFLINE=1`): builds, e2e and perf green; red only on base reds: `architecture-engine.test.ts` glob parity vs TX21 covers ownership, `prepush.test.sh` vs the new census message, and `gate-classify.test.sh` (a shared `/tmp/gate-local-<stage>.log` collision with the real gate).

## Lessons

1. **A generated value must not live inside a hand-written file.** Rule: a committed generator target writes a file of
   its own (pure output), never a section of a file people edit; owner: engine-generate (`generate.targets` schema
   could refuse an `output` that is also a unit-owned hand-written config).
2. **Readers find derived files through the registry, never a literal path.** The literal census does not catch a
   relative repository path in a Python test; owner: engine-literal-census (count `apps/`-prefixed paths in tests).
4. **A test's fake gate must not write the real gate's log paths.** `test_gate_classify.py` clobbered
   `/tmp/gate-local-unit_tests.log` during a real run, so the real failure was unreadable; owner: engine-gate (log dir
   from `ou_worktree_dir` or a temp dir).
5. **A prefetch that ignores its exit hides the class.** `media:cache` failing should print `env` at its own step,
   not later as a `code`-class build; owner: engine-gate.
3. **Hermetic subprocess helpers.** Spawning a script with a fixture root should default to the file store; owner:
   testing-support (one helper for `--root` fixtures that sets it).
