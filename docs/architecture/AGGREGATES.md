# Aggregates: generated from their sources

Plan v3 U1, veto V4, premise P-10 (D-067, D-069 item 1). An **aggregate** is a file that sums facts that live elsewhere.
The original context map, contexts, intents and renamed baseline tests served Open University. Their targets
`context-map`, `contexts`, `intents` and `gate-suite-renames` left with the product (OU-DECOUPLE, D-111;
archive `567176bb`, D-110). The cell files under `units/cells/`, the per-unit rename files and their readers
`scripts/check-architecture.mjs` and `scripts/lib/gate_suite.py` are no longer in this tree. These are historical
relationships, not current generation or checking guarantees. The old outputs `scripts/lib/context-map.json` and
`scripts/lib/gate-suite-renames.json` also left; unit-local `gate-suite-renames.json` inputs no longer exist.

The current targets come from `generate.targets` in `config/registry/generate.json`. Each fact lives in the sources
named there; `scripts/lib/generate.py` loads the corresponding renderer. Some outputs stay committed and are checked
for drift; others are views rendered on demand.

| Aggregate | Fact now lives in | Target | Output | Committed / consumed by |
|---|---|---|---|---|
| registry owner aggregates | `config/registry/*/*.json` | `registry` | `config/registry` | yes; registry readers; owns only its generated files |
| Python contract and registry types | `contracts/**/*.json`, `config/registry/*.json` | `python-types` | `scripts/lib/generated` | yes; engine imports |
| registry and event reference | `config/registry/*.json`, `contracts/events/*.json` | `docs` | `reference` | no; people, on demand |
| code ownership | `units/*/unit.json` | `codeowners` | `CODEOWNERS` | yes; GitHub |
| unit status | `units/*/unit.json` | `status` | `docs/process/roadmap` | no; people, on demand; `STATUS.md` stays history |
| per-area literal census | `units/*/census.jsonl`, `units/*/unit.json` | `census` | `scripts/lib` | no; readers build the view through `scripts/lib/census.py` |
| fluxo-amplo lane briefs | `docs/programs/fluxo-amplo/plan.md` | `lane-briefs` | `docs/process/briefs/fluxo-amplo` | yes; lanes start from their briefs |
| lane rules digest (F78) | `docs/process/lane.md` (Rules digest) | `lane-digest` | `docs/process/lane-digest.md` | yes; `scripts/lane brief` carries it; owns only that file |

`scripts/generate <target>` writes committed targets in place and prints on-demand targets; `--out DIR` writes under
that directory, `--stdout` prints a single-file target raw, and `--list` shows each target's state.

## Current checks and retired guarantees

`scripts/generate --check` compares enabled committed targets with their regeneration (`generated drift` stage).
A renderer that fails is an error, never an empty document. The old cell-map and baseline-rename checks left with
their renderers and readers under D-111; there is no verifier for those guarantees today. The engine's manifest
ownership and dependency checks are described in [UNITS.md](UNITS.md).

## Baselines record tolerated facts

`scripts/lib/absolute-literals-baseline/**/*.json` (the "context baseline") and `scripts/lib/shared-literals.json`
record what the gate already tolerates. The census baseline is a view of the unit records, not a fresh scan of the
tree: generating tolerated entries from current offenders would make its check vacuous. Legacy per-area files remain
inputs while their areas migrate; see [the census of a unit](UNITS.md#the-census-of-a-unit-censo-no-manifesto).
`scripts/lib/shared-literals.json` remains a committed record.

## Optional publication: the train writes a separate ref

Besides committed outputs regenerated in PRs, the train has an optional publication mechanism for on-demand
aggregates. With `train.publish_aggregates` on (an `x-flag`, off), after every `integration.advanced` the train renders the targets in
`train.published_aggregates` (empty today) from the new tip's tree and keeps one commit, a child of the tip with the tip's
tree plus those files, on `train.aggregates_ref`. The commit is dated from its parent, so replaying the log gives the same
commit (`scripts/lib/train_aggregates.py`, called from `scripts/lib/train.py`; the step is measured as
`train:aggregates`). Putting the ref on the forge is the forge port's job (R1), which is the seam for Cursor Origin
(P-02, P-34).
