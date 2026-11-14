# engine-forge-origin — plan

## Alternativas

### R1. The port could not name Origin
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Keep the injected client and do not register Origin | remendo | não | none | alta | the switch never happens | 0 |
| A2 Register `origin` on the port and select it with `forge-events.adapter` | corrige a classe | sim | the client, the key, the contract | alta: `github` stays in the enum | médio | 2 |

### R2. Thirteen call sites still name GitHub
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Move the thirteen sites behind the port in this change | corrige a classe | sim | several units | média | a wide diff | 2 |
| A2 Map them and leave them | remendo | não | the map | alta | GitHub remains in those sites | 1 |

## Escolha
- R1 → A2: the flow calls `adapter_from_config()`. The test `OneKey.test_the_same_flow_follows_forge_events_adapter` runs one function, `exercise`, under `github` and under `origin`. The function's source names neither vendor.
- R2 → A2: the list only shrinks, and this change is the adapter. Follow-up: move each site below onto the port, then set the default of `forge-events.adapter` to `origin`.

## The port and the three adapters
`scripts/lib/forge_events.py` is the only door. `ADAPTERS` loads `origin`, `github`, `git-ref`, `control` and `file` by name. `forge-events.adapter` is the key (`origin`, `github`, `file`). The default stays `github` until the credential and the thirteen sites are ready. `file` is the local log. GitHub is not deleted.

Origin's `set_status` appends `forge.status` on `Channel('<repo>:statuses', None)` and, when the client implements `publish_check_run`, posts `POST /repos/{owner}/{name}/check-runs`. The real client does. A user token is refused before the request: check runs require an installation token. Two credentials: `forge-events.origin_token_env` (user or `oit_`), or an EdDSA app JWT exchanged at `POST /app/installations/{id}/access_tokens`. The private key is a path, never a literal.

`change` reads Get Pull Request. That response has no head repository, so `head_repo` is the repository the flow named. Merge is still `GitRefs` fast-forward, not the Origin merge route.

## The thirteen baseline calls
From `scripts/lib/adapters/engine-vendors.json`, vendor `github`, outside the adapters:

| Site | What it still does |
|---|---|
| `scripts/cloud/setup.sh:gh` | prints the installed `gh` version |
| `scripts/gate-local:github_cli` | reads a pull's head and base through `github_cli.py` |
| `scripts/lib/commit_check.py:github_api` | the commit-check REST read (`github_api._request`) |
| `scripts/lib/credentials.py:github_api` | `github_api.ping()` for the credential probe |
| `scripts/lib/delivery.py:gh` | `gh pr view` for delivery diagnostics |
| `scripts/lib/delivery.py:github_cli` | imports `github_cli` for that call |
| `scripts/lib/gate_policy.py:gh` | `gh pr view` for the diff identity |
| `scripts/lib/gate_policy.py:github_cli` | imports `github_cli.parse_json` |
| `scripts/lib/idea_to_prod.py:github_api` | reads delivery facts through `github_api._request` |
| `scripts/lib/premises.py:github_api` | reads a pull body |
| `scripts/lib/release_policy.py:github_api` | `github_api.api_base()` when refusing a merge |
| `scripts/lib/structure.py:github_api` | reads a pull body, head and comments for the structure check |
| `scripts/lib/toolchain_manifest.py:github.com` | downloads pinned toolchain archives from GitHub releases |

None of these is an `if vendor` in the flow. They are the remainder. The list only shrinks.

## Origin operation parity — 2026-11-01
The requested extension implements the existing D-283 port, not a new unit. Baseline:
18 dispatched operations, five implemented by Origin. `identity`, `append` and `read`
are adapter primitives outside this count. The common contract initially covers eight
behaviors, not all 18 operations.

Evidence: [official OpenAPI](https://cursor.com/docs/api/origin/openapi.yaml), retrieved
2026-11-01, documents list/create/update pulls, pull commits and list/create/update
comments. Comment edit is PATCH `/repos/{owner}/{repo}/pulls/comments/{commentId}`.
No repository push activity listing appears in that specification. No live API proof
is attempted: the injected Origin session is expired. Existing research's claim that
the client speaks REST directly is stale: `_run_cli` invokes `origin api`.

Alternatives: invent API equivalents (rejected: unproved); reuse the established CLI
and paginated reads plus GitRefs locks (chosen: same boundary, no new transport);
move every operation to git (rejected: comments and pull metadata are forge state).
Locks use the same lease and conditional advance protocol as GitHub; calls count
actual attempts in the client's `_call`, including failures. The CLI exposes no
conditional-response metadata, so no request is classified as not-modified.

## Commits for operation parity
1. Record evidence and plan (this document).
2. Gate comment upsert, comment append and listing, shared behavioral proofs.
3. Open pull listing and pull metadata, pagination and base-filter proofs.
4. Git-ref leases and client counters, contention and failure proofs.
5. Remaining supported lifecycle operations, independent coverage count and gaps.

Premises: none

## Cheapest useful effort
Action: Extend this adapter through injected-client contract cases for both forges.
Cost: Five commits, targeted tests at each step and one final gate.
Requirement: Daniel and engine-lane need an Origin adapter usable by the delivery flow.
Cheaper rejected: Methods that pretend success and counters returning invented zeros
would preserve the blocked flow while hiding its cause; live probes cannot prove an
expired session. Follow-up: authenticate a fresh session to attest real API routes.

### Result of operation parity
Origin now implements 17 of the 18 port operations: change, open_changes, approvals,
merge, set_status, upsert_comment, open_pulls, lock, unlock, calls, pull,
change_commits, find_change, open_change, close_change, comment and comments.
The independent count reads dispatch names from ForgeEvents (including its direct
`change` delegation) and intersects them with `dir(OriginAdapter)`, not with
operation_relations.json. The relation is updated to reflect the measured class.
`pushes` remains absent: the official public specification has no repository push
history collection. Access refuses by operation name and states that missing route.
A git commit listing would not prove push timestamps or before/after ref updates.

Shared contract assertions observe comment storage after create/edit, callable
updates and exact/newest marker selection; base-filtered pulls including drafts;
commit parent edges; latest matching changes including closed ones; created fields
and close state; conditional lease transitions; and actual request count deltas.
Origin additionally proves 404-only recreation, failed-call counting, refusal of a
counterless injected client, timeout forwarding and cross-repository lock refusal.
GitRefs remains the merge/lease mechanism, with no new forge write transport.

No new API route was attested live: comment edit/create/list, open/list/get/create/
update pulls and pull commits use transport doubles. The expired session and absent
installation token do not become fabricated successes. The pre-existing set_status
check-run path still requires an installation token. `not_modified` stays zero
because this CLI client sends no conditional requests and exposes no 304 metadata;
`sent` counts actual transport attempts, including errors.

The baseline suite and local checks passed. Structure emitted existing warnings,
including oversize units and historical intake/effort gaps. The baseline operation
relation was a snapshot; adding methods requires updating its implementation list
as well as the adapter. No unrelated baseline repair was included.
