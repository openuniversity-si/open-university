# FORGE-PORT (CANALE8) — intake

## Pedido
Daniel, 01/11 16:03 and 16:04 BRT: "A gente consegue ter um adaptador em tudo em que não dependa do GitHub? O GitHub esteja fora
da nossa operação?" and "não pode ser virar cinco coisas, tem que virar uma coisa só." The design is A Torre's
`/workspace/torre/redesenho-canal/e8-adaptador-total.md`: one forge port of six operations (change, identity, append, read,
set_status, merge); a vendor implements all six or does not enter the key; the switch is `scripts/config set forge.adapter
origin`. Acceptance: the same test file runs against each adapter, and with api.github.com refusing everything the engine
publishes, reads, receives a decision, records, publishes a verdict and merges.

## Intenção
One switch moves the engine's operation off GitHub, and nothing else changes when it moves.

## Contexto
- Measured on `origin/mod/roadmap-integration` at `cdc2ff3e7`+ (01/11 16:3x BRT): the port (`scripts/lib/forge_events.py`) exposes
  about 18 forge operations (change, open_changes, open_pulls, merge, approvals, pull, change_commits, find_change,
  open_change, close_change, comment, upsert_comment, set_status, comments, calls, pushes, lock, unlock), and modules outside
  the adapters call them; seven modules still call `github_api` directly (gate_pin, commit_check, credentials, forge_rate,
  premises, release_policy, structure).
- CANALE7 (#1040) put append and read on the control plane (`forge_control.ControlAdapter`); the Worker is deployed with
  `EVENTS_TOKEN` (A Torre, 01/11). `forge-events.log_adapter` must not be switched alone: a read would stop reading GitHub's
  history and return 0 events for PRs that have it (A Torre).
- Origin (Cursor Origin) holds `the-tower` as an inbound mirror (namespace `openuniversity-si`); its connector (32
  tools, A Torre's) creates and reads PRs, comments and checks, has no merge and no status write.

## Regras
- P-34 (forge-agnostic, confirmed): GitHub may be neither a bottleneck nor a design dependency.
- D-069 item 7: vendor calls only in adapters. D-281, D-282: CANALE8 is the chain's piece after CANALE7. D-054: no production change.

## Problema real
The engine reaches GitHub through a port of about 18 operations and through seven modules around it, so no other vendor can
be switched in by one key. Resolved means: the port has six operations; every caller goes through them; GitHub and Origin each
implement all six; one test file passes against both; `forge.adapter` is the switch.

## Lacunas
- **Origin's API for `change` and `identity`** (the endpoint, its authentication and the PR read): known only through A Torre's
  connector; no document in the repository describes it. Asked of A Torre in the STATUS of 01/11 16:3x BRT; this unit builds
  every other part first.
- Whether history on GitHub comments must be readable after the switch (A Torre's warning): the switch carries a reader of the
  old log, decided in the plan.
