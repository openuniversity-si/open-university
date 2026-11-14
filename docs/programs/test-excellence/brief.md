# Program test-excellence: brief

TX-PROGRAM, "Excelência de teste" (Daniel 00:57 and 00:58 BRT 28/10; addendum 01:03, corrected 01:03 and 01:06). Everything else is paused for it. Same mold as [gate-excellence](../gate-excellence/): audits, plan with waves, launch map, measured critical path, retros.

## Complaint
Tests are a recurring blocker of PRs, and most of the blocks are not the PR's own fault: a shared test file conflicts because another unit merged first, a hand-kept inventory does not know the unit's own new file until the full gate, the base or the machine is red, or a test fails only under load.

## Symptom
Tonight (27/10 20:00 BRT to 28/10 01:00 BRT): `scripts/tests/gate-local.test.sh` conflicted #732 GX-15 twice (on base `9fa02090` and `132af477`); #740 GX-25 went red at 03:56Z on head `8f6ba426` on `scripts/tests/units.test.sh` (`Lists differ: [scripts/tests/covers/gate-timing-report...] != []`) and `scripts/tests/structure-check.test.sh`; NANO-UNBLOCK left base-red and env items in `docs/units/NANO-UNBLOCK/backlog.md`; load flakes in `gate-graph.test.sh`, catalog-cli `sync.test.ts`, identity `handler.test.ts`.

## Evidence
[audit.md](audit.md): every red gate and `pr.conflicted` since 27/10 23:00Z, ranked by PRs blocked, and the overlap table of shared test files across open PRs.

## Measurable goal
At the design target of 1,000 PRs per day (about 40 per hour; 10k and 100k are a distant horizon, not designed for now): no PR is blocked by a test failure that is not its own fault. Metric `test_blocks_not_own_per_day` (gate.failed whose class is env, known defect or flake, plus `pr.conflicted` on a test file or test inventory, per day), comparator `lte`, target 0, measured from the forge events on the tracker issue and the PRs.

## Hard rules (from the brief)
Never merge (the train is the only merge path); never loosen a threshold or timeout; never skip, delete or quarantine a test by hand; never weaken an inventory or structure check (deriving its list is fine); every split keeps every assertion (counts quoted); one lane per PR; nothing touches Neon, Vercel or production; no GitHub Actions; no comments on other PRs or edits to their branches; no launches (briefs go to `briefs/` and a STATUS comment).
