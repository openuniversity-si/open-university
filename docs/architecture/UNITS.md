# Units: manifests, map and ownership (D-067)

A **unit** is a piece of code with its own contract, owner and battery (plan v3 §4.2). A **lane** is one long
session that exclusively owns a set of units (D-065 (4)). This page is the guide to the unit skeleton of PR U0: the
manifest format, the generator that measures and proposes the cut, the ownership check, and the library the train
(M3) and the CODEOWNERS target (G1b) call. Nothing has moved yet: every manifest lists today's paths, and units move to
`units/<id>/` one lane PR at a time (U4).

**Physical form (S1, P-03):** units stay logical. A unit is a manifest and a checked boundary, not a
`package.json`; the spike that made `progress` a workspace package is in
[S1](../process/spikes/S1-progress-workspace-package.md) with the preconditions to reopen it.

## The manifest

`units/<id>/unit.json`, shaped by [`contracts/units/unit.v1.json`](../../contracts/units/unit.v1.json) (JSON Schema
2020-12, the one schema language of D-068 (5)). Required: `id` (equals the directory),
`purpose`, `cell`, `owner`, `paths`. Slots: `requires` (allowed dependencies, unit id to a caret range; seeded from the
measured import graph, enforced since U2), `ring` and `rules` (U2, below), `contract` and `battery` (filled by U3a and
U4), `intents`, `decisions`, `invariants` and `premises`. The engine's units are under `units/engine-*`.

- **owner** is a lane from the registry entry `units.owners` (`scripts/config describe units.owners`). It is
  forge-agnostic: a forge identity is derived from it, never written in a manifest.
- **paths** are repository-relative globs: `*` stays inside one segment, `**` spans any segments (`a/**` is `a` and
  everything under it), and every other character is literal, so `[courseSlug]` names a folder.
- **budget** is not a number in the manifest. The size budget is the registry entries `units.size_target`,
  `units.size_ceiling` and `units.context_budget` (P-04), and the battery time is `battery.unit_time_limit`. A
  manifest may only override one of the three size entries, keyed by its registry name, and must cite the decision
  that allows it:

```json
"budget": { "units.size_ceiling": { "value": 2000, "decision": "D-0NN" } }
```

An override without `decision`, or citing a decision that is not in `docs/domain/DECISIONS.md`, is refused.

## The library (M3, G1b)

`scripts/lib/units.py`; each function takes an optional `root` (default: this checkout) and reads the manifests once.

| Call | Returns |
|---|---|
| `unit_of(path)` | the id of the unit whose globs match a repository-relative path, else `None`; `UnitError` if two match |
| `units_of(path)` | every matching unit (more than one is an ownership error) |
| `owner_of(unit)` | the unit's owner lane; `KeyError` for an unknown unit |
| `owner_of_path(path)` | `owner_of(unit_of(path))`, else `None` |
| `budget(unit, name)` | the unit's value of a size entry: its cited override, else the registry value |
| `manifests()` | every valid manifest by id; `UnitError` when any manifest is invalid, so no caller decides on a broken map |
| `production(files)` | `(production files, test files)` among paths, from `units.production_globs` and `units.test_globs` |

The train's ownership refusal asks `owner_of_path` for each changed file and refuses a file whose owner is not the
PR's lane unless that owner approved it (D-069 item 8). The CODEOWNERS target (`scripts/generate codeowners`, committed at the repository root, checked by the `generated drift` stage)
maps each manifest's `paths` to the forge identities of its `owner` lane (`generate.codeowners_identities`); deeper paths
are written after shallower ones because the last matching pattern wins. From a shell: `scripts/units owner <path>...`, `scripts/units who <unit>...`,
`scripts/units list`.

## The map generator

- `scripts/units propose [--json]` cuts today's production files into candidates: a directory whose production lines
  fit `units.size_ceiling` is one candidate; a larger one splits into its subdirectories, and its own files are
  clustered by affinity (`units.cochange_weight` × co-change of the newest `units.cochange_commits` commits, plus
  `units.import_weight` × import density); a candidate below `units.merge_floor_lines` joins its closest sibling while
  the pair fits `units.size_target`. Import aliases come from the tsconfig `paths` of the files `units.tsconfig_files`
  names.
- `scripts/units measure [--json]` reports, per manifest, its own production lines, its transitive import closure in
  lines and tokens (bytes ÷ `units.bytes_per_token`), its cohesion (the share of its commits that stay inside it) and
  whether it is above its ceiling or its context budget. Data files and generated files count toward no size
  (`units.size_exempt_globs`).
- `scripts/units measure --emit [--pr N]` does the same inside an `engine.step.measured` step and publishes one
  `unit.oversize` per unit above its ceiling through the `forge_events` port; re-emitting is a no-op.

## The ownership check

`scripts/lib/unit_check.py`, a module of `scripts/structure-check` (the gate's `structure check` stage):

- every manifest validates (schema, registered owner, cited override);
- every production file belongs to exactly one unit, and no tracked file belongs to two, so two lanes never edit the
  same file (P-13). This is D-064 (d)'s parallelism simulation turned into ownership by manifest;
- a glob that matches no tracked file warns;
- a unit above its ceiling warns while `units.oversize_fails` is false; one PR citing D-067 flips it once U4 has split
  today's large contexts.

A new production file goes into the manifest of the unit that owns it in the same PR. A new unit is a new
`units/<id>/unit.json`; `scripts/units measure` shows whether it fits.

The cell files under `units/cells/` and the context-map target left with Open University (D-111).
[AGGREGATES.md](AGGREGATES.md) records that history and lists the current generator targets.
## Architecture rules and addresses (U2, U3a)

Three manifest features served Open University's TypeScript project and lost their checker with it (OU-DECOUPLE,
D-111; the archive is `567176bb`, D-110): `rules` and `ring`, the architecture rules as data that
the retired `scripts/check-architecture.mjs` compiled for the product's source (U2), and the stable addresses `@ou/<id>` that
`scripts/generate addresses` wrote into the project's tsconfig `paths` (U3a). The schema keeps the slots, so a product
that comes back can fill them again; no engine check reads them now (OU-DECOUPLE F5, D-113).

