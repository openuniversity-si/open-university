# AUDIT-ROOT-CAUSE — retro

## Brief and intake
The brief was complete: the approval quote, the why, the evidence chain (#805 → #807 → #804 → #808 → #809), the four changes and the files to avoid. Two readings were mine and are recorded in intake.md `## Lacunas`: "structural root" means a class other than `bug local` (only those need alternatives), and the minimum chain is three numbered whys (the brief says "usually ~5"; three refuses the single-why symptom without forcing padding). The decision number was not D-080 as the next free one looked: #809 already holds D-080, so this is D-081. The intake's real problem held through the unit.

## Research, audit and plan
The research changed the plan's shape: fishbone became "one `### R<n>` per root, several roots = several branches" instead of a single chain field; MADR gave `Alternativas`/`Escolha`; SRE gave the patch's `Follow-up:`. Dogfooding the new format on this unit found R2 as `arquitetura/desenho` (the plan was designed around a chosen fix; "Cheaper rejected" compares cost of one action, not levels), which is what made a plan *template* the answer rather than one more line in the effort block. The root causes held: nothing later in execution came from a cause the chains missed. Premises: none.

## Execution
Timeline (UTC, 29/10): 21:17 intake + draft PR #810 → 21:18 research → 21:19 audit → 21:19 plan → 21:21 D-081, Padrão v7, templates → 21:24 check + tests → 21:25 docs → gate → retro.
- The first version of the choice parser took the first `A<k>` anywhere in a root's choice text; this unit's own plan names the rejected options in its justification, so it misread them. Fixed before the push: the choice is the alternative right after the root id (`- R1 → A2: …`). Class: regra faltando in my own format spec (the shape said "one line per root" but not where the choice sits); the template and the rule now say it.
- `commit-check --local` refused two things before the check commit was pushed: two literal numbers in the test (they now read `intake.min_whys` / `intake.max_alternatives`), and the D-081 row in DECISIONS.md, whose class list used `|` inside a table cell and split the row into extra columns. Fixed in the same unpushed commit. Class: mecanismo faltando on my side (I ran the local checks after committing instead of before); the repository's pre-push hook was not installed in this checkout (`.githooks` not configured), so the check ran only by hand.
- The cloud toolchain was not installed at session start (only Python under `.toolchain/`); `bash scripts/cloud/setup.sh` took a few minutes before the gate could run.

## Gate
One `gate-dev --pr 810` run on `0f02737f`: every stage green except `pr metadata`, which refused plan item 8 as not yet ticked; that is this retro. Total 210.6 s, over the 180 s ceiling (warning only, D-064 (f)): script tests 91 s and unit tests 77 s, because `config/registry/intake.json` selects the full battery. No known base defect hit.

## Lessons
- A registry file read by a docs-only check (`intake.json`) puts the PR in the full-battery class; owner: gate lane, worth a narrower class for registries whose readers are only structure-check modules.
- Run `scripts/commit-check --local` before `git commit` on a PR that touches DECISIONS.md or tests with numbers; or install `.githooks` in the cloud setup so `pre-push` runs it. Owner: cloud setup (`scripts/cloud/setup.sh`).
- Rung 2 of research.md's ladder is the next step for this rule: refuse a chain whose last why is a person or a flake (word list in the registry). Owner: whoever next amends D-081.
