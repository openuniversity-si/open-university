# U4 app-course retro

## 1. Brief quality
- Scope item 1 (move files into `units/app-course/`) contradicted S1/P-03 (units stay logical) and Next's App Router; only the audit found it. The brief should say "see S1" instead of "physical form S1 recorded".
- "Allowlist shrinks to zero" cannot hold: Next route segment config (`dynamic`, `dynamicParams`, `revalidate`) must be static literals and `.css` rows are off limits. Never stated.
- The brief named `mod/u4-app-course`, which already existed remotely (old branch, "do not reuse"); the push was refused. The session branch `claude/u4-app-course-0qrrl1` was used.

## 2. Audit and plan
- Held: P-03 (no move), no `text.*` needed (the unit writes no locale text), only consumer is `CatalogLoading`.
- Broke: the plan assumed every JSX literal could migrate; the visual guard (D-006) refuses any JSX-line edit without a `visual: yes` capability with a Figma node, and none exists. Plan changed: only the page-kind word (`kind: "course"`, 8 sites) moved; JSX attribute literals stay in the baseline.
- Also: `ui-playback`'s test asserts `@/ui/playback/LectureAbout` in this unit's view, so that import stays (expand->contract belongs to ui-playback's U4).

## 3. Execution
Audit 06:41, plan, addresses (`@/app/c` to `@ou/app-course`, found by `rg '"@/'`, one miss in `c/*/loading.tsx` fixed by a class search), literals, contract + generated address, merge, two gates. Failures and class:
- ui-playback test pinned an import spelling in another unit's test (cross-unit text assertion).
- Visual guard on markup-line edits (undeclared capability class).
- Untracked new file not seen by the address checker until `git add` (checker reads tracked files).

## 4. Gate
Run 1 (526 s): failed on the visual guard, `premises.test.sh` (base: S1 answered P-03; fixed on base by the next merge) and `generate.test.sh` (base: `@ou/kernel-tables` not resolvable from a node script, `release/domain/intents.ts`). Run 2 (736 s, after merge): PASSED on head ac4c8793; `generate.test.sh` still fails on base and the gate classed it as a known defect. Wall times far above the 180 s ceiling on 4 vCPU; script tests (473 s) dominate.

## 5. Lessons
- Brief template: state the S1 outcome and the Next static-literal and visual-guard limits for app units (owner: A Torre / brief template).
- A `visual: yes` capability for route markup would unblock JSX literals (owner: visual lane); until then JSX literals stay in the baseline.
- Cross-unit "source contains" tests should assert the address through the generated map (owner: ui-playback U4).
- Node scripts importing app code need the `@ou` paths (owner: U1/G1, generate.test.sh).
