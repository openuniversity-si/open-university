# TRAIN-ORIGIN-INTEGRATION — validation

## Baseline merged integration

Source: `a8feab76d8d8f0fb23b55fad9bfe2bfe7d05ede7`. Started: 2026-11-02T22:49:34-03:00. Full ordinary gate: **FAIL**, exit 1, **123.068 seconds**.
All 145 script suites were selected; five failed. The full plan also includes ShellCheck.
This correctness check does not reopen Daniel's accepted performance criterion.

| Stage | Result | Seconds |
|---|---|---:|
| generated drift | PASS | 1.31 |
| no GitHub Actions workflows | PASS | 0.56 |
| pr metadata | PASS | 0.78 |
| schema compat | PASS | 0.91 |
| script tests | FAIL | 120.35 |
| secret scan (history) | PASS | 3.61 |
| secret scan (tree) | PASS | 5.37 |
| shellcheck | FAIL | 0.36 |
| structure check | PASS | 20.26 |

The initial ShellCheck failure was a missing host binary. After a checksum-verified local Debian installation outside tracked source, its actual check reports the hook-output SC2034 in the audit. The five script failures are merged-source defects. Both root-only suites executed successfully in the isolated root profile and were reused by exact key. No VM, Worker secrets or old branch was modified.

## Reconciled integration

Source: `b5777316c8b0fc57695620dfc20c4734a0a57aaa`. Started: 2026-11-02T23:07:56-03:00. Full ordinary gate: **PASS**, exit 0, **146.463 seconds**. All nine stages pass; all 145 script suites pass. Bypass disabled; no gate-speed work.

| Stage | Result | Seconds |
|---|---|---:|
| generated drift | PASS | 1.31 |
| no GitHub Actions workflows | PASS | 0.62 |
| pr metadata | PASS | 0.89 |
| schema compat | PASS | 1.31 |
| script tests | PASS | 128.42 |
| secret scan (history) | PASS | 3.32 |
| secret scan (tree) | PASS | 5.19 |
| shellcheck | PASS | 16.16 |
| structure check | PASS | 13.34 |

Hand-run affected suites (no failed tests):

| Suite | Tests |
|---|---:|
| push-guard | 25 |
| forge-events | 301 |
| forge-rate | 32 |
| gate-forge-budget | 9 |
| lessons | 52 |
| planner-role | 17 |
| plan-tick | 54 |
| train-role | 46 |
| commit-check | 23 |
| pr-creation-path | 3 |
| operation-relations | 42 |
| operation-config | 8 |
| defects | 14 |
| config-readers | 8 |

Total: 634 hand-run tests. Root-identity (8) and Claude-session (13) also executed in an isolated uid-0 profile on the exact source and were reused only by their content keys; both pass. Full ShellCheck passes. Operation relation and demand confrontation have zero findings; configuration reader declarations have zero omissions.

ORIGIN-FINISH survives: refusal incidents are asserted in the pushing checkout with no engine-tree additions; its five added consumers remain declared; the relation now measures 23 operations / 62 sites / 24 files. Origin and GitHub retain their declared adapter proofs and D-287 ownership evidence. Private file/control journal doubles, adapter-only PR creation, complete demanded test surfaces and missing-method refusal regressions are restored alongside TRAIN-DEFINITIVE deadline/no-renewal checks. The only production API change reconciles the required checkout argument; it adds no compatibility path.

The old branch was never pushed. No runner VM or Worker-secret change was made. Existing TRAIN-DEFINITIVE rollout remains coordinator-owned and unchanged; this repair adds no cutover step. The final documentation-only head will receive its own ordinary/PR gate before readiness.

## Documentation-head ordinary gate

Source: `ceb7d6424e80df22ce0533c17dbe4fecafc112e2`. Started: 2026-11-03T02:12:06Z. Ordinary full gate on PR #1088: **PASS**, **24.460 seconds** (driver-reported total), all nine stages and 145 script suites, with content-keyed reuse. Bypass disabled. GitHub reports mergeable against `a8feab76d`.

| Stage | Result | Seconds |
|---|---|---:|
| generated drift | PASS | 1.09 |
| no GitHub Actions workflows | PASS | 0.59 |
| pr metadata | PASS | 5.0 |
| schema compat | PASS | 3.0 |
| script tests | PASS | 4.84 |
| secret scan (history) | PASS | 4.28 |
| secret scan (tree) | PASS | 3.21 |
| shellcheck | PASS | 16.04 |
| structure check | PASS | 12.34 |

The following evidence-only child commit is checked by the exact-head development gate before readiness; it changes no production source, registry, fixture or test input.
