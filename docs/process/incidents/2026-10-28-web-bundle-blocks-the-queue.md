# Incident: 173 bytes of web bundle hold PR #742 and every unit behind it (2026-10-28)

Blameless (D-069 item 9). The question is which missing step let a budget stop the queue, not who set the ceiling.

Format: the blocking evaluation of [../blockers.md](../blockers.md) (D-072). This is its first record.

## 1. What was blocked

PR #742 (`mod/tx-program`, base `mod/roadmap-integration`) is the test program: TX10 and every unit that expects the
tests to stop being a recurring blocker wait on it. Its pinned gate ran 20 stages; 19 passed and one failed in 1.6 s:

```
build (production)  FAIL  1.6s
  web JS bundle: 695469 bytes measured, budgets.web_bundle_bytes_max = 695296
  173 bytes over (0.025%)
```

The stage is `scripts/lib/gate-build.py`, which runs `scripts/lib/budgets.py check-bundle` after `pnpm build`. The PR
changes no file under `apps/web/`; the measurement moved, the ceiling did not.

## 2. What it cost, in queue terms

- PR #742 held, and with it every unit whose gate expects the test program.
- 61 PRs are open against `mod/roadmap-integration`. Each one that reaches `build (production)` meets the same 173
  bytes on the same base, because the ceiling is a base value, not a PR value.
- The failure is a measurement, not a regression: nothing anyone wrote is wrong, so no amount of reading the PR finds
  a fix inside it. The default outcome of the block is that the queue waits for someone to notice.

There is no clock in this accounting (D-072, P-32). The cost is the set of PRs and units above.

## 3. Which options existed

| Option | Assessment |
|---|---|
| (a) Fix the cause now, inside #742 | The bundle grew on the base (TX32/TX11 merges), not in #742. A fix inside #742 would be an unrelated web-size change inside the test program's PR, and it would not help the other 60 PRs. |
| (b) Unblock now, cause fix scheduled | Raise the ceiling to the next KiB above the measurement (696320) and record the cause, the owner and the deadline. Every PR on the base passes the stage again; the real fix lands on its own. Chosen. |
| (c) Stop everything and fix | The base is not untrustworthy: the bundle is 0.025% over a rounded default and the app builds. Stopping the queue here would pay the full cost to avoid none of it. |

Raise the ceiling *and* fix the cause was not offered as a fourth option: (b) already carries the cause fix as a
tracked record, which is the only thing that separates it from hiding the problem.

## 4. What was decided

- **Decision:** raise `budgets.web_bundle_bytes_max` from 695296 to **696320** in `config/registry/budgets.json` — the
  next KiB above the 695469 measured on the base. Recorded as D-072 (Loosens: budgets.web_bundle_bytes_max D-072).
- **Owner of the cause fix:** TX13, PR #756 (`mod/tx-bundle`), which brings the web bundle back under the old ceiling
  at the cause rather than under a raised one.
- **Deadline:** when #756 merges, this ceiling reverts to 695296. The revert is part of #756's close, not a date on a
  calendar.
- **What closes this record:** #756 merged and the ceiling back at 695296, or a later decision that says the bundle
  legitimately needs the extra 1024 bytes. Both are visible in `config/registry/budgets.json` history
  (`scripts/config history`).

## 5. Why (five whys)

1. Why did #742 fail? The measured bundle is 173 bytes above a ceiling rounded up from a 2026-10-27 measurement.
2. Why is the ceiling that tight? D-069 item 14 set it to the next KiB above the measurement of that day, and its
   description said a budget only tightens.
3. Why did nothing adapt when the base grew? The bundle grew in base merges TX11/TX32; the ceiling is a base value and
   no step re-derives it when the base moves.
4. Why is there no step for that? The known-defect route (KD1, D-069 item 15) only covers the test stages of
   `defects.stages`. A build or budget failure on the base has no route of its own, so its default is to stop.
5. Why is the default "stop" for a whole class of block? There was no evaluation step that asks what the block is,
   what it costs and which options exist before acting. Every such block was decided ad hoc, or not decided at all.

The root is the missing evaluation step for the class "a gate stage fails on the base and is not a test stage", not the
173 bytes.

## 6. The class fix

- `docs/process/blockers.md` and D-072: every blocking event enters the four-question evaluation before any action,
  with three options none of them forbidden, and an unblock legitimate only when its record names cause, owner and
  deadline.
- This document is the record shape for an occurrence. The asset inventory carries `docs/process/incidents/*.md`
  under D-072 so a record is never deleted (one per blocking evaluation).
- The recurring class this record exposes — a base value that the base itself outgrows — is the input to extending
  KD1 beyond test stages; that is a separate unit, not this PR.

## 7. What stays true

The ceiling was raised by one KiB, and the old number is still the target. If the revert does not happen, this incident
becomes the record that says we chose the exception and forgot it; the record exists so that it cannot be forgotten
silently.
