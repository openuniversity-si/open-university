# Engine vendor ports (D-069 item 7, plan v3.1 R1)

The engine (`scripts/`) reaches every vendor through a port. A port is a small interface plus the factory that picks
its adapter from the configuration registry; an adapter module is the only file that talks to its vendor. Callers
import the port. The forge port is M2's [`scripts/lib/forge_events.py`](../../scripts/lib/forge_events.py) with its
Origin adapter (the one live forge, D-293)
[`forge_origin.py`](../../scripts/lib/forge_origin.py), backed by [`forge_origin_client.py`](../../scripts/lib/forge_origin_client.py).
Every other port follows the same shape in
[`scripts/lib/adapters/`](../../scripts/lib/adapters/__init__.py).

| Port | Interface | Adapter today | Registry | Slots |
|---|---|---|---|---|
| Forge | Journal: `append`, `read`, `recent`; forge: 22 dispatched operations + adjacent `change` (see below) | `forge_origin.py` (Origin, D-283, D-293) | `forge-events.adapter` | |
| Agent provider ([`agent.py`](../../scripts/lib/adapters/agent.py)) | `name`, `serves(model)`, `run(request)` | `agent_claude.py` (Claude Code CLI) | `providers.agent_default` | Codex, Cursor (documented, no fake) |
| Model ladder ([`model_ladder.py`](../../scripts/lib/adapters/model_ladder.py)) | `rung(tier)`, `pick(tier, current, failures)` | the rung's agent provider (`serves`) | `providers.model_ladder`, `providers.model_escalate_after_failures`, `providers.model_escalation_step` | |
| CI runner ([`ci_runner.py`](../../scripts/lib/adapters/ci_runner.py)) | `run(pr, report_dir)` | `ci_local.py` (`scripts/gate-dev`, locally and in the cloud) | `providers.ci_runner`, `providers.ci_local_command` | never GitHub Actions |
| Storage ([`storage.py`](../../scripts/lib/adapters/storage.py)) | `exists`, `get`, `put`, `keys` | `storage_local.py` (the tier-1 result cache) | `providers.storage_adapter` | a shared object store |

Origin is implemented and selected; the registry default for `forge-events.adapter` is `origin`
(`config/registry/forge-events.json`). Implementation does not establish the adapter selected by an operator.
The port also implements local file storage and event-log routing; see `scripts/lib/forge_events.py`.

## Required forge behavior (D-285, ARQ-OPERATIONS C3)

[`operation_demands.json`](../../scripts/lib/operation_demands.json) declares required operations per consumer
file and a concrete `file::class::test` behavioral witness per adapter/operation. The shared `ForgeContract`
runs its assertions against Origin, with local transport, control-plane and ref fixtures.
Origin's journal push-history witness checks branch encoding, parent edges and newest-first order.
A witness must resolve to a test of that operation; implementing a method alone never authorizes it.
Tests must pass offline; the runtime resolves evidence by AST without importing or running test modules.
This is local contract evidence, not proof of remote availability, credentials or unobserved semantics.

Run `python3 scripts/lib/operation_demands.py` to inspect demands, evidence, implemented-but-unproven operations,
refusals and differences against `operation_relations.sites`. A missing declaration is `undeclared-demand`;
a declared consumer the extractor cannot reach is `unknown-demand`, retained and reported. Dynamic receivers,
`getattr`, shell entrypoints and callers outside `scripts/lib` remain explicit unknowns. This is the existing
textual floor, not a complete execution graph. `operation_relations.py` continues to expose its historical
unknown strings; their old Origin coverage claims do not override the recomputed C3 evidence.

The factory validates the active consumer's **whole demand before constructing any adapter or reading the board**.
`ForgeEvents` validates again on construction and before operations, journal reads/writes and batch entry, so
an injected/reused port cannot perform its first write and only then discover a later missing operation.
Active declared caller files are captured from the Python stack, including declared ancestors of shared helpers.
An intervening undeclared helper is retained as unknown and stops propagation: the configuration store's journal
must not inherit a forge demand from the flow reading configuration. `consumer=` can bind an explicit declared
consumer; an unknown explicit demand refuses. `compatibility_unknowns` exposes unrecognized caller paths and
adapter identities. Outside declared demands, a requested operation still needs its own adapter evidence;
no complete-flow guarantee is claimed for an unknown consumer.

Routing uses the **main forge's** evidence; sending journal events to file or control does not authorize their
forge operations and does not remove the main forge's demand. A partial adapter is valid for a compatible demand:
Origin serves every declared consumer, including the journal-backed push history used by `stall_report.py`.
D-293 removes the GitHub adapter, client, rate limiter, configuration and dedicated proofs.

Current reconciliation (2026-11-02): **23 operations, 53 sites, 19 consumer files**.
`closed_changes(repo, since=None)` returns `[{number, body, merged_at}]` for merged
closed changes, optionally bounded inclusively by merge time (RFC 3339). It does
not filter capabilities. Origin preserves provider creation-descending
order; callers must not depend on merge-time ordering. Origin proves all 23 operations,
including `pushes` and `force_pushes` through its journal. File, memory,
git-ref, control and unknown adapters refuse `closed_changes` rather than return `[]`.
The shared `ForgeContract.test_closed_changes_preserves_merged_facts_and_inclusive_since`
is the evidence for Origin. Origin requests `state=closed` and `mergedSince`;
`mergedAt` is unset unless merged. Offline fixtures establish the request and mapping,
not that the live server actually enforces its documented bound.

