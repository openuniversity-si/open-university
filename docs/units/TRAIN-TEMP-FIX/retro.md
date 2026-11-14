# TRAIN-TEMP-FIX — retro

Covers the unit from the first launch (17:28Z) to the final gate. Evidence: the commits on `mod/train-temp-fix`, the
diary of PR #1085, [audit.md](audit.md), [status.md](status.md).

## 1. Brief quality
- Leads that did not hold: "about 160 wake records after 14:10" — there are 7 (audit F2). "Four take/release pairs" —
  18 between 14:10Z and 17:32Z (F2, F3). "`scripts/service status` reports seven" — on `fab6e204d` it reported 5
  (F7), and on the base this unit started from the miscount was already fixed by #1083 (F13).
- Stale at launch: the brief named the base tip `fab6e204d` and asked to merge #1084/#1083; when this session started
  (17:33Z) both were merged (by the first launch's session train run, F9). Two of the seven acceptance lines were done
  before the replacement session wrote a line.
- Missing: `tools/language-check.py` does not exist on the base; nothing says how the first launch is stopped when a
  replacement brief is issued.

## 2. Audit and plan
- The first launch's audit was taken as notes and re-measured; F1–F7 held with the corrections above. New this session:
  F9 (who merged), F10 (the VM silent for 41 h, hidden by `runners=unknown`), F11 (a released lock printed as held),
  F12 (two red base suites), F13 (R3 already fixed).
- Premise U1 (a session with the token can run the train) held (F9). U2 (the VM is unreachable) held; the lever was
  chosen around it.
- The plan changed once: R2's table used `B<n>` labels the structure check does not read; renamed `A<n>` (`b71d3d41a`).

## 3. Execution
Timeline (UTC): 17:28 first launch starts; 17:29 / 17:33 its skeleton and audit; 17:32 its train run merges #1084 and
#1083; 17:33 replacement session starts; 17:34 its skeleton push refused (two writers, incident I-774747c4); 17:35
first launch interrupted; 17:35–17:50 measurements and code; 17:52 / 17:53 / 17:56 intake+research, audit, plan; 17:57
commit 4 (the dying run's reason); 17:58 commit 5 (status); 18:01 plan effort block; 18:03 status.md; 18:04 gate.
- Failure 1, class arquitetura/desenho: two writers on one branch (the relaunch did not stop the first session).
  Rework: one dropped local commit. Cost: ~2 min.
- Failure 2, class bug local: the first test edit put a `RoleOverGitLock` test inside `Role` (an anchor that matched
  twice). Caught by the targeted run; moved. Cost: ~1 min.
- Failure 3, class bug local: changing the port's `unlock` broke three test fakes (`test_train.py`, `test_battery.py`,
  `test_planner_role.py`) with an unexpected keyword. Fixed as a class in one commit: every fake accepts `died`; the
  port passes it only when there is one, so a fake that never sees a death is untouched.
- Wait: `test_planner_role.py` ran 600 s and was cut; on the base it raises the same `ForgeCompatibilityError` (F12).

## 4. Gate
See [status.md](status.md) `## Verdict` for the runs and their numbers.

## 5. Lessons
- A relaunch must stop the session it replaces. Change: the launcher (coordinator tooling) interrupts the previous
  session of a unit before starting the replacement, or the brief names it. Owner: the coordinator.
- A brief's leads go stale in minutes. Change: the brief template carries "re-read the live state first" with the
  exact commands (`git log -1 origin/<base>`, `scripts/train queue`, `scripts/service status`). Owner: the coordinator.
- A dead runner must be visible where sessions look. Done here: status relays the control plane's failing checks.
  The control plane's own runner check names one runner `runner [object Object]` (a Worker bug). Owner: the
  control-plane lane.
- The VM's credentials are provisioned by hand outside the repository. Change: the redesign's credential inventory per
  runner. Owner: the train redesign.

## 6. The step that should have descended
- Reading `train/lock` history to tell whether runs die at start: done by both sessions by hand (~10 min each). Now
  descended to the engine: the release record carries `died` and `scripts/service status` warns with it.
- Finding the VM's last heartbeat with `curl $control_url/status`: done by hand (~3 min). Now descended: status relays it.
- Deciding "run the train from a session that holds the token": the same decision CONTROL-ROUTE and the first launch
  already took. It should descend to a rule in `docs/operations/train.md` (who runs the train while the VM is
  unprovisioned). Owner: the engine lane.
- Counting closed PRs out of the status queue: already descended by #1083 before this unit; no work repeated.
