# CO1 retro

Unit: event-driven program coordinator (D-069). PR #576. Two sessions: the first reached audit and plan (05:06) and hit the account's session limit at about 02:08 box time; the continuation executed commits 3 to 7.

## 1. Brief quality
- Clear: the five build items, ownership boundaries and the process rules.
- Missing: `v3/queue.json`, named as the migration source, is not in the repository, so the seed came from the unit list in the brief. The dependency edges of the seed are therefore my reading, not data.
- Ambiguous: "quota headroom" has no event source; the coordinator takes it as an observation the launcher reports (unknown does not block). "Launch rate" and "max sessions" had no defaults; I registered them.
- Conflict: the harness named branch `...-u5bwuo` while the continuation instruction named PR #576's branch `...-iwtacz`. I followed the explicit instruction.
- LR1 was not merged at launch; the lessons port was first designed against an unmerged API, then replaced by the real one once #575 merged.

## 2. Audit and plan
- Held: no new event type needed (a launch is `work.assigned`); state is derivable from the log plus the graph; the null lessons fallback was a safe reversible choice.
- Changed: the plan's "lessons port with null fallback" became a direct LR1 adapter (commit 5a2ef5de) once LR1 merged; the null fallback was removed.
- Missed in the plan: `scripts/` assets entries (`docs/structure/assets.json`) and unit-path ownership rules (D-067 (6)), both enforced by structure-check.

## 3. Execution (commit times, box time)
05:06 audit and plan (session 1) · 05:52 program contract · 05:58 coordinator core · 06:07 launch adapter · 06:10 program gate · 06:12 LR1 wiring · 06:13 docs and manifest · 49e0767f structure fixes.
- Failure A, registry: an `object`-typed key requires `x-text`; fixed by splitting into six string keys (class: api-misuse of the registry meta-schema).
- Failure B, tests: `setting(name, root)` passed a temp root to `config.get`, whose registry is the checkout's; fixed once in `program.setting` (class: api-misuse).
- Failure C, vendor tests: adding an adapter changed two pinned lists in `test_vendor_check.py` (class: test-fragility, owner engine-vendors).
- Failure D, structure-check (only caught by the gate): (1) three scripts had no `assets.json` entry, (2) the two launcher files matched both my manifest and `engine-vendors`' `adapters/**`, (3) a gate-file change needs a D-NNN in the PR body. Class: check-gap, I ran the structure stage only at the gate. LR-49827a20 already says to run it after each commit; I did not.
- Dead end: none lost to quota. A throwaway no-op monitor wasted one turn.

## 4. Gate
Run 1 (head 7ca483cd, 898.8s): structure check failed with the six errors above; script tests failed on `generate.test.sh` (`intents-doc.ts`) and `premises.test.sh` (`measurement:S1`), both registered base defects. Run 2 (head 49e0767f, 249.6s): PASSED; the only reds were the same two registered base defects (`generate.test.sh`, `premises.test.sh`), structure check green. Run 3 on the retro-only head follows (docs commit, cached). Three runs in total. Ceiling warning (180s) is the whole-gate time on a cold cache, a base property.

## 5. Lessons
| Problem | Change | Owner |
|---|---|---|
| structure-check failures found only at the gate | `scripts/pr-ready` or the push hook runs `structure-check` on the local diff before each push | engine lane (LR-49827a20) |
| New adapter breaks pinned vendor lists | `test_vendor_check.py` derives expected adapters from the catalog instead of pinning | engine-vendors |
| Object-typed registry key demands `x-text` | The registry meta-schema error should say "use scalar keys or mark x-text" | engine-config |
| Brief names a migration source that is absent | Brief template: "name the file's path and confirm it is in the repo or say it is not" | A Torre |
| Branch named differently by harness and by continuation text | Continuation briefs name the branch once | A Torre |
| Asset entries and unit ownership surprise a new unit | The unit-creation checklist lists `assets.json`, CODEOWNERS and adapter ownership | structure owner |
| Padrão rules lived only in prompts | Now `docs/padrao/v1`; later changes arrive as `padrao_candidate` lessons | CO1 / engine lane |
