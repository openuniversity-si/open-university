# FLUXO-AMPLO — audit

Read-only, from git history (`origin/mod/roadmap-integration` at `b0a61aa1`, 31/10 about 15:00 BRT). Every number below
is reproducible: the raw/counted series with `scripts/flow-metrics`, the lead-time split with the loop in
section "Method". Where a number is an estimate it says so.

## Entradas
[intake.md](intake.md) (the goal, the baseline, the open problem) and [research.md](research.md) (DORA, flow metrics,
Little's law, Goodhart, atomic commits). They set the question: what limits integrated commits per day, and is the
count honest.

## Findings
1. **Throughput fell with the number of lanes, not with the speed of a lane.** Merged PRs per day and distinct
   branches (one session per PR until 28/10, D-007): 25/10 94 PRs on 94 branches; 27/10 113 on 113; 29/10 9; 30/10 16
   PRs on 8 branches; 31/10 21 PRs on 2 branches. The peak was about 110 short parallel sessions; today it is 2 long
   serial ones.
2. **The train is not the limit up to about 700 commits per day.** It integrated 688 commits on 27/10 (113 PRs) with
   the same gate design. A lane count that needs more than that is where the train would become the constraint
   (estimate: untested above 113 PRs/day).
3. **In a serial lane, authoring dominates the cycle, not the gate.** Per PR (median, 5 commits both periods):
   - 24–28/10 (n = 354): first→last commit 7.9 min, last commit→merge (gate + train wait) 4.2 min (p90 24.4).
   - 29–31/10 (n = 46): first→last 33.5 min, last commit→merge 14.4 min (p90 54.6).
   So 70 % of a lane's cycle is the session writing and 30 % is waiting on gate and train. Removing the wait entirely
   is at most 1.4x for a serial lane (Amdahl).
4. **A serial lane's ceiling is about 216 commits per day.** Let a = authoring minutes per commit (33.5/5 = 6.7) and
   W the wait per PR (14.4). Commits per hour = n / (a·n + W) for n commits per PR: 6.3 for n = 5, 8.1 for n = 21, limit
   1/a = 9 per hour = 216 per day over 24 h. Sub-phase 200 is reachable by one serial lane only at the limit; 300 and
   above needs more lanes, or less authoring time per commit (a below 4.5 min).
5. **The wait per PR amortizes over commits; the PR size rule works against the metric.** W is paid once per PR
   (gate, train, merge). "Keep PRs small" and one gate per PR head raise W per commit. Packing more cohesive commits
   per PR (each one still counted only if the guards hold) is the cheapest serial lever.
6. **The count was honest so far, with one soft spot.** Guards over 2,187 integrated commits (24–31/10): 0 empty,
   0.2 % fixup, 2.2 % split, 25.6 % tangled (more than one code area), 66.7 % plan-linked. Splits are rare; the
   metric's risk is not yet inflation but tangling and missing plan links (a third of commits carry no `Plan:`).
7. **A lane is lost at its first push when the designated branch is stale.** Incident of this unit (RC-001): the remote
   branch existed at `251b64fb` (27/10, inside main), the literal census judged the push against that merge-base and
   refused every engine file as new, and a force-push was denied. The session stopped for several minutes of the
   31/10 afternoon (first refusal about 14:58 BRT) and needed the CEO to name a new branch. Class: environment
   (launcher), blocking every session that is given an existing branch name.
8. **Gate cost per commit is small locally and large on the VM.** Local pre-push: about 5–6 s of checks plus about 20 s
   of deferred script tests per push in this container; on the e2-micro a PR head took 292–661 s before D-135 (0 cache
   hits). The gate does not run per commit, so its cost per commit falls with commits per PR (finding 5).

## Causas raiz
### R1. The metric is bound by the number of parallel lanes, and the current stage allows one
Cadeia de porquês:
1. Por que 90 integrated commits per day instead of 700? Two lanes against about 110 on 27/10 (finding 1).
2. Por que two lanes? The program mode of GATE-SPEED and ou-decouple is one long serial session, and this unit starts
   serial by order (progressive capacity).
3. Por que serial is slow in commits? Per lane the ceiling is 9 commits per hour, set by authoring (finding 3, 4).
Classe: arquitetura/desenho
Nota: the lane model; the serial-first rule that holds it at one lane is RC-002.
Evidência: PR counts by branch per day above; `scripts/flow-metrics`.

### R2. A lane's cycle is mostly authoring plus a per-PR wait that is not amortized
Cadeia de porquês:
1. Por que 6.3 commits per hour in the lane? 33.5 min of writing and 14.4 of waiting per 5 commits.
2. Por que 14.4 min of waiting per PR? Gate on the PR head, then train batch, then merge: three serial steps paid once
   per PR.
3. Por que is it paid per 5 commits only? PRs are kept small and commit plans are 3–8 items (AGENTS.md).
Classe: regra faltando
Nota: nothing prices the per-PR wait against commits per PR.
Evidência: lead-time split above (n = 354 and 46).

### R3. The first push of a unit can fail for reasons outside the code
Cadeia de porquês:
1. Por que the first push failed? The census saw 2,688 commits of engine code as new.
2. Por que? It judges against the merge-base with the branch it pushes to, which was stale.
3. Por que stale? The launcher hands out an existing branch name without resetting it to the base.
Classe: mecanismo faltando
Nota: the launcher or the pre-push base choice.
Evidência: RC-001, push output of this session.

## Distância do estado da arte
Research's ladder: step 1 (a read-only command for the baseline and the guards) is done in this unit
(`scripts/flow-metrics`, D-137). Missing for step 2: guards computed at train admission, and the durability guard
by operations. Missing for step 3: counted verdicts as events and the guards as SLOs. On DORA's side we have throughput
and a rework proxy (fixup) but no change-fail rate and no lead time per plan item as a record; on flow metrics we
measure flow time per PR (above) but not WIP per lane as a series.

## Base defects expected
- A tangled commit in the guard is a ratio, not a refusal; if a phase's number grows with it, the guard must become a
  gate check (decision for the plan).
- Gate and train durations are measured from git (last commit → merge); the stage timings sit on the VM and are not
  read here, so findings 3 and 8 are upper bounds on what the gate itself costs.

## Method
```bash
scripts/flow-metrics
git log origin/mod/roadmap-integration --first-parent --merges --since=2026-10-24 --format='%H %P %ct'   # then per merge: first/last commit of p1..p2
```
