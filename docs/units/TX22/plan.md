# TX22 plan: literal baselines derived from the base census (T2)

Lane engine-lane, branch mod/tx-literals, PR #745, base mod/roadmap-integration (891b835ae). Decision D-070, premise
P-46. Audit: [audit.md](audit.md).

## Shape

`check(root, base)` keeps the LT1 rule and drops the committed list: allowed(unit, kind, value) is the census of the
base tree, computed at check time. Per (unit, kind, value), the tree's count may not exceed the base's. The base tree is
the merge-base of `base` (or, without one, of the registry key `literals.base_ref` = `origin/mod/roadmap-integration`)
with `HEAD`. Its census reuses the current census for every scanned path `git diff --name-only <merge-base>` does not
name (same content), and reads the others with one `git cat-file --batch` (the `git show` of each changed file), cached
per run. The current rules and unit manifests judge both trees, so a literal moving with its file to another unit by a
manifest change is not a new literal; a literal moved to a file of another unit is. Without the base ref (offline):
fail closed with one exact message naming `git fetch` and `--base`.

An error names the unit, the value, both counts, then each `file:line` that grew and the fix: a registry entry in
`config/registry/<owner>.json` with `x-readers` naming the file, read with `config.get`, or, if it is not a value,
`literals.allowed_values` / `literals.allowed_numbers`.

## Commits (dependency graph: 1 → 2 → 3 → 4 → 5 → 6)

| # | Delivers | Files | Targeted tests |
|---|---|---|---|
| 1 | audit | docs/units/TX22/audit.md | none (docs) |
| 2 | this plan | docs/units/TX22/plan.md | none (docs) |
| 3 | `check` derives the allowed counts from the base census when given a base; `file:line` + registry fix in the message; the list is still compared without a base | scripts/lib/literal_census.py, scripts/tests/test_literal_census_derived.py (new), scripts/tests/literals.test.sh, units/engine-literals/unit.json (+ `scripts/generate codeowners`) | literals.test.sh, structure-check.test.sh |
| 4 | without `--base`: merge-base with `literals.base_ref`; offline fails closed; `main --base`; the list is no longer read | literal_census.py, config/registry/literals.json, generated types, tests | literals.test.sh, structure-check.test.sh |
| 5 | delete `absolute-literals-baseline/engine/**`, `write`/`--write`, `literals.baseline*`; docs and assets inventory | the list, literal_census.py, registry + generated, docs/structure/assets.json, docs/operations/local-gate.md, tests | literals.test.sh, structure-check.test.sh |
| 6 | retro | docs/units/TX22/retro.md | the single final pinned gate-dev |

## Premises

| Premise | Radius | Mark |
|---|---|---|
| The same fixtures fail before and after: a new literal in a new file, a listed file that gains one, a value moved to another unit; a move inside one unit passes | every PR touching scripts/** | **CRITICAL** |
| `git diff --name-only <merge-base>` names every scanned path whose content differs (worktree, staged and `git add -N` included) | the derived count is wrong if not | CRITICAL |
| Fixture checkouts of other checks without the literals registry stay unjudged (`check` returns early) | structure-check.test.sh, test_structure | high |
| The gate passes `--base` or the checkout has `origin/mod/roadmap-integration` (gate-local fetches it, :420) | a gate without the ref fails closed, by design | medium |
| The apps/web D-063 list (top-level `absolute-literals-baseline/*.json`) is tooling-lane and stays | out of scope, recorded | low |

## Pending PRs

Every pending PR that edits a baseline (#618 #622 #625 #626 #632 #633 #635 #588 #591 #592 #600 #641 #644 #675 #645
#674 #681 #649 #659 #663 and #742) resolves its conflict at its next base merge by taking the base side of
`scripts/lib/absolute-literals-baseline/engine/**` (after the contract step: its deletion); its apps/web top-level list edits are unaffected by this PR.

## Registry keys

`literals.baseline` and `literals.baseline_description` are no longer read. D-068 (3) removes a parameter only after a
revision that marks it `deprecated` (`scripts/lib/schema_compat.py`), so this PR marks both deprecated and a later
revision removes them.

**Expand then contract (decision after pinned gate run 2).** The pinned gate (D-070 (e), P-46) judges this head with the
base's tooling. The base's `literal_census.check` reads `literals.baseline` whenever the key exists and requires the
list to equal the census; the base's `schema_compat` refuses removing the key unless a base revision marked it
deprecated. No single head satisfies both, so this PR is the **expand** step: the new code derives the counts and never
reads the list; the list stays, equal to the census (rewritten for engine-literals with the base's `--write`), and both
keys are deprecated. The **contract** step (delete `scripts/lib/absolute-literals-baseline/engine/**`, both keys, the
assets glob) is a small engine-lane change once this PR is the base; the pinned tooling is then this code, which
ignores the list, and schema compat allows the removal.

## Gate

Fast checks before every push. One pinned gate-dev at the end (offline file config store), then pr.ready, MERGE-READY.
