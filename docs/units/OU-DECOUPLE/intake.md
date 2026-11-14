# OU-DECOUPLE — intake

Unit, stage 1 of Daniel's unit standard of 30/10 (Avaliação, evaluation from first principles), carried in the intake
file the `structure check` requires (D-077). Complete on its own: the research, the diagnosis (`audit.md`) and the
solution (`plan.md`) are separate products. Every number here was measured on base `02a7816a` (#821 merged) on
30/10 between 17:55 and 18:10 BRT; the diagnosis measures them again with its own method.

## Pedido
Daniel (CEO), chat, 30/10/2026 17:41–17:47 BRT, top priority (English, literal excerpts):

- "Open University (OU: the Next.js course catalog in apps/web and everything that serves only it) is paused for a long
  time. It must be separated from A Torre's engine as fast as possible."
- "There will be NO separate OU gate. OU code leaves this repository."
- "The OU production site will be taken down (Daniel approved), but ONLY as the very last step, after the code is
  safely archived and the removal has landed."
- "the-tower contains only the engine: gate, train, events, contracts, config, registry, services/runner,
  services/control-plane, docs."
- "Every path in the repo has an area, so nothing falls back to the full battery by accident (add a check that proves
  it, so a future unassigned path fails loudly instead of silently running everything)."
- "Archive first (before any removal lands)": a pushed git tag on the commit before removal, its sha recorded;
  optionally a free private archive repository. "Nothing about OU may be lost."
- "Neon and R2 stay exactly as they are: do not delete or modify their data." "Never change Cloudflare settings."
- "Choose the least destructive action that takes the site offline, and record it as a D-xxx. If the credentials
  available cannot perform it, do everything else and leave the exact remaining step for Daniel."
- Method: Avaliação → Pesquisa → Diagnóstico (measured baseline, a main metric and guard metrics) → Solução in phases
  → one audit/plan/execute/measure loop per phase → Retro; "never delete, skip or weaken engine coverage or
  thresholds to make something pass; quote engine test counts before/after."

## Intenção
OU is shelved; A Torre's engine (the gate, the train, the events and the services that run them) is what Daniel builds
on now. Every engine change still pays OU's cost (install, browsers, builds) and every engine reader has to step
around OU's paths. The intent is a repository whose every file serves the engine, a gate that judges only the engine,
and an OU kept whole somewhere it costs nothing until someone revives it.

## Contexto
- The repository holds 4,457 tracked files: 1,249 under `apps/web` (OU) and 3,208 outside it. 113 unit manifests:
  74 own only `apps/web` paths (OU), 39 are `engine-*`.
- The gate's area map (`scripts/lib/gate-areas.json`) has 15 areas and 23 stages; 8 stages are the engine's (the 7
  `always` stages and `script tests`), 15 are OU's (install, suite union, lint, unit and integration tests, two builds,
  typecheck, performance tests, the database smoke, three browser stages, `gate-db`, production deploy).
- Production is frozen (D-054); the OU site is the Vercel project `prj_HJ0ueSZq4QBI0RYiNqDCxFux1ScO` (team
  `team_feEmDZ0B5CZl98oD8mq8U4UC`), its database Neon `wispy-sun-55356617`, its covers on Cloudflare R2.
