# GX-17 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/GX17/audit.md`).
2. Plan (this file).
3. Port + adapters: `set_status` on `ForgeEvents`, `MemoryAdapter` (fake) and `GitHubAdapter` (`POST /repos/{repo}/statuses/{sha}`, 403 -> typed error); keys `forge-events.status_enabled`, `status_context_gate`, `status_description_chars`; port tests.
4. `gate_status` writes `pending` at `begin` and `success`/`failure` from the verdict (description: tier, plan, wall, `input_digest` prefix when present); 403 non-fatal, `status: unavailable (403)` once per run; tests through the fake adapter.
5. `docs/operations/gate-status.md`.
6. Retro (`docs/units/GX17/retro.md`) and RETRO comment.

## Graph, critical path
`1 -> 2 -> 3 -> 4 -> 6`; 5 depends only on the agreed interface (keys, states, 403 line) and runs beside 3-4. Real edges: 4 needs 3's port method. Critical path ~35 min (3: 12, 4: 15, 6: 8). The unit is small and every code step touches one of two shared files, so one writer, no sub-agents (fan-out would cost more than it saves).
| Commit | Files owned |
|---|---|
| 3 | `scripts/lib/forge_events.py`, `scripts/lib/forge_github.py`, `config/registry/forge-events.json` (+ generated config module), `scripts/tests/test_forge_events.py` |
| 4 | `scripts/lib/gate_status.py`, `scripts/tests/test_gate_status.py` |
| 5 | `docs/operations/gate-status.md` |

## Premises
Premises: P-44 (GA-P03). Working premises:
- (high) GA-P03: own status via API, no Actions, Vercel untouched. CRITICAL aspect (account scope `statuses:write`) is an owner action; the code is non-fatal without it.
- (high) P-34: the status goes through the port, never `github_api` from `gate_status`.
- (medium) The verdict envelope reaches `final()` as `events` (true today via `publish_status`).

## Tests, then one gate
3: `scripts/run test forge-events`. 4: `scripts/run test gate-status`. Then base-tip `gate-dev --pr <n>`.
Known base defects: claude-session, root-identity, config (RegistryMemo) script tests (GX-ENV).
