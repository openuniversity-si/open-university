# OU-DECOUPLE — plan

Stage 4 of Daniel's unit standard of 30/10 (Solução em fases), carried in the plan file the `structure check`
requires (D-077, D-081). It reads `audit.md`'s `## Causas raiz` and `research.md`'s `## Escada de ambição`, weighs the
alternatives, chooses, and orders the work in phases with measurable targets. Each phase then runs its own loop
(audit, plan, execute, measure) in `phases.md` and passes only when its target is met and no guard metric got worse.

## Alternativas

### R1 The engine has no declared boundary with the products it delivers
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Keep OU in the repository but give its areas no stages | remendo | não: 351 engine files still name it and the next product would repeat it | one PR | revert the PR | OU code rots in place, and its references mislead readers | 0 |
| A2 Remove OU after an archive tag, delete or make generic every acting engine reference, and add a check that no acting engine file names a product root | corrige a classe | sim: the engine stops naming OU, and the check refuses the next crossing | four PRs | the tag restores every byte; each PR reverts on its own | a removal judged by a base that still reads OU (the pin, P-46), which the phase order prevents | 1 |
| A3 A declared product seam: products register paths, stages and units in one manifest the engine reads, with Bazel-style visibility | redesenho | sim | a new mechanism, built for zero products once OU leaves | revert | speculative design with no product to validate it | 3 |

### R2 The area map is not total, and both of its fallbacks are "run everything"
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Add the 16 paths to areas | remendo | não: the next new top-level path falls back silently again | minutes | revert | the gap reopens without a signal | 0 |
| A2 Give every path an area, add a test that the tree is fully covered, make the planner refuse an unmapped path by name instead of running everything, and plan an empty diff as the `always` stages | corrige a classe | sim: totality is stated, checked and loud, and no fallback runs the battery by accident | one PR | revert; the refusal is one branch of `plan_for` | a forgotten path turns a gate red: loud, with the fix in the message, by design | 1 |
| A3 Ownership by construction: each directory declares its area in a file, as a Bazel package does | redesenho | sim | a file per directory plus a loader | revert | churn in every directory for the same result as A2 | 3 |

### R3 Engine checks were written as product tests
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Delete OU's tests with OU and accept the lost assertions | remendo | não: engine coverage drops (G1, G2) | none | the tag | engine rules stop being proven, silently | 0 |
| A2 Port every engine assertion that lives in OU to engine script tests before the removal, and retire with OU what only judged OU (the architecture checker, whose 25 rules all target `apps/web/src`) | corrige a classe | sim: each kept rule is proven where its code lives, and the R1 check keeps tests from crossing again | part of one PR | revert | a missed assertion, found by listing every OU file that reads engine paths (audit finding 6) | 1 |
| A3 Declared test dependencies (test targets with deps) instead of the reader scan | redesenho | sim | a dependency model for every test | revert | large change for a scan that loses its only cross-product subject with OU | 3 |

### R4 The repository has no procedure to retire a product
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Retire OU by hand, once | remendo | não: the next retirement improvises the order again | the same work | — | the order (archive, gate, removal, production) is lost with this session | 0 |
| A2 Write the retirement procedure (`docs/process/RETIRE.md`) and follow it for OU, phase by phase, with each step's proof | corrige a classe | sim | one document, in the last PR | revert | none beyond A1's | 1 |
| A3 An automated `scripts/retire <product>` | redesenho | sim | a command for a case with no other instance | revert | code without a second user | 2 |

## Escolha
- R1 → A2: it resolves the root for OU and guards the class for the next product at a fraction of A3's cost. The guard
  check is A3's rule without its machinery, so the step to A3 stays open.
- R2 → A2: the only alternative that makes "every path has an area" an invariant that fails loudly, as Daniel asked.
  A3 gives the same result at more cost.
- R3 → A2: it keeps G1 and G2 whole, which A1 breaks. A3's dependency model has no second product to serve.
- R4 → A2: writing the order down costs one document and is what makes the next retirement cheap.

## Fases
The pin decides the order: a PR is judged by its base's tooling (P-46). So the base must stop reading OU before a PR
deletes OU, and the archive must exist before the deletion merges. Each phase is one PR against
`mod/roadmap-integration`, gated with `scripts/gate-dev --pr N` and merged through the train (`scripts/train run --pr
N`), one after another.

