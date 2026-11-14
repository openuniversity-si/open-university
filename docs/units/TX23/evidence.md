# TX23 evidence

Base `mod/roadmap-integration` @ `891b835a` (no movement since). Each row below was run in this checkout against the base version of the test (`git show origin/mod/roadmap-integration:<test>`, called "base test") and the new version; the mutated file is restored after each run.

## Assertion counts (runtime, every `TestCase.assert*` call, `subTest` loops included)

| Test file | Tests before -> after | Assertions before -> after |
|---|---|---|
| `scripts/tests/test_gate_areas.py` | 24 -> 25 | 580 -> 602 |
| `scripts/tests/test_gate_report_skips.py` | 8 -> 8 | 62 -> 66 |
| `scripts/tests/test_gate_script_tests.py` | 15 -> 15 | 107 -> 204 |

No assertion is removed. Replaced assertions: the four hard-coded group lists (areas), the pinned digest (report skips), the three exact selections and the pinned `modules` set (script tests); each is replaced by a stronger or equal derived check below.

## Mutations (CRITICAL premise: what the old assertion caught is still caught)

Format: label | mutated file: before -> after | base test | new test | the unmutated new test.

### test_gate_areas.py
```
A3 | scripts/lib/gate-areas.json: '"suite union",\n      "lint",\n      "unit tests",' -> '"suite union",\n      "unit tests",' | base test FAIL | new test FAIL | unmutated new test PASS
A4 | scripts/lib/gate_areas.py: "return full_plan(paths, f'unmapped path: {path}')" -> 'continue' | base test FAIL | new test FAIL | unmutated new test PASS
A1 | scripts/lib/gate_areas.py: 'selected = set(mapping.always)' -> 'selected = set()' | base test FAIL | new test FAIL | unmutated new test PASS
A2 | scripts/lib/gate_areas.py: "stages, _ignored = _ordered(mapping, selected, '')\n    for stage in stages:" -> 'stages, _ignored = sorted(selected), None\n    for stage in stages:' | base test FAIL | new test FAIL | unmutated new test PASS
```
### test_gate_report_skips.py
```
S1 | scripts/lib/gate_proof.py: '[sha, mode, expected]' -> '[sha, expected]' | base test FAIL | new test FAIL | unmutated new test PASS
S2 | scripts/lib/gate_proof.py: 'MS = 1000' -> 'MS = 100' | base test FAIL | new test FAIL | unmutated new test PASS
S3 | scripts/lib/gate_proof.py: "'ok' if stage['result'] == 'PASS' else 'fail'" -> "'ok'" | base test FAIL | new test FAIL | unmutated new test PASS
S4 | scripts/lib/gate_proof.py: "+ [item['name'] for item in report.get('skippedStages', [])]" -> '' | base test FAIL | new test FAIL | unmutated new test PASS
```
### test_gate_script_tests.py
```
T1 | scripts/lib/gate_script_tests.py: "return tuple(script for script in scripts if script in wanted), f'" -> "return tuple(script for script in scripts if script in wanted)[:1], f'" | base test FAIL | new test FAIL | unmutated new test PASS
T2 | scripts/lib/gate_script_tests.py: "owned = [path for path in paths if path.startswith('scripts/') or covered(path)]" -> 'owned = paths' | base test FAIL | new test FAIL | unmutated new test PASS
T3 | scripts/lib/gate_script_tests.py: 'return any(flags[name] for name in chosen)' -> 'return False' | base test FAIL | new test FAIL | unmutated new test PASS
T4 | scripts/tests/covers/generate.json: '"modules": true' -> '"modules": false' | base test FAIL | new test FAIL | unmutated new test PASS
```

## Equivalence of the replaced pin

`test_gate_report_skips.SeamPayload.BEFORE_SPLIT` is now `seam_digest()`, computed from the fixture and the registry. It equals the former pin: `b4edb1c4db27832cfadf8652d69bb765972e279723d24b8ef0885420470fe307`. `test_gate_report_v4.py` (same lane, not edited) still compares its runs with `SeamPayload.BEFORE_SPLIT` and passes (found by running `scripts/tests/gate-report-skips.test.sh`, which runs it; FIX THE CLASS: `grep -rn BEFORE_SPLIT` finds only those two files).

## The point of the unit: adding a stage or a test edits no test

| Change applied temporarily | base test | new test |
|---|---|---|
| `pr metadata` added to `gate_policy.PREREQUISITES` and to `order`, `always`, `subjectInstallUnless` of `gate-areas.json` | FAIL | PASS (`test_gate_areas.py`) |
| `pr metadata` added to `gate_policy.PREREQUISITES` | FAIL | PASS (`test_gate_report_skips.py`) |
| a new `scripts/tests/zz-tmp.test.sh` with a covers manifest matching `scripts/cloud/**` | FAIL | PASS (`test_gate_script_tests.py`) |

## Lane, thresholds

```
$ git diff --name-only origin/mod/roadmap-integration...HEAD
docs/units/TX23/audit.md
docs/units/TX23/plan.md
scripts/tests/test_gate_areas.py
scripts/tests/test_gate_report_skips.py
scripts/tests/test_gate_script_tests.py
```
All code paths map to engine-lane (`scripts/units owner`: engine-gate-plan, engine-gate-report, engine-gate-plan); `docs/units/TX23/**` is owned by no unit, as every `docs/units/*` before it.

```
$ git diff origin/mod/roadmap-integration...HEAD | grep -nE '^[+-].*(timeout|_s"|_ms"|threshold)'
(no output)
```
No threshold or timeout changed. The only duration in the new code is `timedelta(seconds=1) // timedelta(milliseconds=1)` in `seam_events`, which uses only the allowed literals 0 and 1; the literal census equals its list and no baseline was rewritten.

## Fast checks before the last push

`scripts/units check` (106 valid, 0 errors), `literal_census.py` (equals the list), `gate_script_tests.py check` (ok), `scripts/generate --check`, `scripts/structure-check --base origin/mod/roadmap-integration` (0 errors; 50 pre-existing warnings), targeted `scripts/tests/gate-areas.test.sh`, `gate-report-skips.test.sh`, `gate-script-tests.test.sh` all OK.
