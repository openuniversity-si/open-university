# <UNIT> — plan

<!-- PLAN (Padrão v7, D-077, D-081): reads audit.md's `## Causas raiz` and research.md's `## Escada de ambição`; decides before it executes. The PR description mirrors this file. -->

## Alternativas
<!-- For each root of audit.md whose class is structural (regra faltando, mecanismo faltando, arquitetura/desenho), a `### R<n>` with 2-4 alternatives at different levels: remendo (the symptom) / corrige a classe (every instance of the cause) / redesenho (the state of the art from research.md). A `bug local` needs none. Criteria: resolve a raiz?, custo, reversibilidade, risco, degrau (rung of the escada de ambição).

### R1 <the root, as audit.md names it>
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 <option> | remendo | não: <why> | <minutes, quota> | <how to undo> | <what can go wrong> | 0 |
| A2 <option> | corrige a classe | sim | … | … | … | 1 |
| A3 <option> | redesenho | sim | … | … | … | 3 |
-->

## Escolha
<!-- One line per structural root: `- R<n> → A<k>: <justification against the criteria>`. A `remendo` is allowed only with the reason and a `Follow-up: <unit, issue or PR that fixes the root>` on that line or the lines under it. -->

## Commits
<!-- The commits as a dependency graph (3-8, D-025), each with the files it owns (no file owned by two parallel commits) and which run in parallel. -->

## Premises
<!-- `Premises: P-NN, …` or `Premises: none`; each with its blast radius; CRITICAL when its failure changes scope, spends money, touches production or the source of truth. -->

## Tests
<!-- The targeted tests per commit and the single final gate. -->

## Base defects expected
<!-- Known defects of the base this unit will meet, and their owners; "None known" is an answer. -->

## Cheapest useful effort
Action: <the most expensive action of the plan>
Cost: <minutes, quota, money>
Requirement: <who needs its result: a person, a role or a lane, never the gate, the train or the tests>
Cheaper rejected: <the cheaper paths considered and why each does not satisfy the requirement>
