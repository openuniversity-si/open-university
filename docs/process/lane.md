# The lane (FLUXO-AMPLO F1.1, VAZÃO)

One serial session is a lane. Its cycle is authoring plus the delivery of each PR, and the delivery runs in the
background while the lane authors the next one, so the lane never idles on the gate. It takes its next unit from the
[VAZÃO queue](../programs/vazao/fila.md), never from a message. Numbers: `scripts/flow-metrics --prs N`.

## The delivery contract (VAZÃO F68)
`scripts/lane brief Fxx` prints the [rules digest](lane-digest.md) of this section (F78, below) with the unit's queue row and its worktree, the line of each D-NNN the row
cites and, for each unit its "Depois de" names, the line naming it and its merge commit (F77); a lane delivers from that
brief alone, without opening `fila.md`, `RETOMAR.md` or `DECISIONS.md`. Base `mod/roadmap-integration`, never `main`. Never merge PR #3, never touch #41.

0. Every shell command starts with `cd <worktree> && `, nothing more (F81): the scripts source `scripts/cloud/env.sh`
   themselves, find `origin` in `origin-client.cli_dirs` (`~/.local/bin`) when it is off PATH, the config store is
   `file` by default (D-300), and `origin` exchanges `CURSOR_API_KEY` itself. Only when `origin` answers "Not logged in",
   export `CURSOR_AUTH_TOKEN="$(origin auth token 2>/dev/null)"`. Never print a token or credential; never read
   credential files.
