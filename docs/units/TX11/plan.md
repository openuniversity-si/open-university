# TX11 plan: flake attribution on the PR's own head

Lane: engine-lane. Base: `mod/roadmap-integration` at `891b835ae`. Audit: [audit.md](audit.md).

## Rule

After the known-base-defect step, every still-failing test of a stage in `gate-flake.stages` (v1: `script tests`)
that the PR did not touch is re-run exactly once, alone, at the same head, in the same checkout and environment
(`gate_test_cache.run` with a throwaway cache location, so the re-run neither reads nor writes a marker).

- Fails again: nothing changes. The stage stays FAIL, its class stays the runner's (`code` for an assertion), the PR is red.
- Passes: the test is a flake. It is listed in `report['flakes']` and in `report['known_defects']` (source `flake`,
  `base_sha` = the head it flaked on), so the status table shows it in the "Known base defect" column, the verdict
  payload lists it, and `defect.detected` makes `scripts/defects sync` record it through `defects.record`
  (test, normalized signature, owner unit derived from the manifests, evidence `at` per sighting = first/last seen).
  The stage log gets one `flake:` line per test and the class line `flake`. A stage whose every failing test is a
  known defect or a flake becomes PASS with `raw_result` FAIL; the report is PASS when no stage is still FAIL.
- Quarantine: each flake also emits `test.flaked` on the repository channel. When the log holds
  `gate-flake.quarantine_after` (2) `test.flaked` for the test inside `gate-flake.quarantine_window_s` (this one
  included) and the test is not already open, `test.quarantined` follows (owner from the unit manifests). The
  quarantine changes no policy (quarantine.py:14): a quarantined test that fails twice still blocks, and a quarantined
  test that flakes is still listed in the report, table and payload.

Never: a second re-run, a re-run of a whole stage, a changed timeout or threshold, a stage outside the list excused,
a touched test excused, a re-run error excused (an error or a missing result is "fails again").

## Premises

- P-46 (the PR body's premise): the verdict comes from the pinned gate on the base tip; this PR's gate code runs as
  code under test until it is on the base.
- **TX11-P1, CRITICAL (changes how a verdict is produced):** one pass at the same head and inputs after one failure
  proves the failure is not the change's. Blast radius: every tier-1 gate verdict (`gate_tier.adjudicated` modes) on
  every PR whose script tests fail. Wrong, a real intermittent bug the PR introduced in untouched code could pass;
  bounded by (a) touched tests never excused, (b) one re-run only, (c) every flake recorded, shown and quarantined
  on the second sighting, (d) the switch `gate-flake.enabled` (default on) turns the whole rule off. The two fixtures
  (commit 4) ship before the call site goes live (commit 6).

## Commits (dependency graph)

```
1 audit -> 2 plan -> 3 registry + gate_flake core -> 4 fixtures -> 6 call site (live)
                                         \-> 5 flake class --------/                 -> 7 RETRO
```

| # | Delivers | Files | Targeted tests |
|---|---|---|---|
| 1 | Audit | `docs/units/TX11/audit.md` | - |
| 2 | Plan | `docs/units/TX11/plan.md` | `scripts/structure-check` |
| 3 | Registry and core (not called yet) | `config/registry/gate-flake.json`, `scripts/lib/gate_flake.py`, `scripts/tests/test_gate_flake.py`, `units/engine-gate-report/unit.json`, CODEOWNERS (generated) | `test_gate_flake.py`, `scripts/units check` |
| 4 | The two fixtures against the real re-run (deterministic fail: code, red; fail-then-pass: flake, PASS, record) | `scripts/tests/gate-flake.test.sh`, `scripts/tests/covers/gate-flake.json`, gate-script-tests map if generated | `gate-flake.test.sh` |
| 5 | The `flake` class | `scripts/lib/gate_classify.py`, `scripts/tests/test_gate_classify_flake.py` | `gate-classify.test.sh` |
| 6 | The call site in `gate_adjudicate.adjudicate` and the flake/quarantine events in `defect_events` (one seam, one file) | `scripts/lib/gate_adjudicate.py`, tests | `gate-flake.test.sh`, `defect-detect.test.sh`, `gate-report-skips.test.sh` |
| 7 | RETRO | `docs/units/TX11/retro.md` | - |

Single final gate: the pinned gate, `OU_CONFIG_STORE=file bash scripts/cloud/setup.sh`, then
`(export OU_CONFIG_STORE=file; source scripts/cloud/env.sh; unset OU_CONFIG_STORE; scripts/gate-dev --pr 743)`.

## Collisions

Pending PRs #740 and #683 also edit `units/engine-gate-report/unit.json` (each adds its own lines); a base merge
resolves by keeping both sides' lines and regenerating CODEOWNERS (`scripts/generate codeowners`).
