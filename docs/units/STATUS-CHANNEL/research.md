# STATUS-CHANNEL — research

## Quem já resolveu
- Event sourcing, one append-only journal per stream (Fowler, *Event Sourcing*; EventStoreDB's HTTP API): state is the
  journal, and a reader asks the journal rather than asking the people working. A status line is an event, not a
  message in a chat thread.
- Kubernetes "conditions" (API conventions, `metav1.Condition`): one writer owns each condition and patches it in
  place, so a consumer never sees two competing status lines; the convention also fixes `observedGeneration` (the head
  a condition describes), which is exactly the "per head" the gate's stage table needs.
- GitHub Checks and commit statuses (REST, `checks` and `statuses` endpoints): status beside the change instead of
  inside the conversation; one entry per context, updated rather than appended.
- OpenShift's "single source of truth" operator rule and the GitOps principle that a status is derived, never
  hand-posted: a hand-posted status drifts the moment two writers describe the same head.

## Estado da arte
One append-only journal owns the facts, one identified writer owns each mutable status, and a status is derived from
the journal or patched in place per revision — never appended by every actor as a new message in the change's
conversation. The engine already runs the journal (the control plane's `/v1/events`, D-282) and already patches the
gate's table in place per head (`gate_status.py`); the part that is not at the state of the art is the repository text
that still names the comment as the storage and as the per-step channel.

## Encaixe em nós
- **Copy**: the conditions pattern for the one mutable status the PR carries — a single comment per head and mode,
  found again and edited (`gate_status.py` already does this, marker plus head plus mode).
- **Adapt**: the journal as the only status channel: a step's one line is a `plan.note` of kind `engine` on the PR's
  channel of the journal, written with `scripts/plan note --pr <n> --kind engine --evidence <ref>`. The port already
  routes every kind to the configured log adapter, and the control adapter already appends a channel's envelopes.
- **Does not fit**: commit statuses and checks as the per-step channel — the writing identity gets 403 on status writes
  from a cloud session (recorded in the storage section itself); they remain a gate detail, not the diary.

## Escada de ambição
1. (this unit) Correct the two governing texts to the current truth and refuse their return with a test: the diary is
   the status channel, the comment storage is legacy, and a missing token or an unreachable control plane is a broken
   environment recorded as a blocker.
2. Every remaining text that tells a session to put status in a comment (`docs/padrao/*`) aligned to the same rule, so
   no rule file can be cited as licence for a status comment.
3. A reader that renders a session's diary lines for the owner (a view over the journal), so nobody needs the PR thread
   to follow a delivery at all.
