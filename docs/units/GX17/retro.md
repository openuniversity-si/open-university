# GX-17 retro

## 1. Brief
Clear and well fenced. Gaps: it named `mod/gx17` while the session was bound to `claude/gx17-gate-status-api-r2kajb` (the session rule won; one branch, one PR). Tests are in `scripts/tests/`, not `scripts/lib/`. "Three config keys" did not account for LT1 (below). The brief did not say that `gate_report.py` (GX-39's) is the only caller, so the final status is derived inside `gate_status.py` from the `events` it already receives.

## 2. Audit and plan
Held: GA-P03 non-fatal design; P-34 (status goes through the port); the verdict envelope reaches `final()`. Changed: a fourth key, `forge-events.status_digest_chars`, because the literal census (LT1, D-068) refuses a third `12` in `gate_status.py`.

## 3. Execution (UTC, 27/10)
18:22 audit, plan; 18:23 port + adapters + 3 keys (48be6d0b); 18:24 gate_status (9690bc63); 18:24 docs (a76366ce); 18:31 literal fix (fd6e85af); 18:35 base merge (9b8a994a). Single writer, no sub-agents: two shared files and ~35 min of work did not repay a fan-out.
Failure classes: (a) LT1: new numbers/strings in code and in tests (`12`, `140`, a URL, `1000.0`, `125`, `30`, `32`, `6`, `64`); only 0, 1, -1 are allowed and the baseline cannot be edited by this unit. Class fix: one registry key for the code value, and tests derive every expected value from config, the constants already in the file or a computed digest, never a new literal. (b) Base moved 5 commits between the first push and the gate (rebase refusal by `commit-check`); merged the base in.
Dead end: I ran the base-tip and own-checkout gates concurrently; `generate.test.sh` then failed in both and I suspected interference, but it fails alone as well (see 4).

## 4. Gate
Verdict of record = `scripts/gate-dev --pr 699` from a base-tip checkout (`2e862f22`), head `9b8a994a`: structure check PASS; script tests: `forge-events.test.sh` and `gate-status.test.sh` PASS, only `scripts/tests/generate.test.sh` FAIL, 32 s total. Cause: ERR_MODULE_NOT_FOUND from `apps/web/scripts/intents-doc.ts` inside the gate's slot checkout (no apps/web dependencies there); `generate.test.sh` passes (23 tests OK) when run directly in the base-tip checkout and in this one. It is an environment failure outside this unit's files (not in the known list; recorded, not loosened). Own-checkout run (report-only): same single failure, 115 s. The first runs (before the fix) failed structure check on LT1 (9 refusals) and, on base tooling, script tests failed because head tests ran against base libs (`ForgeEvents.set_status` missing, keys unregistered): the interim D-A3 protocol cannot prove a PR that adds library code tested by script tests; GX-05 (pinned gate) is the owner.
Observable: the own-checkout gate (this unit's code) wrote no `tower/gate` status and printed `status: unavailable (403)` once (`status.log`): the identity lacks `statuses:write`; pending owner action.

## 5. Lessons
- Brief template: say that new numbers/strings in code or tests need registry keys (LT1) and that only 0, 1, -1 are free. Owner: coordinator.
- A shared test helper for "expected value from config" would stop repeated test literals. Owner: engine-config.
- D-A3 protocol: head tests against base libs fail for any lib-adding PR; GX-05. Owner: engine-gate-run.
- Gate slot checkouts without apps/web deps break `generate.test.sh` whenever the diff touches generated files; env unit GX-ENV.

## Addendum: after GX-FIX-registry (#715, merge dbfdf809)
Base merged in at 3041f17f; base-tip `gate-dev --pr 699` (138 s): structure check PASS, `forge-events.test.sh` and `gate-status.test.sh` PASS (the registry signature is gone). Script tests fail only on `gate-db.test.sh`, `invoker-tooling.test.sh` (loopback connect refused in `rest_fake.wait_ready` inside the gate slot checkout) and `generate.test.sh` (`ERR_MODULE_NOT_FOUND`, no apps/web deps in the slot): all three pass when run directly in the base-tip and in this checkout, so they are the slot-checkout environment class, not this change. Lesson: a gate slot checkout that cannot reach loopback or has no node deps fails every PR whose diff covers those tests; owner GX-ENV.
