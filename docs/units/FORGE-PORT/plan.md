# FORGE-PORT (CANALE8) — plan

## Alternativas

### R1. The port grew one method per need
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 An Origin adapter of all 18 operations | remendo | não: the next vendor pays 18 again | days | média | alto | 0 |
| A2 Six operations; the 18 composed from them in the port; the seven modules through the port; one contract suite per adapter | corrige a classe | sim | the unit, several commits | alta: the GitHub adapter stays the default | médio | 2 |

### R2. A vendor's gap becomes a second switch
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Wait for Origin to ship merge and status | remendo | não | unknown | alta | the switch waits | 0 |
| A2 Merge by git push of the tested merge commit, and status on the port's log, both vendor-independent, used by any adapter that lacks them | corrige a classe | sim | ~1 h | alta | baixo | 1 |

## Escolha
- R1 → A2: the narrow port is what makes the switch one key. Follow-up: Origin's `change` and `identity` once A Torre gives
  its API (the intake's gap).
- R2 → A2: the gaps close inside the port, not as keys.

## Commits
1. `docs: the intake and the research of FORGE-PORT (CANALE8)`.
2. `docs: the audit and the plan of FORGE-PORT (CANALE8)`.
3. `feat(forge): merge by git push of the tested merge commit, vendor-independent` — `scripts/lib/forge_git_ref.py`, tests.
4. `feat(forge): the six-operation contract suite, run against the GitHub adapter` — `scripts/tests/forge_events/test_forge_contract.py`.
5. `feat(forge): implement the Origin adapter with an injected client` — all six operations and the shared contract on local doubles.

## Premises
Premises: P-34.

## Tests
`scripts/run test forge-events`, `scripts/run test forge-git-ref`.

## Base defects expected
`test_config_check.StructureCheckWiring.test_structure_check_fails_on_a_registered_literal`.

## Cheapest useful effort
Action: the vendor-independent merge and the six-operation contract suite, before the Origin adapter.
Cost: about two hours of session time.
Requirement: Daniel, who asked for one switch that takes GitHub out of the operation (16:03 BRT).
Cheaper rejected: an Origin adapter of the 18 operations (every next vendor pays again); waiting for Origin's merge (unknown date).

## Origin adapter integration
`forge_origin.OriginAdapter(client, repo, log=None, refs=None)` requires a client
with `identity() -> str` and `change(repo, number) -> dict`. The dictionary uses
`head`, `base`, `head_ref`, `base_ref`, `head_repo`, `body`, and `open`, matching
the GitHub port shape. The client owns authentication and normalization.
`log` defaults to `ControlAdapter`; `refs` defaults to `GitRefs`. The remote must
belong to `repo`. Merge refuses closed or moved changes, forks, production writes
forbidden by D-054, and a lost push race.

Status is an append-only `forge.status` journal record on
`Channel('<repo>:statuses', None)`, including SHA, context, state, description,
URL and signing identity. It is separate from schema-validated event channels;
read this reserved channel through `read` to recover status history. It uses the
same log, without another configuration key. Ordinary append/read delegate to
the control plane unchanged.

GitHub remains the configured default. No Origin endpoint or configuration switch
is added. Real use still requires Origin's authenticated change/identity client
and confirmation of its metadata mapping, a repository remote, and control-plane
access. The local contract proves the adapter, not an unavailable vendor API.

## The real client (follow-up, this branch)

The paragraph above closed the unit with the client as a double. It is no longer one.
`scripts/lib/forge_origin_client.py` is the client, measured against the live API:

- Transport is the `origin` CLI. A `crsr_` key is refused as a Bearer token (HTTP 401
  measured), the key must be exchanged for a short-lived user token, and the OpenAPI spec
  documents no exchange operation. `github_api.py` speaks GitHub only, so it was not reused.
- `change` maps `PullRequest` onto the port shape; `merge` carries `expectedHeadSha`, which is
  the adapter's `head_sha`; `comments`/`append_comment` walk the opaque `nextPageToken` cursor.
- Identity is the single `user`-type namespace slug. Origin has no user endpoint, so the gap
  raises `OriginIdentityGap` instead of inventing a login.

What the live API cannot do, and therefore what the port cannot yet do:

- **Checks.** `POST /check-runs` is installation-token only. A user credential cannot publish a
  check run, so `set_status` stays on the control-plane journal.
- **Writes to a mirrored repository.** `the-tower` on Origin is an inbound GitHub mirror, and a
  mirror rejects merge, branch create, commit-from-files and ref delete (`FAILED_PRECONDITION`).
  The adapter merges by git push, so the port cannot run against a mirror at all. Flipping
  `forge.adapter` for this repository needs a native Origin repository, not a client change.
- **Forks.** `PullRequestRef` carries only `ref` and `sha`; there is no repository field and no
  fork concept anywhere in the spec. `head_repo` is therefore the read repository, truthfully.

## Commit discipline port shape follow-up (2026-11-02)

Authorized design: Daniel's execution brief, additive forge shapes and explicit capability refusals (D-283, D-285, D-286).
Premises: none

1. Declare engine-events ownership of the existing audit and plan, and record the commit plan.
2. Extend the forge surface and adapters with metadata, files, comparisons and force-push evidence; prove adapter behavior.
3. Migrate commit-check to the port, reconcile measured operations and vendor catalog, and record regression evidence.

Keep local git reads and GX-14 gated/live semantics. Compare structure diagnostics item by item with the base; leave existing defects unchanged.
