# ADDR-MAP-SHARED retro

Branch `fix/addr-map-shared-b`, PR #779, base `mod/roadmap-integration` @ `edf15a1d`.

## 1. Brief quality

- The brief named the file, its generator, its readers and the exact refusal, so no reading was needed to start. Good.
- **It was written after the change.** I had already edited the manifest and the test before a brief existed (the change
  was being prepared as a direct fix when Daniel's question arrived). The brief therefore documents a decision already
  taken; that is backwards for a program, and the only reason it is acceptable here is that the decision is one list
  entry whose evidence fits in a page.
- The brief did not say that `apps/web/tsconfig.paths.json` is **generated**. Whoever reads it next should know the real
  cure is CENSO's step 3bis (a merge driver), not this declaration.

## 2. Audit and plan

- Premises held. `scripts/generate addresses` writes the map (`config/registry/generate.json`, target `addresses`), and
  three readers read it: `apps/web/tsconfig.json` extends it, `apps/web/vitest.config.ts` reads it, and
  `apps/web/scripts/lib/ou-addresses.mjs` resolves every `@ou/<id>` through it.
- The measurement that mattered: `lanes()` on this PR's own files answers one lane (`engine-units`), so this PR is
  decidable either way. The change is for the NEXT unit that gains a contract, and that is the honest description of it.
- Plan unchanged. Four items, four commits.

## 3. Execution (timeline, commit times)

| Time | Commit | Note |
|---|---|---|
| 17:56 | 38fa6011 | audit |
| 17:58 | d66ebe2f | plan |
| 18:01 | 29c499be | manifest + test, with the mutation recorded in the message |

Failure and rework:
- **The first push was refused** with `FAIL push: 3 commits of the branch would be pushed at once`. The three commits were
  made locally and pushed together. Rebuilt the branch as `fix/addr-map-shared-b` and pushed one commit per push, as the
  local check demands. Cost: one push cycle, about two minutes.
- The first gate run answered `FAIL plan: item(s) 4 not ticked by a commit that changes a file` — the retro item, which
  by construction can only be committed after the gate that proves the rest. That is the expected shape of this gate, not
  a defect.

## 4. Gate

`scripts/gate-dev --pr 779` on `2b15e9d2`, 131.624 s of a 180 s ceiling. Every stage passed except `pr metadata`
(4.689 s), and only for the unticked retro item: `structure check` 9.021 s, `install (frozen lockfile)` 1.772 s,
`script tests` 27.512 s, `unit tests` 35.024 s with 1790 tests in 280 files, integration 49 tests in 5 files.

## 5. Lessons (change, owner)

1. A path that is the OUTPUT of a generator and the INPUT of several others belongs in `shared` from the day it is
   created, not when the first PR is refused. Owner: engine-lane, when `units` validation learns to ask whether a path is a
   generator target (`config/registry/generate.json`).
2. The pre-push check refuses several commits in one push, and `scripts/replay-branch` is the remedy; building the branch
   with `cherry-pick` and one push per commit is faster than replaying when the commits are already clean. Owner: the
   brief standard (it tells sessions to push often, not what to do when they already batched).
3. A brief written after its change is a record, not a plan. The audit still earns its place by naming the six readers
   and by saying what the change does NOT fix. Owner: A Torre (the brief comes first, even for a one-line fix).

## 6. The step that should have descended

- **"Which open PRs does a lane-rule change unblock?"** — same 15-line script LANE-OWN's retro named yesterday, still hand
  run. It answered 17 of 21 yesterday and would answer the same question today for this declaration. It should be
  `scripts/gate-why-unblocked` before the next such change.
