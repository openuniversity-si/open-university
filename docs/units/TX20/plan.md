# TX20 plan: sound selection of web tests that read engine files

Commits form a chain: 1 → 2 → 3 → 4 → 5. Each one is green alone and pushed alone, with trailers `Plan: N` and `Decision: D-070`.

| # | Commit | Files | Targeted tests |
|---|---|---|---|
| 1 | Audit | docs/units/TX20/audit.md | none (docs) |
| 2 | Plan | docs/units/TX20/plan.md | none (docs) |
| 3 | The reader map | `scripts/lib/gate_web_readers.py`, `config/registry/gate-web-readers.json`, `scripts/tests/test_gate_web_readers.py`, `scripts/tests/gate-web-readers.test.sh`, `scripts/tests/covers/gate-web-readers.json`, `units/engine-gate-plan/unit.json` (+ `CODEOWNERS` regenerated), engine-gate-plan literal baseline if it moves | gate-web-readers.test.sh |
| 4 | One call in `plan_for` | `scripts/lib/gate_areas.py` (one call), fixtures in `test_gate_web_readers.py` (the #722 replay, docs-only, apps-only, dynamic read) | gate-web-readers.test.sh, gate-areas.test.sh, gate-select.test.sh |
| 5 | Evidence and retro | docs/units/TX20/retro.md | none (docs). The single final gate is the pinned `gate-dev --pr 747`. |

## Design

`gate_web_readers.build(root)` scans the tracked `apps/web/**/*.test.{ts,tsx,mjs}` in the working tree and returns `{test: {reads: [paths], unknown: bool}}`.

**What counts as a read.** A static read is any of these, once normalised:
- a string literal (dropping leading `./` and `../`, or resolving it against the test's own directory);
- a run of string-literal arguments of `join(` / `resolve(` (`join(app, "..", "..", "docs", "x.md")`).

The result must start with a top-level entry of the repository other than `apps`, and contain a `/` unless it is a root file.

**Unknown readers.** A test is `unknown` when it is anchored at the repository root (`--show-toplevel`, or a literal that climbs out of `apps/web`) and one of its read calls (`gate-web-readers.read_calls`) takes an argument that is not static.

**What the map selects.** `extend(paths, mapping, selected, reasons)` is the one call in `plan_for`. For each changed path that is outside `apps/web` and is not documentation:
- each test whose read equals the path, or is a directory above it, adds the stage that runs the test, plus that stage's `needs` closure from `gate-stages.json`;
- each unknown test does the same when the path matches `gate-web-readers.unknown_globs`.

The stage is `integration tests` for an int test, `performance tests` for `battery.alone_*`, and `unit tests` otherwise. A map that cannot be built selects every test stage (fail closed). A registry flag turns the extension off for rollback.

## Premises (blast radius)

- **P-46** (confirmed, high): the verdict is the pinned gate on the base tip. This PR's own plan code runs only as code under test, and the new rule applies to PRs after it merges. Blast radius: every PR's dev plan. **CRITICAL**: a wrong rule under-selects for everyone. Guard: fail closed on any error, and the #722 replay fixture.
- **TX20-a** (inferred, medium): the working-tree map of the tool checkout equals the head's map whenever it matters. A head that changes what a test reads changes `apps/web`, which plans web-check anyway. Blast radius: one PR's plan.
- **TX20-b** (inferred, low): documentation paths stay out (audit finding 5). Blast radius: a docs-only change to a read doc is not re-tested until gate_select accepts a test list.

## Final gate

A single pinned `gate-dev --pr 747`, run offline (`OU_CONFIG_STORE=file`).