Historical Measured C3 census: **18 operations, 38 sites, 14 consumer files**; the denominator is **17 `_operation`
dispatches plus one adjacent direct `change`**, not 18 dispatches plus `change`.

| Adapter | Proven / 18 | Implemented without compatible behavior proof |
|---|---:|---|
| github | 18 | none |
| origin | 17 | none |
| file | 0 | `change` (a refusing stub, not metadata behavior) |
| git-ref | 0 | `merge` in C2's `GitRefs` census (a git helper, not a forge merge proof) |
| control | 0 | none |

`MemoryAdapter` has separate local witnesses for `change` and `set_status`; it is not a selectable forge.
C2 counts `GitRefs.merge`; the factory selects `GitRefAdapter`. These types remain distinguished, with no
forge-merge permission inferred from the helper's name.

If Daniel selects Origin, the declared demands have the following compatibility result. “Admitted” means local
evidence exists; it does not promise a remote operation succeeds. Paths below are under `scripts/lib/`.

| Operation | Declared consumer files | Origin result |
|---|---|---|
| approvals | train.py | admitted |
| calls | train.py | admitted |
| change (direct) | gate_report.py, gate_status.py, pr_ready.py, train.py, train_queue.py, train_verdict.py | admitted |
| change_commits | replay_branch.py | admitted |
| close_change | replay_branch.py | admitted |
| comment | replay_branch.py | admitted |
| comments | lessons.py, stall_report.py | evidence exists; stall_report's whole demand refuses on pushes |
| find_change | replay_branch.py | admitted |
| lock | engine_role.py | admitted |
| merge | train.py, train_verdict.py | admitted |
| open_change | replay_branch.py | admitted |
| open_changes | defect_router.py, stall_report.py, train_queue.py, train_verdict.py | evidence exists; stall_report's whole demand refuses on pushes |
| open_pulls | flow_check.py, prepush.py | admitted |
| pull | replay_branch.py, stall_report.py | evidence exists; stall_report's whole demand refuses on pushes |
| pushes | stall_report.py | **refused before the consumer's first effect: no Origin push-history witness or implementation** |
| set_status | gate_status.py | admitted |
| unlock | engine_role.py | admitted |
| upsert_comment | gate_status.py | admitted |

`change` stays a direct pass-through, guarded separately by the same evidence rule; it does not become an 18th
`_operation` dispatch. A bare adapter now receives `ForgeEventsError` naming operation, adapter and consumer,
instead of an incidental `AttributeError`. The three existing `port.adapter.change` reach-through sites rely
on factory/construction preflight. Raw adapters constructed outside the port remain outside this guarantee;
C3 does not migrate those consumers or claim to intercept arbitrary adapter access.

The independent refusal oracle is `Compatibility.test_whole_demand_refuses_before_first_effect_on_a_reused_port`
in `scripts/tests/test_forge_events.py`: a local source fixture first writes a comment, then asks for push history.
Its source and effect list are not generated from the declaration; the list must remain empty. Even installing a
`pushes` method on the fixture adapter cannot supply its missing proof.
`test_factory_refuses_before_constructing_any_adapter_or_board` separately asserts zero constructor/board calls.
The suite also checks compatible partial demand, routing, method-without-proof refusal, direct `change`, unknown
consumers, missing demands and a witness that cites the wrong operation.

## The model ladder

`providers.model_ladder` holds the rungs from the least to the most capable model: leaf (leaf, docs and mechanical
PRs), medium (mid-sized PRs) and structural (PRs that fix a format others build on, decisive work), each at effort
medium. The model is stored as data (the provider's id or alias). After two real failures (the gate's code class,
D-027) a step climbs one rung; it never climbs down while the same PR runs. `python3 scripts/lib/adapters/model_ladder.py
pick --tier leaf` prints the rung. An agent turn run through the port is a measured step: `engine.step.measured` (M2's
payload, unchanged) carries the provider, the model that served it and the tokens.

## The engine vendor check

[`scripts/lib/vendor_check.py`](../../scripts/lib/vendor_check.py) runs inside `scripts/structure-check`. The catalog
[`scripts/lib/adapters/engine-vendors.json`](../../scripts/lib/adapters/engine-vendors.json) (schema
[`contracts/adapters/engine-vendors.v1.json`](../../contracts/adapters/engine-vendors.v1.json)) names each vendor's
endpoints, CLIs and client modules, its adapters, the ports that may load them, and the baseline of calls outside them
that predate the check. A new call outside an adapter fails; the baseline only shrinks; a new adapter lives in
`providers.adapter_dir`; GitHub Actions is forbidden with no adapter and no baseline. The archived GitHub forge has no adapter;
its slot keeps detectors and one classified artifact-download baseline. The vendors the engine no longer calls (Neon, Vercel, R2, Figma) stay slots with their detectors, so a new engine call
to one fails until its port exists (OU-DECOUPLE F5, D-113).

The catalog does not yet catalog the implemented Origin adapter/client separately. Its Cursor agent slot describes a different port. This catalog diverges from the forge
implementation above; reconciling it belongs to the proposed follow-up ARQ-FORGE-CAPABILITIES, not this documentation fix.
