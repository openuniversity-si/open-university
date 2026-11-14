# <UNIT> — audit

<!-- AUDIT (Padrão v7, D-077, D-081): read-only, cheap evidence. Complete on its own; it states causes and never dictates the plan's work. -->

## Entradas
<!-- Links to this unit's intake.md and research.md, read as inputs: the real problem and the state of the art. They inform the audit; they do not dictate its questions, which the audit builds on its own. -->

## Findings
<!-- Numbered findings, each with its evidence (file:line, command, PR). -->

## Causas raiz
<!-- 5 Whys + fishbone, blameless (Padrão v7, D-081). One `### R<n>. <title>` per root cause; several causes are several branches. Each root: `Cadeia de porquês:` with at least three numbered whys (usually ~5), `1. Por que …? …`, down to a STRUCTURAL cause we control (a missing rule, a missing mechanism, a wrong design). "Someone made a mistake" or "a flaky run" is never a stop: ask why the system let it happen. Then `Classe:` with one of: bug local | regra faltando | mecanismo faltando | arquitetura/desenho, and `Evidência:`. State causes only; NO solution here (the plan weighs the alternatives).

### R1. <the cause, in one line>
Cadeia de porquês:
1. Por que <the finding>? <answer, with evidence>
2. Por que <that answer>? <answer>
3. Por que <that answer>? <answer>
Classe: <bug local | regra faltando | mecanismo faltando | arquitetura/desenho>
Evidência: <file:line, command, PR>
-->

## Distância do estado da arte
<!-- Where our current code stands against the reference in research.md ("Estado da arte"): what we already have, what is missing, which rung of the "Escada de ambição" we are on. -->

## Base defects expected
<!-- Known defects of the base this unit will meet, and their owners; "None known" is an answer. -->
