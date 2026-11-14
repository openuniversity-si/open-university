# FORGE-PORT (CANALE8) — audit

## Entradas
- [intake.md](intake.md); [research.md](research.md).

## Findings
1. The port exposes about 18 operations that callers use (intake); each is a method a vendor would have to implement.
2. Seven modules call `github_api` outside the adapters (the vendor catalog's baseline, `scripts/lib/adapters/engine-vendors.json`).
3. Origin has no merge and no status write (A Torre's connector, 01/11 16:04 BRT).
4. Switching the log alone loses the history's reader (A Torre, after #1040).

## Causas raiz

### R1. The port grew one method per need
Cadeia de porquês:
1. Por que nenhum outro fornecedor entra por uma chave? Because it would have to implement about 18 operations and the seven
   modules would still call GitHub.
2. Por que 18? Because each new need (approvals, pushes, lock, find_change, ...) added a method instead of composing the six.
3. Por que ninguém estreitou? Because GitHub was the only adapter, so a wide port cost nothing until a second one was asked for.
Classe: arquitetura/desenho
Evidência: findings 1 and 2.

### R2. A vendor's gap becomes a second switch
Cadeia de porquês:
1. Por que o Origin não entra hoje? Because it lacks merge and status.
2. Por que isso trava a chave? Because the port has no vendor-independent merge (by git push) or status (on the port's log).
Classe: mecanismo faltando
Evidência: finding 3.

## Distância do estado da arte
We have a port and one adapter, no contract suite, no vendor-independent merge or status: rung 0.

## Port shape measurement — commit discipline (2026-11-02)

Base: `aace9591c`. Execution authorized by Daniel's port-shape brief; D-283,
D-285 and D-286 govern the port and capability refusal. Existing R2's two whys
remain untouched as an acknowledged base defect.

The brief's seven accesses reproduce as **six direct REST route shapes plus one
existing port operation**, not seven direct `_request` call sites: `get` aliases
`github_api._request` in the original `fetch`. After migration commit-check has
no GitHub import, endpoint or direct request. Its catalog baseline entry and
classification have been removed; no remaining call was hidden.

| Before (`fetch`) | After | GitHub | Origin |
|---|---|---|---|
| `GET /repos/{repo}/pulls/{n}` | `pull` | serves | serves |
| `GET /repos/{repo}/pulls/{n}/commits?per_page=100` | `change_commits` with `message` | serves | serves |
| `GET /repos/{repo}/compare/{base}...{gated}?per_page=1` | `compare` → `{merge_base, behind_by}` | serves | serves |
| `GET /repos/{repo}/commits/{sha}` fallback | `commit_files` → `[{filename}]` | serves | serves via `/commits/{sha}/files` |
| `GET /repos/{repo}/pulls/{n}/files` paginated fallback | `change_files` → `[{filename}]` | serves | serves |
| `GET /repos/{repo}/activity?...activity_type=force_push` | `force_pushes` | serves | declared refusal |
| Branch pushes (already behind the port) | `pushes` unchanged | serves | existing declared refusal |

### Vendor evidence and deviations from the brief

- [GitHub pull documentation](https://docs.github.com/en/rest/pulls/pulls):
  `merge_commit_sha` can name a test merge while open. `merge_sha` therefore
  exposes it only when `merged` is true; open/closed unmerged pulls return None.
- [Origin OpenAPI](https://cursor.com/docs/api/origin/openapi.yaml), inspected
  on this session: `PullRequest.mergeCommitSha` exists and is exposed only when
  `merged` is true. `commits[].commit.message` exists. `/compare/{basehead}`
  returns `mergeBaseCommit.sha` and `behindBy`; both PR files and commit files
  have paginated collections with `files` and `nextPageToken`. Thus Origin can
  serve comparison, contrary to the brief's hypothesis. No force-push activity
  operation was found in this specification.
- `created_at` and `draft` were also absent from `pull`; additive fields now map
  GitHub's snake_case and Origin's `createdAt` / `draft`. Without these fields
  the existing commit-check readiness and timing rules would lose metadata.
- `commit_files` is the fourth new operation, needed to retain the no-checkout
  fallback without another vendor access. Surface: 18 → 22 operations.
- Missing `force_pushes` refuses through the existing `operation_demands` proof
  check / `forge_requirements.require_surface`, naming operation and adapter.
  Origin commit responses missing a message also raise CompatibilityError for
  `change_commits`, rather than synthesizing an empty message. An Origin
  commit-check consumer refuses before reading metadata because it also requires
  the already unsupported `pushes`. No selection or configuration was changed.
- Local `local_commits`, `local_files` and `git diff` remain. GX-14 tests still
  measure six calls for twelve commits; four complete fetch dictionaries (gated,
  live, checkout PR head and checkout base) were compared with the original
  `fetch` loaded from the base commit and were identical.

### Offline proof (OU_CONFIG_STORE=file; hermetic Python bootstrap)

| Proof | Base | Changed tree |
|---|---:|---:|
| `bash scripts/tests/forge-events.test.sh` | 257 green | 268 green |
| `bash scripts/tests/commit-check.test.sh` (`commit-plan.test.sh` does not exist) | 20 green | 22 green |
| `bash scripts/tests/vendor-ports.test.sh` | — | 49 green |
| `bash scripts/tests/operation-relations.test.sh` | — | 42 green |
| `bash scripts/tests/push-guard.test.sh` (replay/stall consumers included) | — | 24 green |
| `vendor_check.check(root)` | — | 0 errors, 0 warnings |
| `python3 scripts/lib/commit_check.py --local` | — | 0 refusals |

The existing `--fixture` test still passes with no new mandatory fixture field.
New tests cover merged versus open `merge_sha` (including a misleading test
merge SHA), message preservation and named missing-message refusal, paginated
PR files, commit files, comparison, named force-history refusal and fetch refusal
before any Origin read. Existing replay/stall and other port consumer tests pass.

The adapter catalog schema `contracts/adapters/engine-vendors.v1.json` describes
vendor access declarations, not forge return values. It needs no schema change;
`json_schema.compatible(base_schema, current_schema)` returns `[]`. Shapes remain
additive, and existing readers ignore the new optional pull fields.

The relation was refreshed programmatically from the repository's
`operation_relations.surface()`, `measured()` and `adapters()` functions, retaining
responsibility declarations. No generated sites/counters were hand edited.
`bash scripts/operation-relations` measures 22 operations, 51 sites, 19 files and
0 confrontation findings (base: 18 / 45 / 19). `operation_demands.confront()` is
also empty. The obsolete engine-commit-plan → engine-github dependency was removed.

### Structure comparison, item by item

Both trees report **2 errors and 15 warnings**. Identical errors: `effort` in
`docs/units/R1/plan.md`; R2's two whys in this audit. Identical warning identities:
D-004, D-020, D-021, D-036 pending proofs; missing paths in engine-budgets (one),
engine-coordinator (three), engine-generate (one); size warnings in engine-config,
engine-coordinator, engine-events, engine-flow, engine-gate-speed and engine-train.
All diagnostic text is unchanged except the existing engine-events size value,
1756 → 1773 production lines. The list is therefore equal by rule/path and count,
not byte-for-byte; no warning or error was suppressed to force equality.
