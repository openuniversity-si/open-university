# AUDIT-ROOT-CAUSE — intake

<!-- INTAKE (Padrão v6, D-077). -->

## Pedido
Daniel (CEO), 29/10/2026 18:15 BRT, via A Torre (pt-BR, literal): "Perfeito. Me relança isso, por favor. Nossa prioridade, eu acho que é isso, né? Resolver isso." The proposal he approved (his 18:12 message, concept, not literal): the AUDIT stops at the superficial cause, takes a PR or a symptom and patches it ("solução meia boca"); the PLAN takes the audit and does the first solution that comes to mind, without weighing the possible solutions. Most of our problems are structural or architectural and need a redesign, not an optimization. Changes: (1) every audit finding carries a "Cadeia de porquês" down to a structural cause we control, branched (fishbone) when there are several causes, each root classified `bug local | regra faltando | mecanismo faltando | arquitetura/desenho`, the audit still proposing no solution; (2) a plan template that compares 2–4 alternatives at different levels per structural root and records an "Escolha"; (3) the structure check refuses a new unit without them; (4) STRUCTURE, AGENTS/CLAUDE and the Padrão updated; this unit dogfoods the format. Record a new D-NNN that amends D-077.

## Intenção
Stop paying for the same problem one layer at a time. Today (29/10): #805 false conflict → #807 → #804 refused → #808 → gate and train attesting the toolchain from different config stores (#809). Four patches, each on the symptom the previous one exposed; five whys at #805 would have reached the structural cause at once: the toolchain identity depends on the runtime environment, not on hermetic committed inputs. Daniel wants the process to find that cause before the first patch and to choose the fix deliberately.

## Contexto
- D-077 (merged in #806 today) made the flow INTAKE → RESEARCH → AUDIT → PLAN → execution → RETRO and decoupled the steps; `scripts/lib/unit_intake.py` already refuses a new unit's `audit.md` without `## Entradas` and `## Distância do estado da arte`.
- "5 whys" lives only in `docs/process/postmortems/TEMPLATE.md` and `docs/process/incidents/2026-10-28-web-bundle-blocks-the-queue.md`; no unit template asks for it. There is no `docs/process/templates/plan.md`; the plan's shape lives in `docs/padrao/v6/audit-and-plan.md` and the `## Cheapest useful effort` block (`docs/padrao/v6/effort.md`).
- A published Padrão version is never edited in place (`docs/padrao/README.md`), so this change is Padrão v7.
- Open PRs #807 (D-075/D-078), #808 (D-079), #809 (D-080, toolchain attest) and #804 (D-076) own the train and gate files; this unit stays out of `train_admit.py`, `train_verdict.py` and `config/registry/train.json`. Next free decision: D-081.
- Production frozen (D-054); docs, templates, one structure-check module and its tests; no product code.

## Regras
D-025 (commit plan; a gate change cites an approved D-NNN), D-054, D-055 (no review step), D-065, D-066 (premises), D-069 item 4 (cheapest useful effort), D-072 (blocker evaluation, keep going), D-077 (unit flow, decoupling, not retroactive), Padrão v6 (`intake-and-research`, `audit-and-plan`, `effort`, `fix-the-class`, `retro-before-merge`), STRUCTURE.md B3 and B5.

## Problema real
Audits stop at the symptom and plans take the first fix, so structural causes are patched one layer at a time. Resolved when: every unit or program created after the rule has an `audit.md` whose `## Causas raiz` gives each root a chain of whys and a class, and a `plan.md` whose `## Alternativas` weighs at least two options per structural root and whose `## Escolha` justifies the pick (a patch names its follow-up); the `structure check` refuses a new unit without them; older units are untouched.

## Lacunas
- The literal heading and class words: Daniel gave them in pt-BR (Cadeia de porquês, Causas raiz, Alternativas, Escolha, the four classes); the files use them so the check reads them literally. Reversible in the registry.
- "Structural root" for the plan: a root of class `regra faltando`, `mecanismo faltando` or `arquitetura/desenho`; `bug local` needs no alternatives. My reading of "for each structural root cause"; reversible in the registry.
- Nothing else depends on Daniel beyond the approval already given.
