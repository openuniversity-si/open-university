# KD1 audit: known base defects (read-only findings, 2026-10-27 00:2x)

Brief: known base defects as a structural, automatic process (Daniel, 26/10 23:50-23:54; D-069). Base `974cab54`
(`mod/roadmap-integration`, GS1 #569 and TR1 included). Evidence below was gathered with reads and the two suspect tests
run once each on the base; no suite was run.

## What exists and is reused
| Need | Found | Where |
|---|---|---|
| Per-test cache (GS1) | script tests are cached per test, `covers` files and toolchain; marker store behind the storage port | `scripts/lib/gate_test_cache.py` |
| Failing test id + signature in the verdict | `gate.failed.failing_tests[] = {id, stage, signature}`; signature is the normalized last error line | `scripts/lib/gate_failures.py`, `gate.failed.v2.json` |
| Verdict emission | `gate_report.py` publishes `gate.passed`/`gate.failed` + `engine.step.measured` through `forge_events` | `scripts/lib/gate_report.py` |
| Owner map | `units.owner_of_path(path)`; unit manifests `units/<id>/unit.json` (owner lane, paths, `requires`) | `scripts/lib/units.py` |
| Open queue | `pr.opened.units[]`; `open_changes(repo, base)` on the GitHub adapter | `contracts/events/pr.opened.v1.json`, `forge_github.py` |
| Fix unit assignment | `work.assigned {lane_id, units, item, sha}` is the maestro's way to start a lane's item | `contracts/events/work.assigned.v1.json` |
| Versioned registry pattern | one YAML-subset record per premise, JSON Schema, sealed digest, CLI | `scripts/lib/premises.py`, `contracts/premises/premise.v1.json` |
| Registered configuration | `config/registry/*.json`, `config.get`, `scripts/config describe`; readers must exist, no literals in engine files | `scripts/lib/config.py`, `config_check.py` |
| Analogous owner-routed lifecycle | flaky quarantine: events, owner from the map, replay of the log | `scripts/lib/quarantine.py` |

Nothing named "defect" exists in the repo (`rg -i "known.defect"` finds only prose). The brief's JSON
(`/workspace/torre/motor/v3/known-defects.json`) is outside the repo, so it is not read; the seeds come from measurement.

## What is missing
1. No re-run of a failing test on the base, so a base failure and a PR failure are indistinguishable in the verdict.
2. `gate_report.py` turns any failed stage red; there is no notion of a known, non-blocking failure.
3. No defect record, no dedup, no audit trail, no owner derivation outside the quarantine.
4. No priority: the quarantine escalates by age (`quarantine.max_age_s`), which Daniel rejected for defects.
5. No lifecycle after "detected": nothing closes a defect when the test passes again.

## Measured on the base (one run each, parallel)
- `scripts/tests/premises.test.sh`: FAIL, `Repository.test_repository_register_is_valid`, `AssertionError: Items in the first set but not the second: 'measurement:S1'` (P-01..P-07 answered by `measurement:S1`, the register expects `A Torre`).
- `scripts/tests/generate.test.sh`: FAIL, `generate.GenerateError: apps/web/scripts/intents-doc.ts failed (1): (node:internal/modules/esm/loader...)`, `ERR_MODULE_NOT_FOUND`.
- `scripts/generate all` stops at `intents` for the same reason; the committed targets (`python-types`, `ts-types`, `codeowners`, `locale-text`, `addresses`) regenerate and `--check` clean.
- The gate's signature for a script test is the last error-looking line of its tail (`last_error`); the seeds use that exact function, so the registry and the gate compare like with like.

## Constraints found that shape the design
- **A config key needs its readers to exist** (`test_every_entry_is_typed_documented_owned_and_read`, 33 failures when the registry was added before the library): each commit adds only the keys its module reads.
- `EVENTS.md` must name every event schema (`test_events_md_and_the_schemas_name_the_same_events`).
- Event schemas are immutable once locked: the verdict gains `known_defects` as `gate.passed/failed` v3.
- The gate verdict's stage result is an enum `PASS|FAIL`; an explained stage is reported `PASS` and the excused tests go in `known_defects`.
- The gate runs in a PR checkout and cannot commit to the base: it publishes `defect.detected`; the router's PR writes the registry.
- Each `.test.sh` is the unit of failure the gate sees (not the case inside it), so the defect id for a script test is the script path; the brief's `premises.test.sh > Repository.test_repository_register_is_valid` is kept as the summary.
- Gate files (`gate_report.py`) require a PR body citing an approved D-NNN: D-069.

## Premises
See plan.md. No CRITICAL premise: nothing here touches production, money or the source of truth.
