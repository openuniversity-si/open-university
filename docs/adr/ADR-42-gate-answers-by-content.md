# ADR-42 — The gate answers by content: what did not change is judged by key, what changed runs cheaply

Status: accepted (PADRAO-DEV F3a: an engine decision in force).

Date: 2026-10-30 · Status: accepted (Daniel, 30/10 10:43 BRT, GATE-SPEED; D-092) · Builds on ADR-41 and D-076 · Unit:
[GATE-SPEED](../units/GATE-SPEED/plan.md)

## Context
On A Torre's runner, an e2-micro that sustains 0.25 vCPU, a docs-only gate took 36 min 47 s: the whole script suite
cold (704 s; about 805 CPU-seconds on any machine), full-history and full-tree secret scans, a structure check that
spends its time replaying configuration, and a report three to four times longer than the stages that reruns work on
the base and reads every open PR's comments ([audit](../units/GATE-SPEED/audit.md), roots R1–R6). No amount of
parallelism on two shared vCPUs turns 805 CPU-seconds into 10 s; only not doing the work does.

## Decision
1. **A test's answer is a property of its inputs.** Every script test keeps its content key (D-076, P-56); the whole
   suite is *judged* every run (every test either answered by its key or run), in one process that hashes each file
   once. "The whole suite in 10 s" means warm: every unchanged test is answered by key in milliseconds, the changed
   ones run. A cold full run stays in `gate-noite` and on a fresh machine; it is measured and reported, never claimed
   as the warm number.
2. **Pay once per run, not once per call.** A registry read is a constant read within a process (the shared store is
   replayed once per read of its log, the event catalog once per contracts directory); git objects of an immutable
   commit are read in one batch and remembered by sha.
3. **The verdict first, the chores after.** The report answers the verdict before it routes defects; it reads each
   channel once per run; the work that only matters to the factory (pricing a defect over every open PR) runs only
   when this run found or changed a defect.
4. **Scans judge the change, the night judges the history.** In a PR gate the secret scans cover the PR's own commits
   (`merge-base..head`) and the files it changes; `gate-noite` keeps the full history and full tree scans.
5. **A runner runs the code of the base it serves.** After a refresh changes its own files, the runner re-executes
   itself between jobs.

## Consequences
- Checks keep their meaning: no test is deleted, skipped or quarantined; a key that cannot be computed runs the test
  (fail closed); every threshold and timeout is unchanged.
- The warm path depends on the key being honest: a test that reads a file its covers do not name can be answered from a
  stale result. The covers check and the nightly cold run are the safety net, as in Bazel's model.
- Categories that cannot fit 10 s cold on the e2-micro (the cold script suite, web unit runs, the browser smoke, the
  production build) are measured and reported as misses with their own tier (D-093), never hidden.
