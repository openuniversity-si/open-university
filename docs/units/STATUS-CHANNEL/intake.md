# STATUS-CHANNEL — intake

## Pedido
Daniel, 02/11/2026 ~10:45 BRT, after deleting STATUS comments from a live PR twice: "Que fia, que ideia é essa de tu
ficar lendo e publicando daqui, bicho? Resolve o problema na raiz, a gente tem que ter esse token aí, cara." The order
that follows it: the engine's diary is the only status channel, and a session never writes status as a PR comment; the
root cause is that the repository itself tells sessions to do exactly that, so briefs cannot override it.

The two measured places:
- `AGENTS.md`, `## Delivery flow`: "Each step posts a one-line PR comment."
- `docs/process/EVENTS.md`, `## Storage in the forge (v0)`: the GitHub adapter's storage described as one issue comment
  per publish on the PR, which is the same status-as-a-comment.

## Intenção
`AGENTS.md` and `docs/process/EVENTS.md` are the governing text a session reads before it acts: a brief cannot outrank
them. While they say status is a PR comment, every session posts one, and the owner deletes it by hand. One channel for
status, and no text anywhere telling a session to put status on the PR thread: the thread keeps the delivery (body,
code, review) and the gate's own stage table, which the gate publishes and edits in place per head.

## Contexto
- The event log already moved: `forge-events.log_adapter` is `control` (D-282, CANALE7), so every event kind not routed
  elsewhere is appended to the control plane's `/v1/events`, not to a comment (`config/registry/forge-events.json`,
  `scripts/lib/forge_control.py`).
- The gate publishes one live stage table per head and mode and edits it in place (`scripts/lib/gate_status.py`), so the
  PR already carries the only status a reviewer needs.
- The offending sentence entered `AGENTS.md` in `77f2eaae9` ("Remove the delivery-tail checkpoint that wrote
  PROGRESSO.md"), where the retired progress file was replaced by a per-step comment; the storage section predates
  CANALE7 and was never rewritten when `log_adapter` changed.
- Daniel deleted the STATUS comments on a live PR twice before stating this order.

## Regras
- D-065: every step is an event, and the PR's event log is the delivery's proof; D-282: the control plane is the events
  journal; `forge-events.control_token_env` names the token variable, never the token.
- D-055: no review step, so the PR body carries `Fit-Review: not reviewed (Daniel 2026-10-25: no review step)`.
- D-077, D-081: every unit runs INTAKE → RESEARCH → AUDIT → PLAN; D-022, D-025: 1–8 commits, each green on its own,
  each with its `Plan: N` trailer.
- D-054: production is frozen; this change touches no production and no worker.
- Padrão v7 `pass-on.md`: a finding that touches other units goes to the planner, not to a PR comment.

## Problema real
The repository's own two texts instruct a session to publish status as a PR comment, so every session does it whatever
the brief says. Resolved when both texts name the diary as the only status channel, `EVENTS.md` describes the adapter
that is actually configured, and a test refuses the sentence's return.

## Lacunas
- `TOWER_EVENTS_TOKEN` in this session's environment is an operator step (Daniel, D-088); without it the diary refuses
  and this unit cannot publish a `plan.note` of its own progress. That is a broken environment, reported, never a reason
  to use a comment.
- Whether the Padrão rule files (`docs/padrao/*/decide-then-report.md` and neighbours, which also say "record it in a PR
  comment") are rewritten in this change is a scope boundary the plan decides.
- The two untracked incident files under `docs/operations/incidents/` belong to another change and are not this unit's.
