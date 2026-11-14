# Incident: the repository channel #548 is past the 20-page read cap (2026-10-30)

Blameless (D-069 item 9). The question is which missing step let a log outgrow its readers, not who set the cap.

Format: the blocking evaluation of [../blockers.md](../blockers.md) (D-072). Second record.

## 1. What was blocked

Issue #548 is the repository channel of the event log (`forge-events.repo`, `pr` null). It holds more than 2,000
comments; `forge_github.GitHubAdapter._comments` reads at most `forge-events.github_max_pages` (20) pages of 100 and
then raises `more event comments than forge-events.github_max_pages reads` rather than return a truncated log. Every
reader of the whole channel raises:

- the train's post-merge reads and green runs (fixed at the cause by GATE-ON-PUSH, #812: they read the newest window);
- the gate's verdict hooks (`gate_status.verdict_hooks` → `slo.collect`), on every gate: `gate.slow` and the SLO
  evaluation are not published (seen on #813, head e3c7c723);
- `scripts/premises propose` (fixed in #813 item 2: it deduplicates against the window);
- defects, defect_detect, slo, program, plan_triage, quarantine state and render, gate_flake, gate_test_cache and the
  battery history, which still read the channel whole.

## 2. What it cost, in queue terms

The gate still passes (the hooks never change a verdict), but every PR's gate publishes no `gate.slow`/SLO events, the
defect and quarantine views cannot be built, and premise, program and triage commands fail for every session. No PR's
change causes it, and no PR can fix it inside its own scope.

## 3. Which options existed

| Option | Assessment |
|---|---|
| (a) Fix the cause now | One shared windowed read of the repository channel for every reader (the newest window, with a snapshot or a `release.ready` boundary where a reader needs history). It touches about ten modules and their tests: a unit of its own, not a line in GATE-ON-PUSH. |
| (b) Unblock now, cause fix scheduled | Raise `forge-events.github_max_pages` to 200: the channel (about 21 pages) is readable again at about one REST read per page per reader; the quota cost is accepted. Chosen by Daniel (2026-10-30 22:06 BRT). |
| (c) Stop everything and fix | The gate passes and merges are not blocked by this; stopping the queue would pay the full cost to avoid none of it. |

## 4. What was decided

- **Decision:** raise `forge-events.github_max_pages` from 20 to **200** in `config/registry/forge-events.json`
  (Daniel, 2026-10-30 22:06 BRT: "as a stopgap ... raise forge-events.github_max_pages ... from 20 to 200 ... Quota
  cost is accepted for now"), in GATE-ON-PUSH PR #813. Recorded under D-072 (Loosens: forge-events.github_max_pages
  D-072).
- **Approval (D-072):** the line `Loosens: forge-events.github_max_pages D-072` (20 -> 200) is APPROVED by Daniel
  (CEO, 2026-10-30 22:07 BRT, relayed; repeated 22:35 and 22:45 BRT) as a stopgap: the quota cost is accepted for now,
  and the real fix, one shared windowed read of the repository channel, is a separate pending unit.
- **Side effect:** the same key sizes the newest window (`GitHubAdapter.recent`), so windowed reads of #548 read the
  whole channel again (about 21 pages) until the cause is fixed.
- **Owner of the cause fix:** the pending unit of one shared windowed read of the repository channel (Daniel, same
  message), not opened yet.
- **Deadline:** when that unit merges, the cap reverts to 20. The revert is part of that unit's close, not a date.
- **What closes this record:** that unit merged and `forge-events.github_max_pages` back at 20, visible in
  `scripts/config history forge-events.github_max_pages` and the registry's git history.

## 5. Why

The repository channel is append-only and has no reader-side bound: readers were written when it was small, the cap
was a guard against a truncated read, and nothing measured the channel against the cap as it grew. The cap did its job
(no reader acted on a truncated log); the missing step is a window shared by every reader of a growing channel.

## 6. Closed (GATE-TRAIN-SERVICES, #814, D-085)

- **The cause fix:** one shared windowed read, `ForgeEvents.read_recent` over `forge-events.window_pages` (20 pages),
  for every module that read #548 whole: `defects`, `defect_detect`, `slo`, `program`, `plan_triage`, `quarantine`
  (list), `battery`, `gate_flake`, `gate_test_cache` and `train_reuse`; the windows of `config`, `quarantine` and the
  train were already newest-window reads and now take their size from `forge-events.window_pages`, not from the cap.
  A guard test (`scripts/tests/forge_events/test_window.py`, `EveryReaderUsesTheWindow`) fails when a library module
  reads the repository channel whole again.
- **The cost:** the GitHub adapter keeps the window's event comments in a machine-wide cache
  (`forge-events.github_comment_cache`) and asks only for the comments created or edited since the newest it holds
  (`since`, a conditional GET): a warm read is one call, a `304` when nothing changed, instead of 21 pages.
- **The revert:** `forge-events.github_max_pages` is 20 again; it bounds a whole read of a PR channel. History older
  than the window is not read: a reader that needs it keeps a snapshot, as `config.snapshot` does.
