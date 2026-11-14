# LT1 plan (mirrored in the PR description)

Brief: enforcement audit 26/10 rule 1 "no literals", fix R3. `config_check` judges only registered names, so a
brand-new literal under `scripts/` passes, and `config.literal_check_excludes` leaves `scripts/tests/` out. LT1 makes
the structure check refuse unregistered literals in `scripts/` (numbers other than 0/1/-1, durations, URLs, hosts,
ports, absolute paths), with the exceptions in registry entries, tests included, and the existing offenders in a
shrink-only baseline in the D-063 style. Evidence: [audit.md](audit.md).

## Commit plan
1. Audit (`docs/units/LT1/audit.md`).
2. Plan (this file).
3. Census, a new unit `engine-literals`: registry `config/registry/literals.json` (`literals.allowed_numbers`,
   `allowed_values`, `patterns`, `baseline`, `baseline_description`, `unowned_area`); `scripts/lib/literal_census.py`
   (census, `check`, `write`, CLI `literal_census.py [--write [unit]]`, and `baseline_areas`, the D-064 a per-area
   reader that `structure.baseline_files` now calls); not yet wired into `structure-check`; hermetic tests from a data
   fixture, one case per refusal kind and per allowed case; runner `scripts/tests/literals.test.sh`.
4. Gate: `config.literal_check_excludes` drops `scripts/tests/` (the vendor check keeps its scope through its own
   `providers.vendor_check_excludes`); the list `scripts/lib/absolute-literals-baseline/engine/<unit>.json` written
   from the census; `structure-check` runs `literal_census.check`; tests: a new literal in a new file, a listed file
   that gains a literal, a list that grows against the base, a stale entry, tests scanned, and this checkout's census
   equals the list.
5. Docs: D-068 row (proof tests and status), `docs/operations/local-gate.md` (how to rewrite the list),
   CAP-011 instance; item 4 recorded as a no-op with evidence.
6. Retro (`docs/units/LT1/retro.md`) and the RETRO comment, after the gate.

## Dependency graph and owned files
`1 -> 2 -> 3 -> 4 -> 6`; `5` depends only on the names fixed in 3 and is drafted in parallel with 4 (files disjoint).
The coordinator is the only committer; one push per commit.

| Commit | Files owned |
|---|---|
| 3 | `config/registry/literals.json`, `scripts/lib/literal_census.py`, `scripts/lib/structure.py` (reader), `scripts/tests/{literals.test.sh,test_literal_census.py}`, `scripts/tests/fixtures/unregistered-literals/cases.json`, `units/engine-literals/unit.json`, `units/engine-structure/unit.json` (requires), `scripts/lib/gate-script-tests.json`, generated `config_registry_literals.py`, `CODEOWNERS` |
| 4 | `config/registry/config.json` (excludes), `config/registry/providers.json`, `scripts/lib/config_check.py` (`engine_files` excludes argument), `scripts/lib/vendor_check.py`, `scripts/lib/structure.py` (wiring), `scripts/lib/absolute-literals-baseline/engine/*.json`, `scripts/tests/test_config_check.py`, `scripts/tests/test_literal_census.py`, generated types |
| 5 | `docs/domain/DECISIONS.md` (D-068 row), `docs/operations/local-gate.md`, `docs/capabilities/CAP-011-read-every-value-from-a-catalog.md` |
| 6 | `docs/units/LT1/retro.md` |

## Premises and blast radius
- P-41 (D-068, high): every engine value lives in the registry. If wrong, the rule refuses legitimate code; scope
  stays the same, the baseline absorbs today's code.
- The D-063 census ignores a subfolder of `scripts/lib/absolute-literals-baseline/` (low; verified by reading
  `areaFiles` and `baseline_files`). If wrong, `pnpm literals:census --write` would delete or flag the engine list:
  caught by the apps/web drift test in the gate.
- U0 manifests give every scanned production file one unit (low; `unit_check` enforces it). A fixture with no unit
  falls in `config.unregistered_literal_unowned_area`.
- No CRITICAL premise: nothing here spends money, touches production or changes a source of truth.

## Decisions (reported, reversible)
- The branch is the session's designated `claude/lt1-unregistered-literals-9s45wa` (a fresh branch from the merged
  base), not `mod/motor-lt1-unregistered-literals`: the session may push only to its designated branch.
- The census is its own unit `engine-literals`, not more code in `config_check`: engine-config was at 1,494 of its
  1,500-line ceiling (D-067 (7), `scripts/units measure`), and `config_check` importing `structure`/`units` would make
  a dependency cycle (engine-structure and engine-units already require engine-config). `structure.py` calls the
  census like its other modules.
- Areas are units (D-067), not top-level folders: literals migrate with their unit (P-05) and two lanes never edit
  the same list file (D-064 a).
- The census must equal the list (D-063 style): a stale entry fails too, with the rewrite command in the message.
- The local pre-push check is not extended here (its 5 s budget); the gate runs the full census (~2 s).

## Tests per commit and the final gate
- 3: `scripts/tests/literals.test.sh`, `scripts/structure-check`, `scripts/generate all --check`, `scripts/units check`.
- 4: the same plus `scripts/tests/config.test.sh`, `scripts/tests/vendor-ports.test.sh`, `python3 scripts/lib/literal_census.py`,
  `scripts/structure-check --base origin/mod/roadmap-integration`.
- 5: `scripts/structure-check` (links, decisions).
- Final: one `scripts/gate-dev --pr <N>` on the head.

## Known base defects
tower-catalog cover concurrency and read-latency on 4 vCPU (catalog lane); not touched.