1. **Worktree and brief, one call:** `cd ~/the-tower && scripts/lane worktree <Fxx> --session <session>` fetches the
   base, adds `<worktree>` on branch `units/<fxx>` from `origin/mod/roadmap-integration`, links `~/the-tower/.toolchain`
   into it (without that link the delivery's gate fails its preflight with class `env`), prints the unit's brief read
   from the new worktree and the one line every later command starts with (F81). Run again on an existing worktree, it
   merges the base in (never a rebase) and restores a missing link. A name that is not a queue unit (`census`) gets a
   worktree with no brief.
2. **Read** only the unit's row and the files it names, by line range. AGENTS.md rules apply.
3. **Commit plan first** (small self-contained commits, as many as the content needs, a checklist in the PR body; no maximum, D-307). Each commit carries its change and
   its tests, is green after it, and ends with the trailers `Plan: N`, `Co-Authored-By: <model> <noreply@anthropic.com>`
   and `Claude-Session: <session>`. Push every commit, one per push; merge commits only, never a rebase or force-push.
4. **PR body** (`scripts/pr-body` builds it from the commits and takes the `Claude-Session:` trailer from
   `export CLAUDE_SESSION_URL=<session>`, else `--session`; `scripts/commit-check --pr-body <file>` (the plan) and `measurement_checks.py body --pr-body <file>` (the effort, D-322) show no
   effort or plan warning): the commit plan; a `## Cheapest useful effort` block of four non-empty lines, `Action:` (the
   most expensive action), `Cost:`, `Requirement:` and `Cheaper rejected:` ([effort.md](../padrao/v4/effort.md)). The
   `Requirement:` names who needs the result with a word of `effort.owners` (`scripts/config get effort.owners`: Daniel,
   A Torre, coordinator, author, operator, …) or a unit lane such as engine-lane; "manager", "the lanes" or "the gate"
   are refused. Then `Premises: P-NN…|none` (`scripts/premises find "<statement>"`), the D-NNN when a gate file changes,
   `Fit-Review: not reviewed (Daniel 2026-10-25: no review step)` and the footer.
5. **Open:** `origin pr create --draft` prints no number you can reuse; skip it: push the branch first (`git push origin units/<fxx>`; deliver reads `origin/<branch>` and says "no commit over base" otherwise), then `scripts/deliver --open --branch units/<fxx>` opens the PR from the branch commits when it has none and delivers it, finding the open PR of the branch itself (no `<N>`). With `--draft`, `origin pr ready <N>` needs the N from `origin pr list`.
6. **Test:** `scripts/test-suite --changed` before delivering.
7. **Deliver:** `scripts/deliver --branch units/<fxx>` (or `--open --branch ...`; `--pr <N>` only when known) in the background (`> ../<fxx>.log 2>&1`), by the shell tool's `run_in_background`, never a trailing `&` (the shell kills it at the end of the call: empty log). Detached (F87):
   the lane ends once the preflight has passed (the log shows the gate started: base right, head fetched), without waiting
   for the merge; the merge, or the ejection, reaches the coordinator through `scripts/lane collect`, which says for a PR
   not merged whether its delivery still runs or was ejected. A preflight or gate red the lane sees: read the class, fix on
   the same branch, deliver again. Base red (the test also fails on the base head): log a friction and report it,
   don't debug it.
8. **After merge:** `deliver` writes the diary note itself when the PR title names the unit (`Fnn:` or `(Fnn)`, F60).
   Only if it printed a note warning, write one line by hand, once: `scripts/plan note --program vazao --from <Fxx> --affects <units> --pr <N> --kind
   engine --evidence <merge-sha> '<delivered; left open; next>'`, never in a loop.
9. **Frictions:** log every lost minute with `scripts/friction <cause> <seconds> <what>` (F85), never by hand: it appends
   one JSON line to `~/.cache/the-tower/frictions.jsonl` (`{"ts","lane","cause","what","seconds"}`) with the clock ts
   and the lane of the worktree; the cause is one of `env`, `base-red`, `conflict`, `hang`, `tooling`, `rule`.
   `scripts/friction --summary [--hours N]` sums the seconds by cause per hour.
10. **Report** to the coordinator, short: PR, merge sha, what changed, measured effect, frictions, follow-ups. No PR
    comments for status.
11. **Never edit `docs/programs/vazao/fila.md` to remove your row.** `deliver` records the closed row (F60), and the
    manager closes rows in one batch with `scripts/deliver --close-queue`. Removing rows in parallel caused most of the
    03/11 conflicts.
12. **Registry:** edit the source files under `config/registry/<area>/`, never the generated aggregate
    `config/registry/<area>.json`.
13. **Token budget** (03/11 ledger: about 15k weighted tokens per tool call). The brief is all a lane reads for
    orientation. Don't read fila.md, AGENTS.md, RETOMAR.md or DECISIONS.md whole; a D-NNN is
    `rg -n 'D-NNN' docs/domain/DECISIONS.md | head -3`. Never `cat` a whole file: `sed -n 'a,bp'` or `rg -n`. Batch
    independent reads into one call. Run `test-suite --changed` once before delivering, not after every edit; run single
    tests directly while iterating. Pipe long outputs through `tail -20`.
14. **One unit per lane.** Report and end when the unit's delivery has a result; the manager starts a fresh lane for the
    next unit. This replaces the chaining below for lanes the manager starts.
15. **Time limit** (F84, 03/11: 7 of 35 lanes over 900 s held 37 % of the lane-seconds): at 60 tool calls or 15 min of
    work without a merge, stop, push what is green and report what blocks you; the manager splits the rest.

## Rules digest (VAZÃO F78)
`scripts/generate lane-digest` copies the body of this section to [lane-digest.md](lane-digest.md), which
`scripts/lane brief` carries in place of the contract above (at most 1.5 KB; `scripts/generate --check` fails when the
copy is stale). Change it together with the contract.

```digest
0. Each command: `cd /root/wt/<fxx> && <command>`, no exports; print no credential.
1. `scripts/lane worktree <Fxx> --session <session>` in ~/the-tower (.toolchain; base mod/roadmap-integration not main; not PR #3, #41).
2. Read only the row's files, by range (`rg -n`/`sed -n`); ~15k tokens a call: batch, `| tail -20`.
3. Each commit green, pushed; no rebase/force. Trailers `Plan: N`, `Co-Authored-By: <model> <noreply@anthropic.com>`, `Claude-Session: <session>`.
4. `export CLAUDE_SESSION_URL=<session>`; `scripts/pr-body --title --action --cost --requirement --cheaper` (all required, else refused); `scripts/commit-check --pr-body <file>`: checklist; `## Cheapest useful effort` (Action:, Cost:, Requirement: effort.owners/engine-lane, Cheaper rejected:); `Premises: P-NN|none`; D-NNN on gate change; `Fit-Review:` from pr-body.
5. Title `<Fxx>: ...`; no `pr create`: `deliver --open` opens it.
6. `scripts/test-suite --changed` once pre-deliver; iterate `scripts/run test <name>`.
7. `scripts/deliver --open --branch units/<fxx> > ../<fxx>.log 2>&1` via `run_in_background` (never `&`), await exit. Red: fix by class, rerun; base red: friction+report.
8. Never edit fila.md.
9. Edit config/registry/<area>/, not the aggregate.
10. Friction: `scripts/friction <env|base-red|conflict|hang|tooling|rule> <s> <what>` (frictions.jsonl). Report PR, merge sha, effect, friction. One unit per lane.
11. 60 calls/15 min unmerged: stop, push green, report.
```

## Starting a new script
`scripts/scaffold script NAME --unit UNIT --protects D-NNN --retire "never: why"` writes the wrapper, library, test, test wrapper,
covers manifest and unit paths in one go (D-146); the author writes the logic. A new script without it was refused five
times before it landed (literal census, unit, asset entry, covers, CODEOWNERS; the last two left with D-292 and D-295).
A new registry key: `scripts/scaffold config-key OWNER KEY --reader FILE --type T --default JSON --unit U --description D`
writes `config/registry/OWNER/OWNER.KEY.json` with its `x-readers` and the owner's aggregate, checked against the meta-schema
(an object key is user-facing text: `x-text`, its locales, owner `l10n.text_owner`) (VAZÃO F74).

## One delivery by one command
`scripts/deliver --branch B` delivers the pushed head of B from its own worktree (`.gate/deliver/pr-N`): it brings the base
in, runs `scripts/gate-dev --pr N` on the exact head, judges again when the base moves during the gate, merges with
`origin pr merge N --expect-head N=<head>` (a merge commit) and prints the PR/s line. With `--open` it first opens the PR
when the branch has none, its body built from the commits (subject, prose, `Plan:` trailers), and opens nothing when
`structure-check`, `commit-check` or `measurement_checks.py body` fails that body (lane 4, D-236). `lane-ship` and `lane-next` did this until VAZÃO F9.

## The loop, per PR
1. **Plan first**: the items in the PR body, as many as the content needs (D-307), each one a cohesive commit that carries its own `Plan: N`. A split of one
   change into two commits on the same files and the same item counts once (D-137).
2. **Author a commit, push it** (`git push`: the push guard sends one commit per push). A commit that fails the local
   checks stays local and the next commit retries it. Open the PR after the first push (`origin pr create`, or
   `scripts/deliver --open --branch B`).
3. **When the last item is pushed**: start `scripts/deliver --pr N --branch B` in the background. A red gate prints the
   failing stage, its class and the log; fix it on the same branch and deliver again. The status of the flow (merges,
   pace, the base's last gate, the next decision number) is one read: `scripts/flow-check` (D-230).
4. **Do not wait.** Branch the next PR and go on authoring; the delivery's exit wakes the session.
5. **Stacked branches**: a branch started from the previous PR's head carries that PR's commits until it merges; bring
   the base in (`git merge origin/mod/roadmap-integration`, never a rebase) once it has.

## Chaining (VAZÃO F63, 03/11)
Replaced by item 14 (one unit per lane) for lanes the manager starts.
A lane chains its units. Once `scripts/deliver` runs in the background, the lane takes its next free unit from the
queue in a new worktree, then reads the earlier delivery's result before it closes that unit. A red delivery is the
lane's next piece of work, ahead of the new unit. A lane holds at most two units at once, one of them in delivery. The
delivery itself is the [Delivery flow in AGENTS.md](../../AGENTS.md#delivery-flow-canonical-for-every-coding-agent-and-human).

The merge train and the runner VM are stopped until the VM is resized (AGENTS.md); the session that opens a PR merges it.

## The status in one entry (D-230)
`scripts/flow-check` is the one entry for the status: the flow metrics (`--cycles`), the lanes' pace, the train, the base's last real gate, the program's units and the next decision number. It replaces the five commands a session ran by hand: `scripts/flow-metrics --cycles`, `scripts/lane-status`, `scripts/service health`, `scripts/gate-shadow latest` and `scripts/coordinator status`. `scripts/flow-check --unit ID` prints one unit's stage, and `scripts/flow-check --idle` the lanes with no merged pull request in the last hour (a lane with an open pull request is in review ready) and the plan's next launches. A test (`scripts/tests/test_flow_check.py`) refuses a loop step that names one of them on its own.

## Selection holes
The PR gate is scoped: it runs the tests whose covers meet the diff, and a test whose key did not move is answered from the
shared results. A test that reads more than its covers say is therefore blind to the change that breaks it (D-153: the
base was broken for about 40 minutes by a reader `config.test.sh` scans but did not cover). Before `deliver`, run
`scripts/test-suite --changed` by default (VAZÃO F50): it judges only the tests the PR gate will select for your diff
(`base...HEAD` against `gate.changed_base_ref`, plus what is not committed yet), through the gate's own functions
(`gate_policy.select_dev_plan`, `gate_script_tests.select_plan`), so the red the gate would find shows before the push and
the gate answers those tests by key (F19). A diff that selects no test (an uncovered docs path) runs nothing and waits on no
lock. Only on a change to shared tooling (deliver, the gate, structure, config, the test runner) run the whole suite once
(`scripts/test-suite`, about 75 s here); when a test fails that the scoped gate skipped, fix its covers in the same PR. Run
one test with `scripts/run test <name>`, never `bash scripts/tests/<name>.test.sh` directly.

## What the lane measures
`scripts/flow-metrics --cycles --durability K` after each merge: counted commits per day, wait per PR, authoring per
commit, lanes, and the guard ratios. A phase passes only if the main metric reaches its target and no guard worsens.

## Decision numbers in parallel lanes (D-181, D-183, D-190)
Each lane writes its rows in `docs/domain/DECISIONS.md` at the next free number it sees. When the base has taken that number
meanwhile, the gate's structure check refuses the PR and `scripts/decision-next` prints the next free one (D-183; `lane-ship` refused the lap until F9). `scripts/decision-next --claim` takes it on the remote, so no other lane can take that number while the PR is open (D-190; a claim is never deleted, so a number is never reused): renumber the row (and every reference to it in code, docs,
covers and the PR body) to the next free id, then run `scripts/deliver` again. The same row on both sides is kept once. After a renumber, run the decision's own proof by hand: under the regime of exception the gate is green before the tests run (D-185).

## Narrowing a test's covers (D-178)
`scripts/covers-cost --since DATE` ranks the script tests by their share of the cost per PR and, with `--paths TEST`, which covers
patterns the merged PRs met. To drop a pattern from a test, `scripts/covers-prove TEST --without GLOB` runs the test without those
files: PASS means it does not read them, FAIL names the read. Then remeasure with `covers-cost` and record the numbers. Measured on the quarantine and production-guard tests (D-214): every pattern FAILs, so the glob `contracts/events/*.json` stays (the event library lists that folder); production-guard gained the three modules its test imports.

## Lanes and the ramp (D-176)
| Lane | Units it owns | Work |
|---|---|---|
| 1 | `engine-flow`, `engine-records`, `engine-lane-tools`, `engine-config` | covers split by what a test reads, flow tools (engine-flow split into measurement, records and lane tools); units and generate moved to lanes 13 and 12 (D-209) |
| 2 | `engine-train`, `engine-train-admission`, `engine-role` | the gate front (e2-micro under 10 s, D-188); engine-train split into the train, its admission and the locked roles |
| 3 | `engine-gate-report`, `engine-gate-run`, `engine-gate-plan`, `engine-gate-speed`, `engine-gate-cache` | split of the oversize gate units; gate-tests, gate-ops and gate-verdict moved to lanes 9 to 11 (D-209) |
| 4 | `engine-env`, `engine-events`, `engine-structure`, `engine-supply-chain`, `engine-idea-to-prod` | split of the oversize units; forge-github moved to lane 14 (D-209) |
| 5 | `engine-push-guard`, `engine-test-support` | merge-regenerate moved to lane 16 (D-209);  the cost of the push guard and the regenerate step; test support (D-184) |

A lane exclusively owns its units, so lanes do not conflict on files. A new lane is added, on units no lane owns, while the train
queue stays at two PRs or fewer, the base shadow is green and the `tangled` and `rework` guards hold (`scripts/lane-status`,
`scripts/flow-metrics --lanes`). A measured limit is recorded as a D-xxx and stops the ramp there.

## The regime line of lane-status (D-192)
`scripts/lane-status` prints `regime:` with the bypass and the runner. A resumed runner (`service.paused=False`) is a recorded change (D-191), not a drift. A drift is named when the bypass is off, which moves the gate.

## Taking a unit (D-193)
A lane takes its next unit from the program's graph: `scripts/coordinator next fluxo-amplo` lists the launches (the unit ids in
`docs/programs/fluxo-amplo/plan.md`), and `scripts/coordinator status fluxo-amplo` shows each unit's stage. Nobody hands out items by message.

## Launching a lane (D-200)
`scripts/coordinator run PROGRAM --briefs` renders the brief of each launch; `--apply` starts the sessions through the launcher, which
runs `coordinator.launcher_argv` (`claude --remote`, a flag this CLI does not have). `--apply` probes every flag of that argv against the command's `--help` first and refuses at once, naming the flag, so no unit is assigned to an idle lane (L1, D-206 (d)). Until the launcher is fixed, a
lane is started with the brief pointer: fetch the plan's branch, run `--briefs`, read the unit's block. Each start is recorded as a
`work.assigned` event (`emit`), and the launch-rate limit counts it (5 in 300 s).

## The commit rate (D-202)
`scripts/commit-rate` gives the counted commits of the last 60 minutes per second, minute, hour and day. It is read by the scheduled report every hour, so a session does not compute the rate by hand.

After the start of a unit is recorded, `--briefs` does not print its brief yet (D-204, fixed by lane 8). Until then the brief head is sent by message, and the padrão is in `docs/padrao/v8`.

## Owners of the breakages of eight lanes (D-201, D-204)
| Breakage | Owner | Fix |
|---|---|---|
| `forge_git_ref` commit-tree in the base (train-role red) | lane 4 (engine-events) | D-201 (1) |
| brief of a unit not printed after its start | lane 8 (engine-coordinator) | D-204 (1) |
| fold counts only launched units | lane 8 (engine-coordinator) | D-204 (2) |
| launcher argv (`claude --remote`) | lane 8 | D-200 |
| train-role reads DECISIONS.md outside its covers | lane 2 (engine-role) | D-201 (5) |

## Where a generated text or a report lives (D-205)
A unit's own script renders its templates or prints its report (lane 8: templates in engine-intake; lane 7: `scripts/checks` in engine-budgets). A change to another unit goes through that unit's owner, never into its file.

## Root cause before fix (D-206)
An incident is fixed at the highest level it allows, in this order: the design that should have been there; then the class of problems it belongs to; then the case. A design fix is taken when the design is known, a class fix when the class is known, a case fix only when neither is. The incident's row in DECISIONS.md names the level, and the plan carries the fix as a unit with done criteria at that level.

## The clock of a claim (D-207)
`scripts/decision-next --claim` prints the number and the time of the claim, in BRT, from the machine's clock; the row takes that time, never a typed one.

## The repeat routine (D-208)
Every 10 minutes a session runs `scripts/repeats`: the open repeated actions, most repeated first. For the top one, it decides whether the action gets a script, a plan unit or a record of why not, and writes that in docs/process/repeats.md. The routine is the script; the session only decides the open rows.

## The PR body (D-208)
`scripts/pr-body --title T --action A --cost C --requirement R --cheaper X --session URL --out FILE` builds the body from the branch's commits, so the plan, the effort block and the footer are not typed again; then `origin pr create -t T -F FILE -H B -B mod/roadmap-integration`.

## Sixteen lanes (D-209)
| Lane | Units |
|---|---|
| 9 | `engine-gate-tests` (moved from lane 3); covers proved, `covers-cost` drops `scripts/covers-cost` (D-212) |
| 10 | `engine-gate-ops` (moved from lane 3) |
| 11 | `engine-gate-verdict` (moved from lane 3) |
| 12 | `engine-generate` (moved from lane 1) |
| 13 | `engine-units` (moved from lane 1) |
| 14 | `engine-forge-github` (moved from lane 4) |
| 15 | `engine-quarantine`, `engine-production` (moved from lane 8); the status-command entry `scripts/flow-check` (D-230) |
| 16 | `engine-merge-regenerate` (moved from lane 5) |

## Starting a branch (D-211)
`scripts/branch-start NAME` starts a branch at the base: it fetches, refuses a dirty tree and a name already on the remote, and creates NAME. Start every branch with it, not with a hand-made fetch and checkout.

## The decision table from the records (D1, D-217)
`scripts/decision-table` renders one table row per record in docs/domain/decisions, in number order. A rendered row passes the structure check's row rules: six cells with no pipe, a proof it reads as a linked test, and the record's relative links moved to the table's folder.

A new decision is a record (`scripts/decision-record`) and its row, in the same commit: `scripts/decision-record` runs `scripts/decision-table --write` itself after it writes the record (VAZÃO F75), and exits non-zero when the row could not be written. `commit-check` reads only the table when a gate change cites a decision, so a record without its row is a decision no PR can cite (D-292 was missed this way until 03/11). `--write` adds the missing rows and never rewrites one; it refuses when the table has another row under a record's number.

`scripts/decision-table --handwritten` (also part of `--check`) refuses a row of DECISIONS.md typed by hand: an id after the first record with no record and not in `docs/domain/decisions/handwritten.txt`. `scripts/decision-table --check` lists each record with no matching row in DECISIONS.md, an id written twice and an id the base had and the table lost; it exits 0 when the table is in step (62 of 62 on 03/11). The pre-push `decision_table` local check runs it (PR #140): a push that changes a decision record or the table is refused while a record has no matching row, an id is written twice or by hand, or an id the base had is lost (fix: `scripts/decision-table --write`); a push that touches neither is not judged.

## The unit of work is the counted commit (D-218)
The program was drawn with the pull request as its unit; the main metric is the counted commit (D-137). The goal and the commit plan follow the commit, in the steps of D-218 (K1 and K5). The literal rule is kept (D-220 supersedes D-218 on that point).
