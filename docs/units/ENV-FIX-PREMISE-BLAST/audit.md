# ENV-FIX-PREMISE-BLAST — audit

Train-role session, 2026-10-29. Class `env` (D-027): the shared machine state, not a PR's change, breaks every reader.

## Symptom
On base `069145b9` every `config.get` that reads the shared store (adapter `github`) raises:

```
config: the change store holds an invalid event (premise.blast: $.producer: 'scripts/premises' does not match '^[a-z][a-z0-9_.-]*$')
```

`scripts/cloud/setup.sh`, the pre-push hook and `scripts/train` all call `config.get`, so they all stop.

## Cause
1. `config/registry/premises.json` declares `premises.producer` = `scripts/premises`. The envelope schema
   (`event_contracts`) requires `producer` to match `^[a-z][a-z0-9_.-]*$`; the slash is outside it.
2. `premises.event()` builds the envelope by hand (not through `ForgeEvents.build`), so the bad producer was not refused
   at emit time. One `premise.blast` (event `1e61e07f…`, P-04, 2026-10-28T22:51:02Z) reached the repository channel
   (issue #548).
3. `config.PortStore.events` treats any rejected entry of the channel as fatal, even one that is not `config.changed`
   or `config.snapshot`. The log is append-only (nobody edits or deletes a comment on #548), so one bad envelope
   blocks every reader for ever.

## Fix (three parts, each with its test)
- The producer becomes `premises` (valid); a test asserts every registry `*.producer` value matches the envelope
  pattern, so the class cannot come back from another owner.
- The store reader skips an invalid envelope and quarantines it: one line per event id in the append-only
  `config.store_quarantine_log` (gitignored, under `.tower/`), said once on stderr when first seen. Valid events are
  replayed as before. The test replays the real event from #548.
- The defect is recorded in the known-defect registry (`scripts/defects record`), so it is routed and closed by the
  normal flow.

## Not done
The bad event stays on #548: the log is append-only. It is skipped, not removed.
