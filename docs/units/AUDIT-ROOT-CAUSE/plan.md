# AUDIT-ROOT-CAUSE — plan

Reads [audit.md](audit.md) (`## Causas raiz` R1–R4) and [research.md](research.md) (`## Escada de ambição`). The PR description (#810) mirrors this file.

## Alternativas

Criteria: resolve a raiz? (does it remove the root cause or only its current symptom), custo, reversibilidade, risco, degrau (rung of research.md's ladder).

### R1 The audit rule has no depth (regra faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Add "go deeper" to the audit template's Findings hint | remendo | não: a hint without a stop rule still accepts one why | 2 min | total | sessions ignore it, as before D-077 | 0 |
| A2 `## Causas raiz` with a numbered `Cadeia de porquês` per root, branches as several roots (fishbone), a blameless stop rule and a `Classe:` among four | corrige a classe | sim: every new audit must reach and name a structural cause | 15 min | registry words | a long chain written by rote | 1 |
| A3 Replace the audit with an SRE-style postmortem per unit, reviewed by a second session | redesenho | sim, plus a second reader | a session per unit | low | contradicts D-055 (no review step) | 4 |

### R2 The plan is designed around one solution (arquitetura/desenho)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Add a "considered options" line to the effort block | remendo | não: the effort block judges the most expensive action of a chosen fix | 5 min | total | mixes cost of an action with the choice of a fix | 0 |
| A2 A plan template whose first sections are `## Alternativas` (2–4 per structural root, at different levels, against fixed criteria) and `## Escolha` (justified; a patch names its follow-up), before the commit graph and the effort block | redesenho | sim: the plan becomes decide-then-execute, as an ADR | 15 min | registry words + template | longer plans | 1 |
| A3 A separate ADR file per decision (MADR), linked from the plan | redesenho | sim | a file per unit and a new folder rule | medium | duplicates DECISIONS.md and D-NNN | 3 |

### R3 No mechanism reads causes or alternatives at the door (mecanismo faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Padrão text only | remendo | não: D-077 shows text is skipped | 0 | total | same failure | 0 |
| A2 Extend `unit_intake.py` (structure check) to read the shape: each root has a chain of ≥3 whys and a known class; each structural root has 2–4 alternatives and an `Escolha`; a patch choice names a `Follow-up:`; behind `intake.root_cause_since`, not retroactive | corrige a classe | sim, for every new unit and program | 25 min + tests | registry `since` | refuses a unit in flight created after 21:15 UTC | 1 |
| A3 A model-graded check that the last why is structural | redesenho | sim, also judges content | paid calls per gate | low | nondeterministic gate, cost | 4 |

### R4 Toolchain identity depends on the environment (arquitetura/desenho)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Re-verdict on disagreement (#807) and dual verdict (#808) | remendo | não | done | — | keeps producing disagreements | 0 |
| A2 `toolchain_id` hashes the committed registry (#809, D-080) | redesenho | sim: identity is a function of committed inputs (Bazel/Nix) | owned by #809 | — | — | 3 |

## Escolha
- R1 → A2: it is the cheapest option that makes depth part of the audit's shape; A1 does not resolve the root, A3 conflicts with D-055.
- R2 → A2: the root is the plan's design, so only a redesign answers it; A2 reuses the existing plan file and D-NNN instead of a new ADR folder (A3).
- R3 → A2: the door already exists and is deterministic; A3's paid, nondeterministic grading is rung 4. The check reads shape, not quality; research.md rung 2 (last why not a person or a flake) is the next step.
- R4 → A2: not this unit's code; #809 owns it. Recorded here as the worked example of a redesign choice.

## Commits
Sequential (each one push, one `Plan: N` trailer); no parallel commits, every file has one owner:
1. `intake.md` → 2. `research.md` → 3. `audit.md` → 4. `plan.md` → 5. D-081, Padrão v7, templates (`docs/process/templates/{audit,plan}.md`, `docs/programs/_template/{audit,plan}.md`) → 6. `scripts/lib/unit_intake.py`, `config/registry/intake.json`, `scripts/tests/test_structure_intake.py`, covers → 7. `STRUCTURE.md` B3, `AGENTS.md`, `docs/padrao/README.md` → 8. `retro.md`.

## Premises
Premises: none. Not CRITICAL: no scope, money, production or source-of-truth change; the rule is not retroactive.

## Tests
Commit 6: `python3 -m pytest scripts/tests/test_structure_intake.py` (each refusal and the accepted case). Final gate once on the exact head: `scripts/gate-dev --pr 810`.

## Base defects expected
None known.

## Cheapest useful effort
Action: extend the existing intake structure-check module with the root-cause and alternatives checks behind a new `since`, plus templates and Padrão v7
Cost: about 40 minutes of session time and one gate run
Requirement: Daniel, who wants every new unit to reach the structural cause and weigh redesigns without reminding each session
Cheaper rejected: only a Padrão text (D-077 shows text alone is skipped; nothing refuses a symptom-level audit); a free-text "5 whys" field (accepts one why and no class, which is the failure being fixed)
