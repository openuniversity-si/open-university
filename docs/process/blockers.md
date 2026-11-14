# The blocking evaluation step (Padrão, D-072)

Daniel, 2026-10-28 02:11 (pt-BR, literal): "Tudo que trava a gente é algo que deixa a gente parado. Tudo que deixa a gente
separado, a gente tem que ter um procedimento padrão pra resolver isso. Porque tempo é mais importante que dinheiro."

Something stops the queue. Before anyone acts on it, the block enters the evaluation below. The evaluation is the
procedure; the action is its output, judged case by case. No rule decides in advance which option wins — the case does,
and the answer is written down.

## What enters the evaluation

Every blocking event, whatever its shape: a gate stage red, a failure already sitting on the base (base-red), a flaky
test, an environment failure, a missing permission or credential, a threshold that stops a build the PR did not change.
A blocking event is anything that keeps an open PR or a dependent unit from advancing.

## The four questions, answered and recorded before any action

1. **What exactly is blocked?** The stage, the PR, the branch, the unit; the exact failure line and the measurement —
   e.g. `build (production)`: 695469 bytes measured against a 695296 ceiling.
2. **What does it cost?** In queue terms: which open PRs it holds, which units wait behind them, how many tests it
   masks. Never in clock terms, never as a deadline: the same accounting the known-defect router already does
   (`scripts/lib/defect_router.py`, weights in `defects.weight_*`).
3. **Which of the three options applies?** Named explicitly, from the table below.
4. **What was decided, and why?** The option, the reason, the owner of the cause fix, the deadline for that fix (an
   event, not a date), and what closes the record.

## The three options, none of them forbidden

| Option | When it fits | What it leaves behind |
|---|---|---|
| (a) Fix the cause now | the cause is small, known, and in the lane that owns the files | the fix, its test, the green stage |
| (b) Unblock now, cause fix scheduled | the cause is large, in another lane, or needs its own unit, and the queue pays for it | cause, owner, deadline, a tracked record |
| (c) Stop everything and fix | the cause makes the base or the engine untrustworthy, so every verdict is in doubt | the fix first, then the queue |

(a) and (c) are what "parar tudo" means when the cause is ours; (c) is what was done for the test program itself
(PR #742): the tests were the cause and every unit behind them would meet it again. (b) is what this page was written
for: 173 bytes of a budget stopped a PR that changed no web file. When a block does stop everything, Daniel's rule of
2026-10-27 23:01 applies — one PR carrying its own audit, plan, fix, gate and retro, not a mini program of many PRs.
This page and its first record are that single PR for this block.

## The record is what separates unblocking from pushing the problem under the rug

Option (b) is legitimate exactly when the record it leaves names the cause, an owner and a deadline. An unblock with no
record is the thing we refuse: it moves the queue today and leaves the same block for the next session, with no
address to fix it at. The same choice means opposite things depending on the record alone.

## The mechanism this extends, and its gap

`docs/operations/known-defects.md` (KD1, D-069 item 15) already does this for one class of block: the gate detects a
test that fails on the base, dedups it by (test, signature), prices its queue impact with `scripts/lib/defect_router.py`,
opens the fix unit and lets the PRs through. Its scope today is the test stages of `defects.stages` — `script tests`,
`unit tests`, `integration tests`, `e2e smoke`, `performance tests`. A build failure and a budget failure have no such
route, so that class of block has no default other than stopping. That is why 173 bytes could hold PR #742, and every
unit behind it, for the length of a gate run plus the time to decide.

The evaluation below is the route for everything the known-defect route does not cover yet; where a class of block keeps
recurring, the evaluation's record is the evidence for extending KD1 to it.

## Where the record of an occurrence goes

`docs/process/incidents/<YYYY-MM-DD>-<slug>.md`, in the four-question format of this page. First occurrence:
[2026-10-28-web-bundle-blocks-the-queue.md](incidents/2026-10-28-web-bundle-blocks-the-queue.md).

Decision: [D-072](../domain/DECISIONS.md). Rule of record: this page.
