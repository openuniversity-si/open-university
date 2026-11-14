# U4 engine-cloud: retro

## 1. Brief quality
- Wrong for this unit: "move files to `units/engine-cloud/`", "contract entry exports what others import", "@ou importers". The unit is shell/Python outside `apps/web`: no `@ou` address, importers call paths. The brief allowed the fallback (keep in place) but the contract item had no fallback: the manifest `contract` slot is resolved through the address and turns the battery red for an unaddressable unit (verified).
- Missing: that unit tests live under `scripts/tests/` owned by other units; the unit owned zero tests, so its battery ran nothing.
- Missing: the literal rule counts only registered parameters; this unit's literals were unregistered, so "zero literals" needed a registry first.

## 2. Audit and plan
- P-03 held (files stay). Contract premise broke (no contract entry possible); decision: leave slot unset, reported in the PR.
- Plan changed once: first draft had registry split by language; ended as Python params in commit 3 and shell params in commit 4 so each commit stays green (readers must exist).

## 3. Execution
- Commits: audit, plan, registry + Python literals, shell literals, battery/manifest, gate-table fix, base merges.
- Failure class A (first failure, fixed as a class): tests that pin a literal as source text (`test_cloud_tail` fonts, `test_root_identity` lock path and `POSTGRES_BINARIES`, `gate-script-tests` selection table). Searched all of `scripts/tests` for the moved literals; three files edited. The table failure was found only by the gate (selection table is not run by the targeted tests I chose): incomplete class search, I did not run `gate-script-tests.test.sh` after adding a `covers` entry.
- Failure class B: first env.sh draft read the registry five times per `source` (0.05 s to 1.0 s). Measured before committing; fixed by per-branch reads and skipping when the parent shell already carries the result.
- Failure class C: `config.py get` with one name prints a bare value, with several a dict; my parser assumed a dict (caught by an existing claude-session test).
- Dead ends: `config.check()` takes 51 s, so two early tests were rewritten to scan only the unit.

## 4. Gate
- Run 1 (head e86ab7d2): red, 359 s: `gate-script-tests` table (mine) and `generate.test.sh` (`@ou/kernel-tables` not resolved by plain node; reproduced identically on a clean worktree of the base, so a base defect). Run 2: see the PR comment.

## 5. Lessons
- A script-test mapping change must run `gate-script-tests.test.sh` in the unit battery (owner: engine-test-support); tests must assert registry reads, never literal source text (owner: engine-test-support; add a hermetic-lint rule).
- `config.py get` should have a stable output form for N names, or a `--shell` form for shell readers (owner: engine-config); five shells now carry a parser.
- Brief template for non-TS units: state that the contract slot needs an address form (owner: units lane, U3a follow-up), otherwise `contract` is unreachable.
- Registry reads in hot shell paths need a cost budget in the brief (0.2 s per `config.py get` call).
