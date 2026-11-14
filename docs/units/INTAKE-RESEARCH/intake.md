# INTAKE-RESEARCH — intake

## Pedido
Daniel (CEO), 29/10/2026 ~16:01 BRT, via A Torre (pt-BR, literal): "Nossa sim, já coloca isso lá por favor." The proposal he approved: every unit, mini-program or system step starts with INTAKE (`intake.md`) and RESEARCH (`research.md`) before the AUDIT; the flow becomes INTAKE → RESEARCH → AUDIT → PLAN → execution → RETRO; each step delivers a complete, independent product and never dictates what the next one does.

## Intenção
Stop spending effort on the wrong problem and on reinventing known solutions. On 29/10 the request was "gate via API"; the real intention was "PRs enter on their own and fast, toward 1,000 PRs/day". We rebuilt a strict train and only afterwards found that Uber (SubmitQueue), Google (TAP/Bazel) and the GitHub/GitLab merge queues already solve it (speculative verdict, test only what is affected, cache by hash, post-merge verification with revert).

## Contexto
- The Padrão active version is v5 (`coordinator.padrao_version`); `docs/padrao/v5/audit-and-plan.md` starts a unit at AUDIT. A published version is never edited in place, so the change is v6.
- Units live in `docs/units/<UNIT>/` with `audit.md`, `plan.md`, `retro.md` (151 folders today). The effort block (EFFORT-STEP, `scripts/lib/effort.py`) is the model of a structure rule that is not retroactive: a file written before the rule is grandfathered by its first-commit date.
- D-074 (#768) and D-076 (#804) are claimed by open PRs; D-077 is the next free number.
- Production frozen (D-054); this change touches docs, the Padrão, a structure check and its test, no product code.

## Regras
D-025 (commit plan, gate change cites an approved D-NNN: `structure-check` is a gate file), D-054, D-055 (no review step), D-065 (events, never a clock), D-066 (premises), D-069 items 4/8/9 (effort block), D-072 (blocking evaluation), Padrão v5 (`audit-and-plan`, `effort`, `retro-before-merge`, `gate-verdict`), STRUCTURE.md B5 trailers.

## Problema real
Units start auditing before anyone has written down what was asked, why, and who already solved it. Resolved when: every unit folder created after the rule carries `intake.md` (six sections) and `research.md` (four sections), the `structure check` stage refuses a new unit without them, existing units are untouched, and the launch brief (Padrão v6) tells every session the new order.

## Lacunas
- Literal section names: Daniel gave the concept in pt-BR; the files use the pt-BR section names he dictated (Pedido, Intenção, …) so the check reads them literally. Reversible by changing the registry.
- When the rule's date counts: the oldest commit of the registry file, the same measure as the effort rule (no list to maintain). Nothing here depends on Daniel beyond the approval already given.