- The gate and the train run on the VM runner (e2-micro); a full battery is about 47 min expected there (#821's status
  comment), a docs-only scoped gate 173 s (#821's `gate.passed`).
- No other PR is open on the base (30/10 18:00 BRT): nobody else is changing OU or the gate.

## Regras
- D-105 (this unit's founding decision), D-054 (production frozen, nobody deploys by hand), D-065 (events, lanes),
  D-077 and D-081 (intake → research → audit with roots → plan with alternatives), D-084 (intake and research share one
  commit while every head is gated), D-083 (a draft is judged on what it delivered), D-098 (each green PR merges through
  the train, run by the session), D-096 (a rule a PR adds runs from the next PR: the gate is pinned to the base, P-46).
- Padrão v7: decide-then-report, fix-the-class, save-often, retro-before-merge, no-probe-prs.
- Daniel's constraints for this unit: free tiers only; no secrets anywhere; never `OU_CONFIG_STORE=file` by hand; no
  GitHub Actions workflows; the VM changes only through the documented runner commands; REST quota is shared.

## Sintoma
1. Separating a paused product is a project, not a deletion: 547 files outside `apps/web` name it (351 of them in
   files that act today: scripts, tests, config, units, root files and living docs; 196 in historical records).
2. 16 tracked paths have no area (`services/**`, `.githooks/*`, `.cursor/*`, `.claude/settings.json`,
   `.gitattributes`, `.gitignore`, `.gitleaks.toml`, `apps/web/tsconfig.paths.json`). A diff touching one runs all 23
   stages, OU's builds and browsers included (`gate_areas.plan_for` → `unmapped path: …; full battery`).
3. Worse than reported: 939 of the 3,193 engine paths that do have an area pull OU stages on a one-file diff. 925 of
   them add `install (frozen lockfile)` and `unit tests` (pnpm and vitest in `apps/web`), because the web-readers scan
   finds an OU test (`apps/web/scripts/lib/architecture-engine.test.ts`) that "reads an unknown path" and fails
   closed toward every engine file. The premise "the gate already skips OU steps on engine-only PRs" holds only for
   docs and the config registry.
4. Engine rules are proven inside OU code: for example `apps/web/src/site/domain/no-github-actions.test.ts` asserts
   on `scripts/merge-phase`. Deleting OU as it stands would drop engine coverage without a red signal.
5. A paused product's production site stays up, and the repository has no procedure to retire a product.

## Sistema que falhou
Each symptom is a system that failed; none is a person or bad luck.

| # | System | State | Why it counts as failed |
|---|---|---|---|
| S1 | The boundary between the engine and its products | missing | Nothing declares where the engine ends: engine code, tests, config and CODEOWNERS name `apps/web` directly, and OU's stages are wired into the gate's own plan. Symptoms 1, 3 and 4. |
| S2 | Path ownership (the area map) | exists, needs improvement | A glob list with a silent fail-open fallback and no completeness check: `services/`, `.cursor/` and `.claude/` were added without areas, and no stage noticed. Symptom 2. |
| S3 | Test-to-code dependency tracking (`gate_web_readers`) | exists, needs improvement | Fails closed toward cost: one cross-product read it cannot resolve selects OU's stages for every engine file. Symptom 3. |
| S4 | The product lifecycle (create → pause → retire) | missing | Units create products. No procedure archives one, removes it and decommissions its production in a safe order. Symptom 5. |

## Sistema ideal
- S1: the engine knows a product only through a declared, removable seam. A product owns its directory, its unit
  manifests and its gate stages; the engine names no product path. Retiring a product means deleting its directory and
  its registration, and no engine file changes. A check refuses an engine file that names a product path (Bazel
  visibility, Nx module boundaries and Shopify's Packwerk enforce this idea; see the research).
- S2: every tracked path belongs to an area, as every file in a Bazel workspace belongs to the package of its nearest
  BUILD file. A gate check fails loudly on a path without an area, naming it; the area map never decides by silently
  running everything.
- S3: a test lives with the code it proves. A cross-boundary read is declared, never inferred as "unknown, so
  everything".
- S4: retirement is a procedure: archive with history (a pushed tag, optionally a filtered repository), remove, prove
  the engine is unchanged, then take production offline by the least destructive reversible action, with data kept.

## Distância do sistema ideal
| System | Measured now | Ideal |
|---|---|---|
| S1 | 351 acting engine files name `apps/web`; 26 OU files read engine paths; 15 of 23 gate stages are OU's | 0 and 0; the gate's plan holds engine stages only |
| S2 | 16 unassigned paths; no check | 0, held by a check that fails the gate on the first new one |
| S3 | 939 engine paths pull OU stages | 0 |
| S4 | no procedure, no archive tag, site up | tag pushed and recorded, OU removed, site offline last, Neon and R2 untouched |

## Problema real
The engine cannot exist without OU: it names OU in 351 acting files, judges every engine change partly with OU's
stages, and holds 16 paths no area owns. Resolved when acting engine files that name `apps/web` = 0, unassigned paths =
0 (held by a check), engine diffs select only engine stages, OU is archived by a pushed and recorded tag and removed,
and engine test coverage is not lower than the baseline.

## Lacunas
- Production credentials: this session's egress refuses `api.vercel.com` and `console.neon.tech` (`scripts/cloud/preflight`,
  17:55 BRT: CONNECT answered 403), so the Vercel step may stay Daniel's. Depends on the environment's network policy.
- A private archive repository: this session's GitHub access is scoped to `openuniversity-si/open-university`. Creating another
  repository depends on Daniel.
- How long the VM takes for a removal diff of about 1,250 files is unknown until the first such gate runs.
- Which engine checks run only inside OU's stages (lint, typecheck, vitest) is for the diagnosis to measure.
