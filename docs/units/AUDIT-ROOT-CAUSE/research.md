# AUDIT-ROOT-CAUSE — research

<!-- RESEARCH (Padrão v6, D-077). -->

## Quem já resolveu
- **Toyota 5 Whys** (Taiichi Ohno, *Toyota Production System*, 1978; https://en.wikipedia.org/wiki/Five_whys): ask "why" about five times until the cause is a process you can change, not a person. Ohno's own example ends at "no strainer on the pump", a missing mechanism, never "the operator".
- **Ishikawa / fishbone** (Kaoru Ishikawa, 1968; https://en.wikipedia.org/wiki/Ishikawa_diagram): one effect, several cause branches (method, machine, material, measurement, environment, people); each branch gets its own chain. Fixes 5 Whys' known weakness, a single linear chain.
- **Google SRE postmortem** (*Site Reliability Engineering*, ch. 15, https://sre.google/sre-book/postmortem-culture/; workbook ch. 10): blameless; "root cause" and "contributing factors" are listed separately, and every action item is typed (prevent / mitigate / detect) and tracked to closure. "Human error" is never a root cause.
- **MADR / ADR "Considered Options"** (https://adr.github.io/madr/; Nygard 2011): a decision record lists ≥2 considered options with pros and cons against named decision drivers, then the "Decision Outcome" with its justification and consequences.
- **Bazel / Nix hermeticity** (https://bazel.build/basics/hermeticity, https://nixos.org/guides/how-nix-works): an action's identity is the hash of its declared, committed inputs, never of the machine that runs it. The structural fix to "same code, different toolchain verdict"; the patch is to re-check the verdict when it disagrees.

## Estado da arte
Standard: 5 Whys plus fishbone in the audit (several chains, each to a controllable process cause), blameless (no "someone erred", no "flaky"); the cause is classified so the fix's level is visible. Most advanced: SRE-style typed action items and ADR "Considered Options" in the plan, i.e. options at different levels (patch, fix the class, redesign) weighed against explicit criteria, the choice recorded with its consequences and, when a patch wins, a tracked item for the root. Requires: a template that asks for each part and a reviewer, or a check, that refuses a single shallow why and a plan with one option.

## Encaixe em nós
- 5 Whys + fishbone: **copy** as `## Causas raiz` in audit.md, one `### ` per root with its numbered chain (`Por que 1..N`) and a `Classe:` line; several roots = several branches. The stop rule (no person, no flake) copied verbatim.
- SRE contributing factors / typed actions: **adapt**: the four classes (`bug local`, `regra faltando`, `mecanismo faltando`, `arquitetura/desenho`) replace prevent/mitigate/detect, because Daniel's point is the level of the cause; the "tracked follow-up" when a patch is chosen copies SRE's action items.
- MADR Considered Options: **copy** as `## Alternativas` (2–4 per structural root, criteria table) and `## Escolha` in plan.md. Decision drivers become fixed criteria: resolve a raiz?, custo, reversibilidade, risco, degrau da escada.
- Bazel/Nix: **does not fit as code here** (no toolchain change in this unit); used as the worked example in the audit and as the "redesenho" rung, and it is exactly #809's direction.
- A reviewer as the enforcement: **does not fit** (D-055, no review step); the structure check reads the shape instead, as D-077 did.

## Escada de ambição
1. Now (cheapest useful effort): templates + Padrão v7 + the structure check refusing a new audit without chains and classes and a new plan without ≥2 alternatives per structural root and an `Escolha`.
2. Next: the check also refuses a chain whose last why is a person or a flake (word list in the registry), and a patch `Escolha` without a follow-up link.
3. Later: root causes and chosen alternatives become events (`root_cause.recorded`) so the retro and `scripts/lessons` count how often a class recurs and propose a Padrão change.
4. State of the art: SRE-style tracked action items closed by the unit that fixes the root, visible in the program plan.
