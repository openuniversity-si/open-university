# GATE-API: retro

Unit: the gate is an API that runs the tests and returns the result (engine-gate program, owner A Torre). Launched
28/10 20:25 BRT on Daniel's words of 20:22. PR #800, base 069145b9, decision D-070. This retro was written before
the verdict of record. That verdict runs on the head that carries this file and is posted on the PR.

## 1. Brief

- Clear on the concept, the exit contract, the call a session makes and what to take from #780 and #797. The table
  (0/1/4/64) and "4 is never a result about the code" settled the design before any code.
- Missing: the literal census (LT1) refuses any number other than 0, 1 and -1 in `scripts/`, tests included. So the
  exit code 4 could not be written as `4` anywhere. The brief's "`config/registry/gate.json` keys" pointed there
  without saying why; I found it in the audit (F9).
- Ambiguous: "keyed by head sha + base sha + toolchain" against P-42 (metadata always reruns). I read it as the
  content-addressed part. The PR metadata check runs live on every `--pr` call and is never recorded (F5).
- Not covered: what `--head` without `--pr` means. The gate runs a bare head as `gate-local --dev --sha`, tier 2,
  with no base for its proof hook or its diff checks. The proof found this (section 3).

## 2. Audit and plan

- Premises held: P-42 (metadata never recorded), P-43 (tier 2 and 3 never touch the store), P-46 (the pinned base
  tooling binds; confirmed live, see below).
- The key the API binds is the gate's own `input_digest`, made in the pinned tool root. Proof: for #659's head on
  069145b9 it is `3c078b31…`, the digest of tonight's real v4 `gate.failed` bound on another box. #780 F6 predicted
  that a bind in the invoking checkout would miss.
- Plan change (from the proof): a bare head is now `unbound` and never recorded. The audit's decision 3 said "tier 1
  only"; it now also requires `--pr`.
- The plan held otherwise: seven commits, one per push, in the graph's order.

## 3. Execution (BRT, 28/10)

| Time | Event |
|---|---|
| 20:25 | 2ee05b00 audit skeleton. The first push was refused by `.githooks/pre-push`: `config.StoreError`, because the shared change store holds a `premise.blast` event whose producer `scripts/premises` fails the envelope pattern. Pushed with `OU_CONFIG_STORE=file`. `scripts/cloud/setup.sh` had failed the same way at session start; rerun with the file store. |
| 20:33 | PR #800 draft and STATUS. 2ee05b00's `Claude-Session:` trailer names #780's session (copied from a sibling commit); not rewritten. |
| 20:38 | 21c20378 audit findings and plan. |
| 20:40 | a5abe2b6 #780's items 2 and 5, byte for byte as on its head (4 targeted test modules green). |
| 20:57 | 2ac5c710 the API: 25 tests, 5 mutations each caught, 17 covering script tests green; live `--no-run` calls before the commit. |
| 21:00 | cbb50eda Padrão v5 and the operations page; the test reads both tables. |
| 21:02 | 91581ac9 `gate pin` is env; the two new tests fail on the base classifier (5 failures) and pass with the fix. |
| 21:03-21:11 | Proof 1: 069145b9 PASSED, 465 s. |
| 21:11-21:24 | Proof 2: #659's head FAILED, 734 s. Compared with tonight's `--pr` gate on the same head, the same digest stood for two different measurements. Fixed: bare heads are now `unbound`. |
| 21:20-21:33 | Both bare runs repeated with the fix: FAILED 380 s, PASSED 393 s. |
| 21:33 | 178441ca the proof and the fix. |

Rework: the `unbound` change and a misleading stderr note on tier-2 calls, both found by the proof and fixed in its
commit. Dead ends: none. Waits: about 20 min of gate runs per proof round on this box. It is slower than tonight's
other box: #659's head took 730 s here and 221 s there.

## 4. Gate

- Runs before the verdict of record: 4 full dev runs, all through the API (2 bare heads, then the same 2 again with
  the fix). They are the proof's evidence, not this PR's gate. 069145b9: 21 of 21 stages green both times. #659's
  head: `generated drift`, `unit tests`, `script tests` red (`code`) both times.
- Known defects: none hit by this PR's files.
- The verdict of record runs as the unit's own last step, `scripts/gate-verdict --head <final head> --pr 800`. That
  is `gate-local --dev --pr 800`, the gate `gate-dev` runs, plus the head-tooling advisory run, because this PR changes
  gate files. A second call shows the tier-1 record. Both lines are posted on the PR.

## 5. Lessons

| Problem | Change that would have prevented it | Owner |
|---|---|---|
| One invalid event of another type in the shared change store stops every default-mode `config.get` (setup, pre-push, units) | `premises.producer` must match the envelope pattern (e.g. `premises`); `config.PortStore.events` should refuse only invalid `config.*` events and report the others | engine-premises, engine-config |
| A bare `gate-local --sha` run judges structure check and schema compat with no base and binds nothing, so the same head gets a different verdict without `--pr` | `gate-local --sha` takes the batch base (`gate.batch_base_ref`) as its diff base and binds it, as a batch of one | engine-gate-run |
| LT1 forbids numbers in tests too; found only by reading the census | name LT1 in the engine brief template next to "registry keys" | A Torre (brief template) |
| The first commit's session trailer was copied from a sibling PR | take `Claude-Session:` from the session's own reminder, never from another commit | every session (Padrão) |
| `driver_abort`'s second GET uses `--jq .headRefOid`, which `github_api._jq` does not implement, so a pin abort writes no report (#780 F8) | implement the projection or drop the call; the API already treats a missing report as UNOBSERVABLE | engine-gate-run |
