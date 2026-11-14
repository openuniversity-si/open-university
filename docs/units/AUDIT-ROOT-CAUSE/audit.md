# AUDIT-ROOT-CAUSE — audit

Read-only, cheap evidence, base `4607ca6b` (mod/roadmap-integration, 29/10 ~21:15 UTC).

## Entradas
- [intake.md](intake.md): the real problem — audits stop at the symptom and plans take the first fix, so structural causes are patched one layer at a time.
- [research.md](research.md): the state of the art — 5 Whys + fishbone to a process cause, blameless; SRE contributing factors and tracked actions; MADR "Considered Options"; Bazel/Nix as the structural-vs-patch example.
- Read as inputs only; the findings below are this audit's own questions.

## Findings
1. **The audit template stops at evidence.** `docs/process/templates/audit.md` has `## Findings` ("Numbered findings, each with its evidence"); nothing asks why the finding exists. Same in `docs/programs/_template/audit.md` (an Area/Evidence/Consequence table).
2. **5 Whys exists only after an incident.** `rg -il "five whys|5 whys|porquês"` finds `docs/process/postmortems/TEMPLATE.md` (`## Why (five whys)`) and `docs/process/incidents/2026-10-28-web-bundle-blocks-the-queue.md`; no unit template, no Padrão rule.
3. **There is no plan template.** `docs/process/templates/` holds `intake.md`, `research.md`, `audit.md`; the plan's shape is prose in `docs/padrao/v6/audit-and-plan.md` items (a)–(e): commit graph, premises, tests, base defects, cheapest useful effort. None of them asks for options.
4. **"Cheaper rejected" compares cost, not level.** `docs/padrao/v6/effort.md` asks for cheaper paths to the same action; a redesign is never a candidate, because the block judges the plan's most expensive action, not the plan's choice of fix.
5. **The check reads headings only.** `scripts/lib/unit_intake.py` refuses a new audit without `## Entradas` / `## Distância do estado da arte` and never reads a plan; `effort.py` reads only the effort block.
6. **Today's evidence (29/10).** #805 (false conflict) → #807 (train re-verdicts on a toolchain refusal, D-075/D-078) → #804 refused → #808 (dual verdict, D-079) → #809 (toolchain_id from the committed registry, D-080). Each PR's audit took the previous PR's symptom; #809 is the first to reach "toolchain identity is an input of the environment, not of the commit", which a chain of whys at #805 reaches in five steps (worked as R4 below).
7. **No review step catches depth.** D-055: the author writes `Fit-Review: not reviewed`; the only reader of an audit before code is its own session.

## Causas raiz

### R1. The audit rule has no depth: it asks for evidence, not causes
Cadeia de porquês:
1. Por que os PRs de 29/10 remendaram uma camada de cada vez? Each audit stated the symptom its PR saw (finding 6) and the plan fixed that symptom.
2. Por que a auditoria parou no sintoma? Its template asks for "findings, each with its evidence" (finding 1); a symptom with evidence satisfies it.
3. Por que o template aceita um sintoma? Neither D-077 nor `audit-and-plan.md` defines how deep a finding goes or where a chain may stop.
4. Por que nenhuma regra define a profundidade? 5 Whys was adopted only for postmortems (finding 2), as a reaction after an incident, never as the audit's method.
Classe: regra faltando
Evidência: `docs/process/templates/audit.md`, `docs/padrao/v6/audit-and-plan.md`, `docs/process/postmortems/TEMPLATE.md:11`.

### R2. The plan is designed around one solution
Cadeia de porquês:
1. Por que o plano faz a primeira solução que vem à cabeça? Nothing in it asks for a second one.
2. Por que nada pede uma segunda? The plan's contents (a)–(e) start from the commit graph, i.e. from an already chosen fix (finding 3).
3. Por que a única comparação não ajuda? "Cheaper rejected" compares cheaper ways to the same action, not fixes at other levels (finding 4).
4. Por que o desenho é assim? The plan was defined as an execution artifact (D-025 commit plan, D-069 effort); the decision step of an ADR ("Considered Options" → "Decision Outcome") never entered it, and there is no plan template to carry it.
Classe: arquitetura/desenho
Evidência: `docs/padrao/v6/audit-and-plan.md` item 2, `docs/padrao/v6/effort.md`, no `docs/process/templates/plan.md`.

### R3. No mechanism reads causes or alternatives at the door
Cadeia de porquês:
1. Por que uma regra de texto não bastaria? D-077 is the counter-example: the rule exists because sessions skipped what was only text; the gate was what made intake/research real.
2. Por que o gate não pega uma auditoria rasa? `unit_intake.py` reads only the headings `Entradas` / `Distância` (finding 5).
3. Por que ninguém mais pega? There is no review step (D-055, finding 7).
4. Por que então nada pega? The only door is the structure check and it has no shape for a cause chain, a class, an alternative or a choice.
Classe: mecanismo faltando
Evidência: `scripts/lib/unit_intake.py:79-96`, D-055, D-077.

### R4. Worked example (finding 6): the toolchain verdicts disagree because identity depends on the environment
Cadeia de porquês:
1. Por que #805 viu um conflito falso? The train refused a head whose gate verdict named another toolchain.
2. Por que o toolchain era outro? The gate and the train computed `toolchain_id` on different machines.
3. Por que máquinas diferentes dão ids diferentes? The id hashes the config store the process reads at runtime, not the committed registry.
4. Por que o id lê o ambiente? It was designed as "what is installed here", not as a function of committed inputs.
5. Por que isso é a causa e não o remendo? Every later PR (re-verdict, dual verdict) handled a disagreement the design keeps producing; Bazel/Nix hash declared inputs only (research.md).
Classe: arquitetura/desenho
Evidência: #805, #807, #808, #809 (open, owns the fix; this unit does not touch it).

## Distância do estado da arte
- **Already there:** a blameless 5-whys template (postmortems), the door check pattern (`structure check` + `unit_intake.py`, not retroactive by a `since`), and a plan section the gate already reads (effort block).
- **Missing at base:** chains and classes in the audit (R1), alternatives at different levels and a recorded choice in the plan (R2), and a check that reads both (R3).
- **Rung:** base is at rung 0 of research.md's ladder; this unit's target is rung 1.

## Base defects expected
None known for docs/scripts-only changes; the gate's structure-check WARN lines on oversized units predate this PR.