| Phase | PR | What | Measurable target | Guards checked |
|---|---|---|---|---|
| F0 | #822 | This decision, evaluation, research, diagnosis and plan | the four stage files pass the `structure check`; merged | G3 |
| F1 | 2 | Nothing runs the full battery by accident: every path gets an area; a test proves the tree is covered; `plan_for` refuses an unmapped path by name; an empty diff plans the `always` stages | T1: 16 → 0 unassigned paths, held by the test; `plan_for(['.gitignore'])` and `plan_for([])` select no OU stage | G1–G5 |
| F2 | 3 | The engine gate runs only engine checks: port the engine assertions OU holds (finding 6); OU's areas keep paths but select no stage; OU's 15 stages leave the plan; the base's engine stages are proven on a tree without OU | T2: 939 → 0; T3: 15 → 0; the F2 head's structure check, generated drift, schema compat and script tests pass on a worktree with OU deleted | G1–G5 |
| F3 | — | Archive: tag `ou-archive-2026-10-30` on the base tip after F2 merges, push it, record its sha | `git ls-remote origin refs/tags/ou-archive-2026-10-30` equals the recorded sha, and that commit holds all 1,249 OU files | G6 |
| F4 | 4 | OU leaves: `apps/web`, the 74 OU units, the OU-only scripts, their tests, registry keys, contracts and docs, and every generated file regenerated | T4: 1,249 → 0 files, 74 → 0 units; every removed engine test listed with its reason | G1–G6 |
| F5 | 5 | The engine names no product: remaining acting references generic or gone (gate, toolchain, docs, CODEOWNERS); a check holds M at 0; `docs/process/RETIRE.md`; the retro | M: 351 → 0, held by the check | G1–G6 |
| F6 | — | Production offline, last: Vercel `POST /v1/projects/prj_HJ0ueSZq4QBI0RYiNqDCxFux1ScO/pause?teamId=team_feEmDZ0B5CZl98oD8mq8U4UC`, announced on the PR first. This session's egress refuses `api.vercel.com` (audit finding 11), so the step goes to Daniel with the exact command | the site answers 503 `DEPLOYMENT_PAUSED`; Neon and R2 untouched | G6 |

A private archive repository is not created in this unit (research, "Encaixe em nós"). The tag already keeps every
byte, and this session cannot create a repository. `phases.md` records the exact `git filter-repo` command that cuts
one from the tag.

## Commits
This PR (F0) is four serial commits, each its own stage product: D-105; evaluation and research (one commit, D-084);
diagnosis; this plan. Each later phase PR opens with its loop's audit and plan in `phases.md`, then its execution
commits, then its measurement. Each commit is green on its own, so no two commits own the same file at the same time.

## Premises
Premises: P-46. The gate is pinned to the base tip (confirmed, high): it decides the phase order above. If it failed,
F2's preparation would be unnecessary, not harmful.

## Tests
- F1: a script test over `git ls-files` that every tracked path matches an area, plus `plan_for` cases (unmapped →
  refused by name, empty → `always` only).
- F2: the ported assertions as script tests; the engine stages run by hand on a worktree with OU deleted.
- F4: the engine suite (`scripts/test-suite`), counts quoted before and after.
- F5: the guard check as a script test, and the engine suite once more.
- Each phase's single final gate is `scripts/gate-dev --pr N` on its head.

## Base defects expected
- The VM runner gates a merged head with the full battery and holds the only runner (audit finding 3). This unit's
  gates run in its session.
- The runner's orphaned `gate.lock` after a job killed at 3,600 s (Daniel's note): a finding for engine-service unless
  it blocks this unit.

## Cheapest useful effort
Action: delete Open University from the repository after an archive tag, in the order the pinned gate requires
Cost: five PRs, about five session gates and five train runs, no money, no production write except the final pause
Requirement: Daniel, who wants the engine separated from the paused OU as fast as possible, nothing lost, and the site down last (17:41–17:47 BRT)
Cheaper rejected: one PR that deletes everything at once (judged by a base that still runs OU's stages and reads OU's files, so it cannot be green); hiding OU's areas without removing it (R1 A1: the references stay)
