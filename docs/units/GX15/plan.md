# GX-15 plan (base `fbc09f28`, D-070)

Goal (plan §3 GX-15, plan-v2 §4 row): `structure check` becomes the tree part (24 modules minus threshold, see audit A3),
cached by content; `pr metadata` is its own stage that always reruns, can run alone (`scripts/structure-check --pr N
--metadata`) and publishes `pr.checked v1`; the GA2 Q2 base-relative modules join the local checks.

## Commits (dependency graph)

| # | Commit | Files it owns | Needs | Parallel with |
|---|---|---|---|---|
| 1 | Audit | `docs/units/GX15/audit.md` | — | — |
| 2 | Plan | `docs/units/GX15/plan.md` | 1 | — |
| 3 | Tree part cached | `scripts/lib/structure.py`, `config/registry/structure.json`, `scripts/lib/generated/config_registry_structure.py`, `scripts/tests/test_structure.py`, `scripts/tests/covers/structure-check.json` | 2 | 5 |
| 4 | `pr metadata` stage + `pr.checked` | `scripts/lib/structure.py`, `scripts/structure-check` (usage line), `scripts/lib/gate-hooks/prereq.sh`, `scripts/lib/gate-stages.json`, `scripts/lib/gate_policy.py` (stage name), `scripts/lib/gate-areas.json` (stage name), `scripts/tests/test_structure.py` | 3 (same file) | 5 |
| 5 | Local checks | `config/registry/local-checks.json`, `scripts/lib/local_checks.py`, `scripts/tests/test_local_checks.py` | 2 | 3, 4 |
| 6 | RETRO | `docs/units/GX15/retro.md` | gate | — |

Edges: 3→4 is a real edge only by file (`structure.py`); 5 shares no file with 3/4 (it calls `config_check`, `literal_census`,
`vendor_check`, `unit_check`, `perf_tests` directly, not through `structure.py`), so it runs in parallel (sub-agent).
Critical path: 1 → 2 → 3 (≈ 30 min) → 4 (≈ 30 min) → gate (≈ 10 min) → 6 (≈ 10 min) ≈ 85 min.

## Design
- **Tree part** (`structure.tree_part(root, base, today)`): the 23 tree modules + size warning; result `{errors, warnings, counts}`.
  Key = sha256 of [`structure.tree_cache_version`, head tree, base tree, merge-base tree, gate_version (`OU_GATE_VERSION`,
  else the tool root's `scripts/` tree), the tool root's `config/` tree, the config overrides, today]. No key (always run)
  when the cache is off (`structure.tree_cache_enabled=false`), the checkout or the tool root is dirty (tracked or untracked),
  or any git read fails. Only a result without errors is stored, through the storage port at `structure.tree_cache_dir`.
  The run prints `structure tree: cached|ran … s`.
- **Metadata part** (`structure.metadata_part`): `--pr-body` checks, `--pr` (commit_check, visual_guard, `Premises:` line),
  `--review`, threshold (A3). Never cached (GA-P01). With `--metadata` and `--pr`, publishes `pr.checked v1` through the
  forge_events port (producer `structure.event_producer`); a publish failure is printed and never changes the verdict.
- **Gate split**: `prereq.sh` exports `OU_STRUCTURE_TREE_ONLY=1` when sourced (before any launch, `gate-local:44`), so the
  existing `structure check` launch runs the tree part only; the hook launches `pr metadata`
  (`structure-check --metadata [--base B] [--pr N]`) next to the other prerequisites, on every run (every plan expects it;
  without `--pr` it judges nothing). `gate-stages.json`: `structure check` deterministic (version 1, inputs `**`),
  `pr metadata` non-deterministic, both needed by install.
- **Rollback**: `structure.tree_cache_enabled=false` (nothing cached); revert of the merge commit for the split.

## Premises
- P-42 (GA-P01, CRITICAL, decided): the metadata check always reruns — held by design (never cached) and tested.
- P-46 (GA-PG1, decided): the verdict of record is the pinned gate; this PR's own gate code runs only as code under test.
- Unit premise (medium): the 23 modules read only the tree, base and merge base (GA2 Q2 corrected by audit A3); a
  module wrongly classed would be cached past a metadata change. Mitigation: threshold moved out; key covers the merge base.

## Tests per commit
- 3: `scripts/run test structure-check` (cache hit/miss, disabled, dirty tree, failure not stored), `config` registry check.
- 4: `scripts/run test structure-check` (tree-only env, `--metadata` alone, pr.checked validates via `event_contracts`),
  `scripts/run test event-contracts`, `python3 scripts/lib/gate_graph.py check`.
- 5: `scripts/run test local-checks`.
- Final: one pinned `scripts/gate-dev --pr 732`.

## Known base defects expected (not this unit)
`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (GX-ENV); KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3.
