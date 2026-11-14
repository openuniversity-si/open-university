# EFFORT-STEP audit (read-only; evidence from `mod/roadmap-integration` at 5fe8da27)

Unit: move the cheapest-useful-effort check (motor `rules/effort.md`, `tools/effort-check.py`) into the repository as part of the `pr metadata` stage, so the gate refuses a plan or PR body that spends effort without saying who needed it.

Deadline: 90 min from launch (2026-10-28).

## Cited sources (brief standard v2 item 2)
1. `/workspace/torre/motor/v3/rules/effort.md` and `/workspace/torre/motor/v3/tools/effort-check.py` **do not exist in this session**: there is no `/workspace` on this container (`ls /workspace`: no such file or directory). The rule and the check are reconstructed from the brief: four fields (`Action:`, `Cost:`, `Requirement:`, `Cheaper rejected:`) under `## Cheapest useful effort`; refused when the block or a field is missing or empty, and when `Requirement:` names a machine (gate, train, tests) instead of an owner. The motor's 16 checks cannot be compared one by one; the repo suite is its own and is mutation-tested the same way (owner rule disabled → suite red).
2. "The language baseline" does not exist under that name (`git grep -i "language baseline"`: nothing). The shrink-only lists that do exist: `tests.unhermetic_sites` (`config/registry/tests.json`, enforced in `scripts/lib/hermetic_check.py:141`: a site absent from the base is refused, a stale site warns) and `scripts/lib/db-package-baseline.json`. The plan baseline follows `tests.unhermetic_sites`: a registry list, compared with the base's copy of the same registry file.
3. D-069 items 4, 8, 9 and D-065 (5) exist in `docs/domain/DECISIONS.md` (rows 71 and 67). No new decision is needed: the brief names those.
4. GK1's plan exists: `docs/units/GK1/plan.md`, without the block.

## The `pr metadata` stage
5. `scripts/lib/gate-hooks/prereq.sh:16` launches `scripts/structure-check --metadata [--base B] [--pr N]`; `scripts/lib/structure.py:641` `metadata_part` reads the body from `--pr-body` or from the PR over REST (`gated_fetch`) and already runs `commit_check.plan_errors(body)`, `plan_completeness_errors`, `check_premises_line`. The effort body check is one more call on the same body in both branches: no new stage, no new read.
6. The tree part (`tree_part`, `structure check` stage, cached by tree key) is where repo files are judged against the base (`check_absolute_baseline`, `hermetic_check`). The plan-file check (every `docs/units/*/plan.md` carries the block or is in the baseline; the baseline only shrinks) goes there: it reads the tree, not the PR.

## Registry and wiring
7. Every tunable is a registry entry (`scripts/lib/config.py` `config.get(name, root)`), one JSON Schema file per owner under `config/registry/`, each property with `default`, `description`, `x-unit`, `x-readers`; `scripts/generate python-types` writes `scripts/lib/generated/config_registry_<name>.py` and the gate fails on drift.
8. Every production file belongs to exactly one unit (`scripts/lib/unit_check.py`). `scripts/lib/structure.py` is in `units/engine-structure/unit.json` (owner `engine-lane`); the new `scripts/lib/effort.py`, its registry file and its test join that manifest.
9. Tests: `scripts/tests/structure-check.test.sh` runs `scripts/tests/test_structure*.py`; its selection is `scripts/tests/covers/structure-check.json`. A test named `test_structure_effort.py` is picked up by both without a new script.

## The unit checklist
10. The launch rules are the Padrão (`docs/padrao/<version>/padrao.json`, active version `coordinator.padrao_version`, read by `scripts/lib/coordinator_launch.py:28`). `docs/padrao/README.md`: "a published version is never edited in place". So the rule goes in as a new version `v4` = v3 + `effort.md` (the motor rule, copied) + `audit-and-plan.md` item (e) naming the block.

## Count
11. `ls docs/units/*/plan.md | wc -l`: 130 existing plans; none carries `## Cheapest useful effort` (`git grep -l "Cheapest useful effort" -- docs/units`: nothing). All 130 go to the shrinking baseline except EFFORT-STEP's own plan, which carries the block.

## Registered defects expected on this branch
Per `docs/operations/known-defects.md` (read at gate time); none touch `structure-check`.
