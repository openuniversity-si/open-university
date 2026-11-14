# ORIGIN-FINISH — intake

## Pedido
Daniel, 02/11/2026 15:59 BRT, as given: "Em paralelo, para que não deixemos de lado, tenha uma sessão para finalizarmos a
questão do Origin." Standing target (Daniel 01/11): Origin first, in the operation; one forge port with Origin as the
provider actually used, GitHub kept only as a live adapter behind the port; the project ends only when GitHub is out of
the operation. The coordinator's brief: close the remaining baseline calls and port operations, make Origin the forge
the operation uses (no dual path, no fallback), prove a PR end to end on Origin, and write the exact outside steps when
something can only be done outside the repository.

## Intenção
The engine must not be tied to one forge vendor: the delivery flow (gate, pr-ready, train, merge, statuses, events)
speaks only to the forge port, and the forge that actually holds the repository and the operation is Origin. GitHub stays
selectable behind the same port, never a second path.

## Contexto
- Base `mod/roadmap-integration` at `98cf1db5` (02/11).
- The port is `scripts/lib/forge_events.py`; one registry key, `forge-events.adapter`, selects the forge (D-283). Its
  default is `github`; the description says it stays so "until an operator sets this one key to origin" (the change
  store, `scripts/config set`).
- The event journal is already off GitHub: `forge-events.log_adapter` is `control` (CANALE7, D-282, #1062).
- The coordinator's leads (13 → 9 baseline calls, Origin at 17 of 18 operations) predate later merges; they are leads,
  measured again in audit.md.
- A parallel unit, TRAIN-DEFINITIVE (PR #1086), redesigns the train, its lock and the runner VM. Its files are fenced.
- This cloud session cannot reach Origin: the egress policy answers `CONNECT 403` for `cursor.com` and `api.cursor.com`,
  there is no `origin` CLI on PATH and no Cursor credential in the environment (diary blocker, 02/11).

## Regras
- D-283 (one key selects the forge; no other module branches on the vendor), D-282 (journal on the control plane),
  D-054 (production frozen; nobody merges into `main`), D-065 (events, not a clock), D-077/D-081 (unit flow, roots).
- Brief: no dual path and no fallback; a replaced call is deleted in the same change. Not this unit's to take:
  spending money, production, source-of-truth changes (where the repository lives is the source of truth).
- Never print secrets; never read credential files; never force-push; do not touch I-052b7eed.md, I-12caecdd.md, PR #1066.

## Problema real
The operation still runs on GitHub because the selector names `github`, and nothing in the repository says, measured,
what else must be true before it can name `origin`. Resolved when: (1) every GitHub dependency of the operation is
listed and counted, (2) every one that the repository can remove is removed, (3) the switch to Origin is a single
operator step whose readiness the engine itself checks, and (4) the remaining outside steps are written exactly.

## Lacunas
- Whether `openuniversity-si/open-university` exists on Origin with its history and branches (only someone with an Origin account sees it).
- Whether the runner VM and the cloud environments can hold an Origin credential and reach Origin (environment owners).
- How Origin numbers changes, so a GitHub PR number maps (or not) to an Origin change (live Origin only).
