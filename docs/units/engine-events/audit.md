# engine-events — audit
## Entradas
[intake](intake.md), [research](research.md).
## Findings
1. premises.py fetch_pr imports commit_check and github_api only to list files. fetch_body already uses change. pull_files and GitHubAdapter._pages use forge-events.github_page_size / github_max_pages (100 × 20); an empty successful page returns an empty list.
2. idea_to_prod.py GitHub.prs imports _request and reads closed pulls, keeping merged_at and Capability bodies, returning consumer key mergedAt. live_at already uses comments through the port.
3. rg -n github_api scripts/lib/premises.py scripts/lib/idea_to_prod.py reproduces two logical sites on three lines (premises import and call, idea_to_prod import).
4. No closed_changes surface exists in the base. File, memory, git-ref and control have no historical merged listing evidence.
## Causas raiz
### R1. Historical reads are outside the declared forge surface
Cadeia de porquês:
1. Why do consumers import GitHub? They read file names and historical merge facts directly.
2. Why are these reads direct? The original consumers predate the relevant shared surface.
3. Why can they remain? Catalog baseline exceptions preserve these reads, and the historical listing has no declared behavioral contract.
Classe: mecanismo faltando
Evidência: the two sites above, engine-vendors.json baseline, and the 22-operation base census.
## Distância do estado da arte
File listing has a port operation; merged listing has no common adapter oracle yet. Provider selection already has named capability refusals.
## Base defects expected
Structure unittest: 28 failures without hermetic bootstrap; structure-check: expected two errors and 15 warnings, measured separately. Existing FORGE-PORT R2 has only two whys; outside scope.

## Delivery measurement — 2026-11-02
| Former provider site | Port read after migration |
|---|---|
| scripts/lib/premises.py:github_api (file listing) | change_files; fetch_body still uses change |
| scripts/lib/idea_to_prod.py:github_api (closed merged history) | closed_changes; Capability filter and mergedAt key remain consumer-owned |

The source search now has zero github_api occurrences in both consumers. GitHub
serves all 23 operations; Origin serves 21 and refuses pushes/force_pushes. File,
memory, git-ref, control and unknown adapters refuse closed_changes by name.
Both providers default to creation-descending order, not merge-descending order.
The official local Origin spec says closed includes merged, mergedAt is unset
unless merged, and mergedSince is inclusive. Fakes enforce the bound and prove
its forwarding across cursor pages; no live Origin server claim is made.

Ownership measurement contradicted the brief: operation_demands.json belonged
to engine-events; commit 1 moves it to engine-operations. The requested audit
folder did not exist, so intake, research, audit and plan were added and owned
by engine-events. No changed code path lacked an owner. Neither declaration
JSON is generated; existing AST measurement functions reconciled the observed
sections. responsibility.accepted remains empty and closed_changes is unknown.
The vendor schema needs no change: existing baseline/classification entries only shrink.

## Validation against 6017c0f52
| Proof | Base | Delivery |
|---|---|---|
| forge-events shell suite | 268, green (5 skipped) | 274, green (5 skipped) |
| premises unittest | 37, green | 40, green |
| premises shell suite | 37 in underlying base unittest | 40, green |
| structure unittest, without hermetic bootstrap | 65 tests, 28 failures | 65 tests, identical 28 failed cases and assertion signatures (elapsed times normalized) |
| structure-check, hermetic and file store on both trees | 2 errors, 15 warnings | identical error/warning lines, including size counts |
| vendor-ports | not remeasured | 49, green |
| vendor_check.check | not remeasured | zero errors and warnings |
| operation-relations | 22 operations | 23 operations, 53 sites, 19 files; confrontation: 0 finding(s) |
| old --prs fixture command | successful | byte-identical report at fixed --now, including idea-to-prod lines |

All script proof commands use `bash scripts/<name>`, `OU_CONFIG_STORE=file`, and
`PYTHONPATH=scripts/lib/hermetic:scripts/lib` for the repository's hermetic runner.
The explicit vendor_check probe reinserts scripts/lib on sys.path because
hermetic/sitecustomize.py intentionally removes the tooling path at startup.
Neither source JSON declaration has a generator command: operation-relations is
a read-only confrontation; its measured/surface/adapters functions supplied the
observed sections. No generated artifact was hand-edited.

The plain initial structure-check observed the live exception regime (0 errors,
17 warnings); the controlled base and delivery comparisons both use the hermetic
judge and reproduce the brief's 2 errors and 15 warnings. Pre-push also exposed
two defect-lifecycle errors (MemoryAdapter lacks open_changes); the untouched
base worktree reproduces both. No unrelated base defect was repaired.
