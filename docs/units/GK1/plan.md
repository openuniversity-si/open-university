# GK1 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/GK1/audit.md`).
2. Plan (this file).
3. Skip record + runner helper: `scripts/lib/gate_skips.py` (`record`, `remaining`), `gate_skip` and `gate_unless_blocked` in `gate-runner.sh`, hermetic tests.
4. Report: `gate_report.py` lists guard-skipped stages with their cause, apart from stages absent from the plan; a known-defect-only run with every stage present passes; a skipped stage fails; tests.
5. Schedule: `gate-local` guards read `blocked` (install, browser inventory, DB classify), not `failed`; skipped stages are recorded; structure test forbids a `failed` guard; two-case hermetic test.
6. Retro (`docs/units/GK1/retro.md`) and the RETRO comment.

## Graph and owned files
`1 -> 2 -> 3 -> 4 -> 5 -> 6` (3 and 4 touch disjoint code but both register in `gate-script-tests.json`, so they run in sequence).
| Commit | Files owned |
|---|---|
| 3 | `scripts/lib/gate_skips.py`, `scripts/lib/gate-runner.sh`, `scripts/tests/gate-skip.test.sh`, `scripts/lib/gate-script-tests.json` |
| 4 | `scripts/lib/gate_report.py`, `scripts/tests/test_gate_report_skips.py`, `scripts/lib/gate-script-tests.json` |
| 5 | `scripts/gate-local`, `scripts/tests/gate-local.test.sh` |

## Premises
Premises: none registered. Working premises:
- (high) Not blocking later stages after a red non-dependency stage costs time only on a genuinely red run, and the verdict is unchanged. Holds: `failed` still reaches `gate_report`.
- (high) Gate files need a cited D-NNN (D-025): D-069 item 12 (failure routing).
- (medium) Neon PR stages after a red unit test create a Neon branch that was previously avoided; they are released in the same run (`Neon PR cleanup`).
- CRITICAL: none (no production, money or source of truth).

## Tests, then one gate
3: `gate-skip.test.sh`. 4: `test_gate_report_skips.py`. 5: `gate-local.test.sh`, `gate-db.test.sh`. Then one `gate-dev`.
Known defects expected: KD-024bbecb, KD-4db6e693 (engine lane).
