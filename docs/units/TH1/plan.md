# TH1 plan: thresholds only tighten; hermetic carve-outs listed (D-069 item 14)

Audit: [audit.md](audit.md). Gate files change under D-025 and D-069 (item 14 authorizes this PR); each commit cites them.

## Commits (dependency graph)

| # | Commit | Owns | Depends on |
|---|---|---|---|
| 1 | Audit | `docs/units/TH1/audit.md` | - |
| 2 | Plan | `docs/units/TH1/plan.md` | 1 |
| 3 | Hermetic carve-outs: a `harness` rule for `without_harness` calls; the two existing sites listed in `tests.unhermetic_sites` with their reason; the shrink rule admits a gained site only when the base file already offended it | `scripts/lib/hermetic_check.py`, `config/registry/tests.json`, `scripts/tests/test_hermetic_check.py` | 2 |
| 4 | Threshold-monotonic check: `x-monotonic` in the registry meta-schema, `config.monotonic_patterns`, the structure-check module `scripts/lib/threshold_check.py` (a looser value fails unless the body and a commit carry `Loosens: <name> D-NNN`), wired into `structure.py`, unit manifest and script-test cover | `contracts/config/registry.v1.json`, `config/registry/config.json`, `scripts/lib/threshold_check.py`, `scripts/lib/structure.py`, `scripts/tests/test_threshold_check.py`, `units/engine-config/unit.json`, `scripts/lib/gate-script-tests.json` | 2 |
| 5 | `config.changed` report: each registry default edited in the PR is printed as one `config.changed` envelope line (`EVENT ...`) in the structure-check report, no refusal | `scripts/lib/threshold_check.py`, `scripts/lib/structure.py`, `scripts/tests/test_threshold_check.py` | 4 |
| 6 | Retro | `docs/units/TH1/retro.md` | gate |

Commits 3 and 4 own disjoint files and can run in parallel; 5 extends 4's files, so it runs after 4.
The coordinator is the sole writer of the branch.

## Rules of the new check

- Judged: every entry whose name matches a `config.monotonic_patterns` glob (initial `*_timeout*`, `*_limit*`,
  `*_max*`, `*_budget*`, `*_ceiling*`, `*_tolerance*`) or declares `x-monotonic`; numeric defaults only.
- Direction: `x-monotonic: "max"` (a ceiling: higher is looser) or `"min"` (a floor: lower is looser); a pattern
  match without the key is a ceiling.
- Looser fails unless the PR body and a commit message of the PR each carry `Loosens: <name> D-NNN`, with the
  D-NNN recorded in `docs/domain/DECISIONS.md`. Tightening, an equal value and a new key pass. A removed key is the
  expand->contract rule's (schema compat), not this check's.
- Report: every changed default (`config.diff_ref` against the base) prints `EVENT <config.changed envelope>`, built
  through the `forge_events` port on a memory adapter, never written to the store.

## Premises and blast radius

- P-41 (config as code, HIGH, confirmed): every new tunable is a registry entry; if wrong the patterns would move to code.
- Numeric defaults are the only thresholds judged (LOW): an array allowlist loosening is not caught by this check
  (the existing shrink-only rules of `x-literal-sites` and `tests.unhermetic_sites` cover those two lists).
- No CRITICAL premise: nothing here spends money, touches production or the source of truth.

## Tests

- Commit 3: `scripts/tests/test_hermetic_check.py` (harness refused unlisted; listed passes; a gained site that
  offended at base passes; a gained site new at base is refused; the repository passes).
- Commits 4-5: `scripts/tests/test_threshold_check.py` (a raised ceiling fails; a lowered floor fails; tightening,
  equal and new keys pass; a cited `Loosens:` in body and commit passes; body-only or an unknown decision fails;
  non-numeric skipped; the report line is a valid `config.changed` envelope; the repository passes).
- One final gate: `scripts/gate-dev --pr <N>`.

## Known base defects

The timing-sensitive web tests (cover concurrency, read latency) on 4 vCPU; not touched.