One manifest field is enforced besides the ownership check:

- **requires**: `scripts/lib/unit_check.py` (structure check) measures the imports between units with the graph of
  `scripts/lib/unit_map.py` and refuses one the importing unit does not declare; a `requires` naming no unit fails and
  one nothing imports warns. A new cross-unit import is therefore a manifest change, made by the unit's owner lane.

## The unit battery (tier 1, U3a)

`scripts/unit-battery <id> [--json] [--emit [--pr N]]` is tier 1 for a unit (P-12, veto V5): the whole of what the
unit owns, never a sample.

| Step | What runs |
|---|---|
| contract | when the manifest has `contract`: its `entry` must be a file of the unit |
| types | `tsc --noEmit` over a per-unit tsconfig (under `battery.unit_types_dir`, outside git) that includes only the unit's TypeScript files and the step's global declarations; tsc follows their imports |
| unit, int, perf and perf-int tests | the unit's test files, each in the vitest project of its kind (the int ones need `source scripts/cloud/env.sh`) |
| script tests | each `scripts/tests/*.test.sh` of the unit |

The contract tests of the units that require this one (`battery.contract_test_globs`) run with it. The steps are the
registry data `battery.unit_steps` and run concurrently; a step with no file is skipped. The TypeScript steps judge
the product under `products/web` (`battery.project_tsconfig`); the engine has none, so an engine unit runs its
contract and script tests (OU-DECOUPLE F5, D-113). The battery is red when a step
fails or its wall time exceeds `battery.unit_time_limit`, which is never loosened (D-069 item 14). `--emit` publishes
`engine.step.measured` per step (`unit-battery.<step>`) and for the battery. A manifest's `battery.command` slot stays
empty: the command of every unit is `scripts/unit-battery <id>`.

## The census of a unit (CENSO-NO-MANIFESTO)

**A datum more than one unit writes that lives in a repository file is an accident waiting for the second unit.** N
writers of one file make N(N-1)/2 pairs that can collide. A merge does not lower that rate; it only lowers how many
collisions reach a person. The literal census (D-063) was such a datum: 31 per-area files, each one owned by
`engine-structure`, written by 69 units. A unit's datum lives in the unit's own folder, written by one command.

- **The record.** `units/<id>/census.jsonl` (`census.record_file`), one event per line, shaped by
  [`contracts/units/census.v1.json`](../../contracts/units/census.v1.json): `add`, `set` or `remove` of a `catalog`
  entry (a D-063 literal catalog: `domains`, `holds`, optional `generatedFrom`, `builders`) or of a `baseline` entry (a
  file's remaining offenders, per `<kind> <value>`), with `by`, `why`, `at` and a digest chain
  (`scripts/lib/audit_chain.py`). The unit's live census is the fold of its events.
- **The one writer.** `scripts/census add <path> --why <why>` (a baseline entry, counts read from the absolute scan)
  or `scripts/census add <path> --catalog --domain <d> --holds <text> --why <why>`; `remove`, `sync [--unit U]` (the
  baseline brought to the scan), `migrate <area>` (an old per-area file moved
  into the records), `list`, `show <path>`. The unit is taken from the manifests. A path of no unit, or of two, is
  refused.
- **The door.** `scripts/census check`, run by `structure-check`, refuses a record that does not match the schema, is
  not the writer's canonical text, breaks the digest chain, does not extend the base's events (append-only), or holds
  a path that belongs to another unit. It also refuses a per-area file that the base does not have, so the migrated
  files never come back. A hand edit fails the same way an unregistered literal does.
- **The view.** `scripts/generate census` renders the old per-area shapes (`scripts/lib/literal-catalogs/<area>.json`,
  `scripts/lib/absolute-literals-baseline/<area>.json`) on demand, `committed: false`, like the current `status` target.
  No pull request carries it, so none can conflict on it.
- **Hermetic read.** The gate judges a commit from its checkout alone. The readers (`scripts/lib/census.py`, and
  through it `structure.py`) read the records in the tree and build the area view in
  memory. **A census entry is an input to a verdict, so it is never kept in a remote store: there, the same commit
  could be judged differently at two times.** `scripts/config` and `forge_events` can provide one
  (`config.store_adapter: file | control`, with the gate pinned to `file` for this same reason). Here the API is the
  write path and the query path, not a network hop.
- **Migration.** Until program [`censo-no-manifesto`](../programs/censo-no-manifesto/plan.md) has moved every area
  (CN3), the readers merge the records with the per-area files
  still present, and a path held in both is refused.

### Generated files that must stay committed

Some files are generated and are also read from the tree by something outside this repository. `CODEOWNERS` is read by
GitHub when it assigns reviewers. Such a file cannot become an on-demand view. Their conflicts are settled by the tool that merges:
`.gitattributes` names the `regenerate` driver (`scripts/merge-regenerate`, which `scripts/cloud/setup.sh` registers),
and the driver writes the regeneration from the merged sources. A renderer that keeps hand-written content from its
own output declares `strip(root, text)`, so only that part is merged 3-way. A conflict in the sources
themselves stays a conflict. A file the generator can build on demand is not committed at all, which is the better of
the two answers.
