# Engine operations — observed scope and proposed boundaries

Observation: worktree `/tmp/wt-arq-audit`, revision `09554c363`, 2026-11-01,
 before C1/C2. Scope: ARQ-SISTEMA audit F1, change → proof → queue → merge,
plus configuration and verifiers. This is not a census of library functions or
an authorization to switch forge. All named units currently use `engine-lane`;
path ownership does not establish exclusive ownership of an operation.

This map is prose. The measured relation beside it is
`scripts/lib/operation_relations.json`, read and confronted with the tree by
`scripts/lib/operation_relations.py` (`scripts/operation-relations`): that file,
not this one, is what a consumer or a check reads. Where the two disagree the
relation is right and this page has to be reconciled; the relation extends no
guarantee this page does not, and this page extends no guarantee the relation
does not.

## Current port shape reconciliation (2026-11-02)

The historical observations below predate the current adapters. The measured
relation now has **23 operations, 53 sites, 19 files** (base: 18 / 45 / 19).
`change_files`, `commit_files`, `compare` and `force_pushes` extend the surface;
`pull` adds optional merge/readiness metadata and `change_commits` preserves
messages. GitHub implements all 23 operations (29 public methods). Origin
implements 21 (25 public methods); `pushes` and `force_pushes` are explicit
capability refusals, not empty histories. Origin's public API does provide
comparison and commit messages. Commit discipline now consumes only the port;
its former GitHub baseline entry is removed. Capability availability neither
changes the selected adapter nor establishes operational responsibility.
`closed_changes(repo, since=None)` returns merged closed changes as
`{number, body, merged_at}` with an inclusive RFC 3339 merge-time bound.
Both adapters preserve the provider's default creation-descending order, which
is not merge-time order; the consumer sorts by `mergedAt`. GitHub filters merge
time locally after all pages; Origin sends `mergedSince` and also checks locally.
The shared contract proves these facts offline, not live Origin server behavior.
Premises now uses `change_files` and the historical report uses `closed_changes`;
its `Capability:` filter stays in the consumer. Four catalog exceptions remain:
CLI version, credential probe, origin URL and artifact hosting. File, memory,
git-ref, control and unknown adapters refuse unsupported historical listing by name.
The JSON relation and demands are source declarations, not generated artifacts;
observed sites and counts were reconciled using `operation_relations`' AST readers.
See [measured evidence](../units/FORGE-PORT/audit.md#port-shape-measurement--commit-discipline-2026-11-02).

## Operations and responsibility (R1)

The requester initiates the operation; the executor implements it. Configuration
below was read through `config.get` in this checkout; it describes selection,
not proof that a remote executor is running. “Proposed” means the approved plan,
not an implemented guarantee. Evidence paths are relative to the repository.

| Operation | Requester → executor implemented today | Selected today / limit of observation | Ideal/proposed in the approved plan |
|---|---|---|---|
| Inspect push and warn about overlap | pre-push → `prepush.open_pulls/overlap`, forge port → adapter (`scripts/lib/prepush.py`) | GitHub adapter; overlap concerns common files, not Git conflicts | Map responsibility only (R1 A1); no new exclusive-operation check |
| Select and execute proof | gate entry → gate policy/selection and gate-local; batch plan → `gate_batch.plan` | `train.tier2_command=['scripts/gate-batch','--tier','2']` | Preserve selection and proof; unify composition mechanism (R2 A2) |
| Compose members in order | train → `GitWorkspace.combine`; batch gate → `merge_union` (`train.py`, `train_git.py`, `gate_batch.py`) | Both implementations available and linked by tier-2 command | One shared primitive, two independent executions; not N instead of 2N merges |
| Verify declared batch head | tier-2 caller → `gate_batch._plan/given_head` | Reconstructs members and compares trees even with supplied head | Preserve independent reconstruction and reject wrong tree |
| Discover/admit/order queue | train → `train_queue.QueueIndex.build`, ownership/verdict modules; port reads changes/events | GitHub port; lane checks concern path ownership (`train_ownership.py`) | R1 map only; complete operation contract deferred to proposed ARQ-OPERATIONS |
| Request exact-head merge | train → `ForgeEvents.merge` → selected adapter | GitHub helper arguments interpreted as REST by `github_api.run_http`; Origin implementation uses GitRefs, not client's API merge endpoint | No selection change or session merge; train remains merger |
| Validate, append and replay events | producers/readers → `ForgeEvents`, routing adapter and log adapter (`forge_events.py`) | `adapter=github`, `log_adapter=control`, `board_issue=0`; `engine.step.measured` and `gate.started` routed to control | Describe available vs selected; no log migration |
| Read/update configuration | config CLI/readers → `config.py` registry and replay of `config.changed` | Registry defaults plus change-store overrides; not inferred from adapter availability | No configuration writes in this unit |
| Verify paths and dependencies | structure/local checks → `unit_check.ownership/dependencies`, `unit_map` | Paths and recognized static imports; dynamic GitHub/control/Origin selections absent from measured graph | R4 A2 later: represent dynamic relations; still not forge capability validation |
| Select unit proofs | unit battery caller → `unit_battery.plan` | Selection by owned paths/contracts; not yet intersection with covers | R5 A2 later: derive proofs from production ownership intersected with covers |
| Refuse contract/process violations | hooks/gate → `commit_check`, `structure`, `vendor_check` | Vendor baseline permits 13 external GitHub sites (`adapters/engine-vendors.json`); D-260 can lift some locks | No claim of complete port isolation or semantic exclusivity |
| Discover and execute jobs | service entry → `service_runner`; claim/lease/heartbeat → control plane (`services/control-plane/src/core.js`) | `service.transport=git`; remote executor availability not measured here | R7 A1 later: distinguish checkout, remote state and delivery evidence; no readyz change |

The operation map reduces rediscovery; it does not resolve R1 structurally.
ARQ-OPERATIONS and ARQ-FORGE-CAPABILITIES are proposed follow-ups, not opened units.

## The observed relation (C2, D-285)

`scripts/lib/operation_relations.json` declares the measured scope at base
`38538045e`: **23 operations, 53 call sites across 19 files** under `scripts/lib`.
Twenty-two names dispatch through `ForgeEvents._operation`; `change` is the
direct adapter pass-through. The counters, sites and adapter rows are confronted
with the tree on every run: undeclared calls, stale sites, omitted or unowned
consumers, absent implementations and mismatched counts are printed as findings.

`change` is the widest operation: 15 sites in 10 consumers across 7 units.
The complete surface spans 19 consumer files and 12 units. These crossings are
why one operation cannot be assigned a unit owner from the path that calls it.

**All 23 operations have one accepted accountable party: `engine-lane`.**
The Tower's direction (Daniel) authorized acceptance on 2026-11-02 in
[D-287](../domain/decisions/D-287.md). Each acceptance records matching
`responsible` and `accepted_by`, with that decision as evidence; every observed
`responsible` is also `engine-lane`, so the report shows 23 responsible and zero
unknown. A single party deliberately answers for the operation surface: 23
separate owners would invent an organizational structure that does not exist.
This attributes no operation to a consumer unit. Adapter implementation and
ownership of a calling file still prove no operation responsibility (D-285).
C5 continues to refuse missing, invalid or conflicting acceptances.

The repository integration proof reconstructs 23 missing-responsibility refusals
without these acceptances on both adapters and proves their removal. GitHub has
zero remaining refusals; Origin retains three pre-existing `unproven-demand`
refusals for `pushes` and `force_pushes`.

The configuration census closed too (D-289): the 17 `forge-events.origin_*`
parameters had no reader once the Origin client took its settings from
`origin-client`, and they left the registry in the same revision that fixed the
three declarations whose consumer files no longer spelled the key. The
`operation_check` configuration source reads 0 finding(s) on both adapters; its
former 21 `stale-consumer` and 17 `unknown-key` rows are gone, not waived.

The following adapter counts and consumer observations are historical; the
current port shape reconciliation above and the JSON relation supersede them.

Implementations, read by AST from the modules themselves: `GitHubAdapter` 24
public methods, `OriginAdapter` 9, `FileAdapter` 4, `ControlAdapter` 3 and
`GitRefs` 8 — the last three are not adapters of the gate's operation set. Of the
18 operations the Origin adapter implements 5 (`approvals`, `change`, `merge`,
`open_changes`, `set_status`), so **13 have no Origin implementation**: `calls`,
`change_commits`, `close_change`, `comment`, `comments`, `find_change`, `lock`,
`open_change`, `open_pulls`, `pull`, `pushes`, `unlock`, `upsert_comment`. A
missing implementation is a gap of this adapter, not evidence that no forge could
serve it.

The engine names 7 of the 18 — `lock`, `unlock`, `change`, `open_changes`,
`merge`, `approvals`, `calls` — and reads its journal outside this set.
`approvals` is dead today: its only site is `train.py` through
`train_ownership.refusals`, which compares `manifest['lane']` with the owner, and
all 47 manifests name `owner=engine-lane` with no `lane`, so the comparison never
refuses. `read` is a journal operation of the port, not an operation of this
relation.

Unknowns the relation carries explicitly, none of them hidden: the census is
textual reach over `scripts/lib`, so a bash entrypoint, a `getattr`, a `**kwargs`
pass-through or a test double is unobserved and the count is a floor (F3); the
relation records which operation a call names, not that one adapter behaves like
another (F2); the 13 GitHub accesses outside the adapters allowed by the vendor
baseline are not operations of this relation; and selection is read from
configuration, never from this file (R6).

## Consumer × adapter capabilities (R3)

AST reconfirmation: parse `scripts/lib/forge_github.py` and `forge_origin.py`,
select the named class, count directly defined FunctionDef/AsyncFunctionDef whose
name does not start with `_`: **24 GitHubAdapter**, **9 OriginAdapter**.
Origin's count includes auxiliary static `status_channel`; GitHub's includes
`rotate`, `recent`, `issue_comments`, `calls`. These are not 24 requirements for
every consumer. No inheritance or client methods were counted as adapter methods.

Each cell states the required operations and whether that adapter implements
them. `emit` is port-level validation/enveloping followed by adapter `append`;
`read_window` uses adapter `read`. Optional queue `events_since` is an optimization,
not a requirement (`train_queue.QueueIndex.build`). Journal routing can choose a
different adapter from the forge operations; Origin delegates its log to control.

| Consumer (evidence in `scripts/lib/`) | GitHubAdapter: required / implemented | OriginAdapter: required / implemented |
|---|---|---|
| Train/queue/ownership (`train.py`, `train_queue.py`, `train_ownership.py`) | `change, open_changes, approvals, merge, append, read`: all implemented | Same required: all implemented; merge via GitRefs; log via ControlAdapter |
| Push overlap (`prepush.py:open_pulls`) | `open_pulls`: implemented | `open_pulls`: absent; switch breaks overlap lookup |
| Branch replay (`replay_branch.py`) | `pull, change_commits, find_change, open_change, comment, close_change`: all implemented | Same required: all absent; switch breaks replay |
| Stall report (`stall_report.py`) | `pull, pushes, comments, open_changes, read, append`: all implemented | Same required: `open_changes, read, append` implemented; `pull, pushes, comments` absent |
| Lessons journal (`lessons.py`) | Port `emit/read` → `append/read`: implemented | Same required: implemented via ControlAdapter |

This matrix covers the concrete consumers inspected in audit F6; it does not
certify every engine flow. Additional public GitHub methods are `rotate, recent,
upsert_comment, identity, set_status, issue_comments, calls, lock, unlock`;
Origin additionally defines `identity, status_channel, set_status`. Status in
Origin appends a journal entry and calls optional client `publish_check_run`;
that is not evidence of an installation token or a live published check.

`ForgeEvents._operation` checks method presence only at call time. No construction
boundary validates a consumer's capabilities. Thirteen authorized baseline
GitHub call sites outside adapters remain a separate migration constraint
(`vendor_check.py`, `adapters/engine-vendors.json`). Implemented Origin is not
selected Origin: the effective forge/log selection read here remains GitHub.
R3 A1 documents compatibility gaps; it neither implements R3 A2 nor permits a
forge swap. R6's distinction between implemented, selected and proposed applies
to every row above.

## Proof limits

`scripts/tests/test_unit_check.py` proves unique path ownership and declared
`requires` against the measured import graph. It does not prove exclusive
operation ownership, the completeness of this documentary scope, or forge
substitutability. `scripts/tests/test_operation_relations.py` proves the
confrontation itself — an undeclared operation, a stale site, an unowned
consumer and an implementation the adapter does not define are exposed, and
implementation is never read as responsibility — against fixture trees, and that
this checkout's declaration agrees with its own tree. It does not prove that the
census is complete, that any adapter behaves like another, or that a forge may be
swapped. No global intake counter is declared zero by this map.

Premises: none

## Origin parity update (2026-11-01)
The historical census above predates the Origin extension. The current adapter
implements every port operation, measured from port dispatches and `dir(OriginAdapter)` in the
shared contract. The Origin public specification provides no repository push-history route, so
`pushes` and `force_pushes` are answered from git (D-300 addendum; before it, from the control
plane's `ref.updated` journal): this clone's reflog of `refs/remotes/<remote>/<branch>`, where git
records each push of the branch, and the adapter answers only when that reflog proves the branch's
history: it reaches the creation, holds only this clone's pushes, and ends at Origin's head
(`git ls-remote`). Otherwise it refuses and names the reason. Commits are not push events.
`scripts/lib/operation_relations.json` reflects the new implementation set.
Route mappings are proved offline; no live Origin authentication proof is claimed.
