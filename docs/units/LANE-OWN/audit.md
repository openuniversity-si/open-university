# LANE-OWN audit

Base: `mod/roadmap-integration` @ 5fe8da27d. Read-only; cheap evidence only.

## Cited sources (brief standard v2 (2): all exist on the base)

| Cited | Found |
|---|---|
| `structure.lane_errors` | `scripts/lib/structure.py:474`, GX-21; reads the manifests at the PR's merge base |
| `structure.changed_lines` / `catalog_files` | `scripts/lib/structure.py:426-445`; excludes the catalogs the literal manifest declares (D-064 amendment) |
| `train_ownership.lane_of` / `refusals` | `scripts/lib/train_ownership.py:26,42`; `lane_of` says "the same lane rule as refusals()" |
| `units/engine-structure/unit.json` | owner `engine-lane`; paths include `scripts/lib/literal-catalogs/**`, `scripts/lib/absolute-literals-baseline/**` |
| `units/web-build/unit.json` | owner `tooling-lane`; paths include `apps/web/tsconfig.json`, `apps/web/eslint.config.mjs` |
| `contracts/units/unit.v1.json` | `additionalProperties: false`; no `shared`; derived file `scripts/lib/generated/contracts_units_unit_v1.py` (`scripts/generate python-types`, the gate fails on drift) |
| `scripts/lib/units.py` `validate` | schema, then id/owner/budget/decision checks; no cross-field path check |
| `literals:census` | `apps/web/package.json` (the census files are generated) |

## Findings

1. **Two copies of the lane rule.** `lane_of` and `lane_errors` each re-implement "the units whose `paths`
   match a file, keyed by `manifest.get('lane', owner)`". Nothing makes them agree but the docstring. The fix
   is one helper in `train_ownership` that both call, so excluding shared paths is written once.
2. **Who reads the rule.** `lane_of` is reached through `pr_ready.lane_of` (the lane of `pr.ready`, and
   `gate_proof`); `lane_errors` through `structure-check` `pr metadata` (`--pr` and `--pr-body --base`).
   `refusals` is read by `train.py:174` (approval check per member) and `forge_events.unit_of`
   (`refusals(commit, files, None, list)`: every touched unit, shared ones included, which is right for
   naming the units of a change). `train_shard` and `quarantine` read `manifests`/`owner_of` only. None of
   these change except through the helper.
3. **`refusals` already keeps the approval duty** the brief asks for: a manifest outside the lane whose
   paths match is foreign whatever kind of path matched. It needs no code change, only a test that pins it
   for a shared path. Consequence to report: a tooling-lane PR that regenerates the census is decidable
   (tooling) and still needs an engine-lane approval in the train, exactly as the brief specifies
   ("sharing removes the ambiguity, never the owner").
4. **Manifests are read at the merge base.** A shared declaration takes effect for a PR only once it is on
   the base; this PR is judged by today's manifests. Every file this PR changes is engine-lane
   (`structure.py` engine-structure, `train_ownership.py` engine-train, `units.py` engine-units) or claimed by
   no unit (`units/*/unit.json`, `contracts/units/unit.v1.json`, docs), so this PR is decidable today.
5. **Gate file.** `scripts/lib/structure.py` matches `commit_check.GATE_FILE`: the body must cite an
   approved D-NNN. The rule refines D-067 (2) ("the owner is the lane"); the body cites D-067. No new
   decision row: the brief is the design under A Torre's delegation and DECISIONS.md is a shared source of
   truth this unit does not edit.
6. **Shared stays in `paths`.** A shared glob must also be one of the unit's `paths`, so `unit_of`,
   `owner_of`, `unit_check` (every production file in exactly one unit) and `train_shard` keep seeing it as
   owned. `units.py` validates `shared ⊆ paths` (the schema cannot state it).
7. **Tests.** `scripts/tests/test_structure.py:754` has a git-fixture helper for `lane_errors`;
   `scripts/tests/test_units.py` covers `validate`. No test file covers `train_ownership.lane_of` directly
   (only through `pr_ready`, `test_plan_tick.py:225`).

## Measurement in the brief, not re-run

The 17/7/6 split was measured by the coordinator at 15:05 28/10. Re-measuring needs 17 PR file lists over
REST; it changes nothing this unit builds (the declarations are the brief's), so it is not repeated. The
first real run after merge is the `pr metadata` stage on those PRs (see plan, acceptance).

## Known defects

None registered in `config/registry/defects.json` for these files.
