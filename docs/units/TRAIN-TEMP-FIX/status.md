# TRAIN-TEMP-FIX — status

## Environment
- This session (cloud, behind the GitHub proxy) holds `GH_TOKEN` and `$TOWER_EVENTS_TOKEN` (presence checked, values
  never printed); `scripts/train queue` and `scripts/plan note` reach the control plane.
- **Limitation (not reachable from a session): the runner VM** `train@the-tower-runner.us-central1-a.c.savvy-bonito-286513.internal`.
  No gcloud login, ssh or keys were attempted (brief). Its `runner.env` and journal cannot be read here. Measured from
  outside: the control plane's `GET /status` gives its last heartbeat as 2026-11-01T00:14:56.751Z (~41 h before
  17:51Z), and `train/lock` shows no take by it after 17:31:03Z (checked 17:51Z and 18:02Z). Until its owner
  provisions the runner token, the train runs only when a session runs it.
- Two writers: the first launch (session `01B2LxDVDe3V…`) was still pushing to `mod/train-temp-fix` at 17:34Z; this
  session interrupted it at 17:35Z and told it to stop, then continued from its head `3ab21ea8e`. The push of
  `662d370c` refused at 17:34Z is incident I-774747c4.

## Lever
- Chosen: **A3, make the train's death impossible to miss** ([plan.md](plan.md)): a run that raises releases
  `train/lock` with `died: <type>: <first line>` (over git), `scripts/train run` ends with `train: died: …`, and
  `scripts/service status` warns with that reason and relays the control plane's failing checks (the silent VM runner).
- Why: it is the only lever a session can implement and prove today, and it covers every future cause of death, not
  only the missing token. "Make the VM read the journal again" (A2) was weighed and not stacked: it needs VM access
  this unit does not have, and its git-read variant would reverse D-290.
- To merge today: the train is run from this session (`scripts/train run --pr 1085`), the same path that merged #1084
  and #1083 at 17:32Z.
- Rollback (one key): `git revert -m 1 <merge sha of #1085>`. The `died` field is additive; older readers ignore it.
- Follow-up (not this unit): the VM's owner provisions the runner token in `runner.env`
  (`docs/operations/services.md:38`); the class fix (a credential inventory per runner) belongs to the train redesign.

## Status count, before and after
- Before (`fab6e204d` status, run at 17:36:54Z in a throwaway worktree): `queue: 5 woken, not merged` — #907, #910,
  #956, #966 (all closed, never merged) and #1066. The first launch measured 7 at 17:40Z on the same code, with
  #1084 and #1083 still unmerged.
- After (`e8b74c581`, 17:35:27Z): `queue: 3 open PR(s) in the control-plane queue` — #1066, #1082, #1085, all open;
  no closed PR. The fix is `5b23c44fe` (#1083), not this unit (audit F13).

## Merges
- #1084 → `850f8e3c0`, #1083 → `e8b74c581` (batch `b-9ef10b2cc24c`, 17:32:52Z / 17:32:54Z), run by the first launch
  from its session (audit F9). Base past `fab6e204d`: yes.
- #1082: draft (`mod/status-channel`, head `7e14dc416`) — not merged (the brief: only if out of draft and declared
  ready by its author).
- #1066: not merged (Daniel's order: it waits for a conversation about the method).

## Verdict
- Gate 1 on `b71d3d41a`: `GATE: PASSED (bypass=D-151)`, evidence `gate.passed cb9d1df9faa9` (+8 engine.step.measured);
  the stages do not execute under D-151, so the hand-run suites are the battery's proof.
- Hand-run suites on this head (unittest): `test_train_role.py` 45 run, 1 fail (base defect F12, RestBudget);
  `test_service_status.py` 22 OK; `test_service_runner.py` 31 OK; `test_train.py` 8 OK; `test_battery.py` OK;
  `forge_events/test_forge_contract.py` 73 OK; `test_loopback.py` 9 OK; `test_forge_flow_compatibility.py` 4 OK;
  `test_forge_requirements.py` 3 OK; `test_planner_role.py` raises `ForgeCompatibilityError` on base and head alike (F12).
- The final gate of the head that carries this file is in the PR body.
