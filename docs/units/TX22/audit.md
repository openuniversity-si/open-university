# TX22 audit: literal baselines derived from the base census

Base: origin/mod/roadmap-integration at 891b835ae (28/10). Every cited line re-verified on that tree.

## What the census is today

- `scripts/lib/literal_census.py:192` `check(root, base)`: (1) the census must equal the committed list
  `literals.baseline` = `scripts/lib/absolute-literals-baseline/engine/<unit>.json` (`config/registry/literals.json:100-109`),
  exact per file, kind and value (`:202-210`: "is written N times and allowed M" for growth, "the list shrinks with the
  code" for a stale entry); (2) against `base`, the per-unit totals of the list may not grow (`:211-216`, read from the
  base tree with `git show` by `baseline_areas`, `:159-176`). **Holds.**
- `:220-234` `write(root, area)` rewrites the list; `main` (`:237-245`) has `--write [unit]` and no `--base`.
- The list: 32 files (31 units + `unowned.json`), 217 source files, **2829 entries, 2327 in `scripts/tests/`** (measured
  on this base). **Holds** (the TX audit's 2327 of 2829 is this list).
- Messages carry no line number (`:206`, `:209`, `:214`): the census keys are `kind value` without the line
  (`key`, `:120-123`), and `census()` (`:142-156`) drops the line it has in `python_literals`/`text_literals`. **Holds.**
- `scripts/lib/structure.py:491` already passes `args.base` to `check`; without `--base` (`gate-local:420` drops it when
  the fetch fails, or a local run) `check` judges only the committed list. No change needed in `structure.py`.
- `scripts/tests/literals.test.sh:5` runs only `test_literal_census.py`; `test_literal_census.py:185`
  `test_lt1_the_repository_census_equals_its_list` is the `Lists differ`-class failure of #724, #726, #735.
- Runtime today (`python3 scripts/lib/literal_census.py`, warm): **1.23 s**.

## Two lists share the folder name: scope

- `scripts/lib/absolute-literals-baseline/*.json` (top level: `admin`, `app`, `catalog`, `platform`, `scripts`, `ui`, …,
  14,191 entries) is **the apps/web D-063 exception list**, not this census. It is written and compared exactly by
  `apps/web/scripts/lib/absolute-literals.ts` / `absolute-literals.test.ts` / `census-files.ts:9`, unit
  `tooling-literals`, **tooling-lane**; its base ratchet is `structure.py:262-298` `check_absolute_baseline` (DO NOT
  TOUCH beyond one call). The audit's "scripts.json by 7 PRs, app.json by 4, catalog/platform/ui.json by trios" are these
  files. Deriving them needs the TypeScript census in tooling-lane: **out of this unit (one lane)**; it is the same T2
  change for a tooling-lane unit. This PR keeps `baseline_areas` (structure.py reads that list through it).
- `scripts/lib/absolute-literals-baseline/engine/<unit>.json` is **this census's list**: derived and deleted here.

## literal-catalogs: a different contract

`scripts/lib/literal-catalogs/<area>.json` (11 files) is the D-063 **catalog manifest**: per area, the files whose
literals *are* documented keys, with their domain and description (read by `apps/web/scripts/lib/literal-catalogs.ts`,
tested by `literal-catalogs.test.ts`; D-064 amendment). It holds no counts and is not an inventory of the census; it is
declared intent (which file is a catalog), not something the tree can compute. **Left unchanged.**

## Consumers to keep green when the engine list goes

- `config/registry/literals.json:100-120` `literals.baseline`, `literals.baseline_description` and their generated types
  `scripts/lib/generated/config_registry_literals.py:8-18` (`scripts/generate --check`).
- `docs/structure/assets.json:365` inventories `scripts/lib/absolute-literals-baseline/engine/*.json`.
- `docs/operations/local-gate.md:78` describes the list and `--write`.
- `CODEOWNERS:528` (`/scripts/lib/absolute-literals-baseline/**`) stays: the apps/web list remains.
- Prose in DECISIONS (D-068 status column) and CAP-011 names the list; history, left as is (the PR records the change).

## Rule to preserve (CRITICAL)

Per (unit, kind, value): the count in the tree may not exceed the count at the base. A new literal in a new file, a file
that gains one, and a value moved to another unit fail; a value moved between files of one unit passes.
