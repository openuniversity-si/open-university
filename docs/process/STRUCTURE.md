# Structure rites

Status: Approved by Daniel 2026-10-22 (D-010, D-011, D-012, D-013, D-020). These rites solve the process instances A4,
A5, B4, B5, C5 and D5 of the Brazil batch root-cause analysis ([STRUCTURAL-PLAN.md](STRUCTURAL-PLAN.md#traceability)). They are short on
purpose: each one is a file or a line in a PR, and `scripts/structure-check` (S00b) checks the parts a machine can.

"Gate" below means our local gate (`gate-dev`, `gate-noite`; ADR-24). Nothing depends on GitHub Actions (ADR-41).

Every change also follows the engineering standard D-069; [principles/D-069.md](principles/D-069.md) ties each principle
to the check that enforces it.

## Roles

| Role | Who | Owns |
|---|---|---|
| CEO | Daniel | Decisions (product, domain, priorities). Approves capability designs and the contract. |
| Structure owner | A Torre | The contract, the decision register, the architecture map, capability designs, fit review, the metric. |
| Executor | One short Claude Code session per PR (D-007) | Code, tests and docs of one PR, inside an approved design. |

## A4. Capability first

A request that has happened before, or will plainly happen again ("ship India", "ship Brazil", "add an area"), is first
written as a **capability**: what any instance of the request needs, stated without the instance. The delivery is the
capability's first use. A one-off request stays a delivery.

Test for "recurring": the same verb applied to a different object would need the same code path. When in doubt, it is
recurring.

## A5. Design before PR

Every structural PR (a migration, a new route or command, a new concept, a change to the contract, or more than one
context touched) needs an approved capability design **before** any code. File: `docs/capabilities/CAP-NNN-<name>.md`.

```markdown
# CAP-NNN — <capability, as a verb on any object>
requested: 2026-10-22T10:00-03:00          # when the idea was stated (D5 clock starts here)
requested-by: Daniel                        # message or decision id
status: draft | approved YYYY-MM-DD | done YYYY-MM-DD
visual: no | yes                            # yes requires a Figma node (D-006)
figma: <file key / node ids, when visual>
condition: before-merge open — <a condition of the approval>   # repeat per condition; open | met YYYY-MM-DD
## Concepts        # which CONTRACT.md concepts it uses or adds; a new concept changes CONTRACT.md in the same PR
## Contract        # inputs, outputs, invariants (INV-…), guarantees (G-…), errors
## Out of scope
## PRs             # ordered, small (D-008), each with the invariants it proves
## Target          # the number that says it works (time, size, count)
```

An approval that comes with conditions ("starts only after …", "needs Daniel's approval before production") records
each one as a `condition:` line in the header, with its kind: `before-start`, `before-merge` or `before-production`.
A condition is `open` until someone records `met YYYY-MM-DD` with the evidence in its text. `structure-check` refuses a
malformed line and a `done` capability with an open condition. A PR body that names a capability with an open
`before-merge` condition fails the B5 check (D-054, step 1 audit
[F2](roadmap/STEP-01-audit.md#f2-d-051-and-cap-005-disagree-about-when-the-decision-was-made)).

The executor's prompt is the design plus [CONTRACT.md](../domain/CONTRACT.md) and the architecture map
([AGENTS.md](../../AGENTS.md) → FACTORY.md (archived with Open University at `567176bb`, D-110), ADR-36). The executor does not redesign;
a gap in the design goes back to the structure owner.

## B3. Every unit starts from intake and research (D-077)

**Superseded (D-292, 2026-11-03).** The management method ([METODO.md](../padrao/METODO.md)) governs what each level carries, and the structure check no longer enforces this section. It stays as the record of the rule.

Since Daniel's approval on 2026-10-29 (~16:01 BRT), every unit, mini-program or system step runs
INTAKE → RESEARCH → AUDIT → PLAN → execution → RETRO, each step a file of its folder (`docs/units/<unit>/` or
`docs/programs/<program>/`) committed on its own, after the branch and draft PR (STEP 0):

- `intake.md` ([template](templates/intake.md)) translates the external request into our understanding: `Pedido`
  (literal), `Intenção`, `Contexto`, `Regras`, `Problema real` (one sentence + the metric of resolved), `Lacunas`
  (if only the requester knows, ask before spending effort).
- `research.md` ([template](templates/research.md)) looks outward from that real problem: `Quem já resolveu` (3–5
  references with links), `Estado da arte`, `Encaixe em nós` (copy / adapt / does not fit), `Escada de ambição` (the
  minimum useful step now, which is the plan's cheapest useful effort, → the state of the art). About one page, ~15
  minutes; one line when the reference is obvious.
- `audit.md` ([template](templates/audit.md)) reads intake.md and research.md as inputs, to know the real problem
  and the state of the art: `Entradas` (links to both files) and `Distância do estado da arte` (where our current code
  stands against the research's reference), next to its own findings. Since D-081 (2026-10-29 18:15 BRT) it also
  carries `Causas raiz`: one `### R<n>` per root cause (several causes are several branches, fishbone), each with a
  `Cadeia de porquês` (at least three numbered whys, usually ~5) that stops only at a structural cause we control (a
  missing rule, a missing mechanism, a wrong design; never "someone made a mistake" or "a flaky run") and a
  `Classe:` among `bug local`, `regra faltando`, `mecanismo faltando`, `arquitetura/desenho`. The audit still proposes
  no solution.
- `plan.md` ([template](templates/plan.md)) reads those roots and decides before it executes: `Alternativas`, for each
  structural root 2–4 options at different levels (`remendo` / `corrige a classe` / `redesenho` from the research's
  state of the art) against resolve a raiz?, custo, reversibilidade, risco and degrau; then `Escolha`, one
  `- R<n> → A<k>: <why>` per structural root, a `remendo` only with its reason and a `Follow-up:` for the root. The
  commit graph and the cheapest useful effort block follow.
- Each step delivers its complete, independent product and never dictates what the next one does: the research
  raises no questions for the audit; the audit builds its own and only reads the files before it.

The `structure check` stage enforced this until D-292 (2026-11-03) retired the rule and its module (`unit_intake.py`;
the registry `config/registry/intake.json` stays for the templates). As written then, it refused a folder
first committed at or after `intake.since` without both files, or with a section missing or empty, and, once
`audit.md` exists, without `Entradas` (naming both files) or `Distância do estado da arte`. It is not
retroactive: older folders are not judged. For a folder first committed at or after `intake.root_cause_since` it
also refuses an `audit.md` without `Causas raiz`, a root without its chain or class, and a `plan.md` without 2–4
alternatives per structural root, without an `Escolha` for each, or with a `remendo` choice and no `Follow-up:`. The
launch rules are [Padrão v7](../padrao/v7/intake-and-research.md) and [its audit and plan](../padrao/v7/audit-and-plan.md).

## B4. Every agent starts from the contract

- `AGENTS.md` names DECISIONS.md, this file, EVENTS.md and RELEASES.md under "Read first". Claude Code loads it through
  `CLAUDE.md`. The launch prompt adds the capability design.
- The retired architecture checker rejected duplicated rules (`L6.single-rule`) and rule logic outside the domain
  core (`L6.rules-in-core`) for Open University (S04). It left with the product (OU-DECOUPLE, D-111);
  these guarantees have no verifier in the engine today.

## B5. Structure owner and fit review

Since D-055 (Daniel, 2026-10-25 14:21) there is no review step: a roadmap PR merges into the integration branch once
its gate passes. The PR body ends with:

```
Capability: CAP-NNN
Instances: A1, B3            # root-cause instances or invariants this PR closes
Fit-Review: not reviewed (<who> YYYY-MM-DD: <reason>) | approved by A Torre (independent reviewer session, head <sha>) YYYY-MM-DD | not structural
Claude-Session: <link>
```

**Nobody claims a review they did not get (D-054, D-055).** Without a review the line is
`Fit-Review: not reviewed (Daniel 2026-10-25: no review step)`. `approved` is written only by a reviewer session
that did not write the code, after it posts a PR comment that starts
`Independent fit review (reviewer session, head <sha>): APPROVED` for that head. Between 2026-10-23 and 2026-10-25,
72 PRs merged with an author-written `approved by A Torre` and no review on record (step 1 audit
[F4](roadmap/STEP-01-audit.md#f4-fit-review-is-written-by-the-author)). `structure-check --pr-body` refuses an
`approved` line without the reviewer session and head, and a `not reviewed` line without who, when and why.
`scripts/structure-check --review <pr>` (`review_errors` in `scripts/lib/structure.py`) refuses an `approved` trailer unless the latest review comment
for the current head says APPROVED and names that head. A review that exists and requests changes refuses the merge
whatever the trailer says.

The fit checklist below stays the author's own check, answered in the PR body when a PR is structural.

Fit checklist (answer each in one line):
1. Does it use the contract's concepts, or add one through CONTRACT.md in the same PR?
2. Is every rule in the domain core, declared once, with an id and a test?
3. Does it delete the path it replaces (no parallel old step)?
4. Is every decision it implements in DECISIONS.md with its test linked?
5. Does it make the next instance cheaper (name the next instance and its cost)?
6. Is it small (≤ ~600 changed lines without tests/generated files), with no data committed?

PRs are strictly serial (D-020): the structure owner opens the next PR only after the previous one is merged. Since
D-054 a PR merges into the integration branch, and production is verified once per release, the merge of that branch
into `main` ([RELEASES.md](RELEASES.md)), not once per PR.

`scripts/structure-check` (`fit_review` in `scripts/lib/structure.py`) checks missing or incomplete B5 trailers,
accepting `approved`, `not structural` and the D-055 `not reviewed` form above. The old `ship-verify`
left with the production tail (OU-DECOUPLE, D-111). Under the D-260 exception regime, structure errors
can become explicit warnings (`under_regime` in that same module); a successful exit alone does not prove refusal.

## C5. Decision to code

The path of every domain decision is fixed and starts the same day:

1. **Decision** — Daniel states it (chat, meeting, review).
2. **Register** — the structure owner adds `D-NNN` to [DECISIONS.md](../domain/DECISIONS.md) the same day
   (America/Sao_Paulo), with the invariant it touches and `test pending` if needed. The contract changes in the same PR
   when the decision changes a concept or invariant.
3. **Test** — the first PR that implements it adds the test that fails without the decision, and the register links it.
4. **Code** — only then the implementation, in the same or the next PR.

A decision that reaches code without an entry is a fit-review failure. An entry left `test pending` for more than seven
days appears in the weekly metric report.

## C6. Retire what is finished

Keeping an old asset is a cost to justify, not the default (D-026). What a file protects is in its commit, its test and
its decision; the separate inventory that `structure-check` enforced (`docs/structure/assets.json`) was retired by
D-292. Every migration or transition states its **end criterion** when it starts (a closing migration, a decision
marked done). The PR that meets it deletes the proof, the importer and the compat code in the same change. S16
(`migration:0027_retire_legacy_media` for the frozen asset tables) is the model; D-023 (v1 restore proof) is the
precedent.

## D5. Idea-to-production metric

The primary metric is **idea-to-production time**: from `requested:` in the capability (or the decision date) to the
verified production deploy of the PR that completes it (the merge commit and the production check, which ADR-32 already
records). It is computed, not hand-logged (AGENTS.md: no progress files):

`scripts/idea-to-prod [--since 2026-10-01]` (S00b) reads `docs/capabilities/*.md` and the merged PRs whose body names the
capability, and prints one line per delivery:

```
capability   requested(-03:00)    live(-03:00)         idea→prod  PRs  fixed-cost  marginal  verdict
CAP-003      2026-10-22 10:00     2026-10-23 16:40     30h40m     4    —           ≤1h       ok
```

`marginal` is the time the *next* instance should take once the capability exists (from its Target). Weekly, the
structure owner reviews the report with Daniel. A delivery is **slow** when idea→prod exceeds 2× its target, or when a
second instance of a capability costs more than its target. A slow delivery opens `docs/capabilities/INV-NNN-<name>.md`:
the question, then causes and the definitive structural solution in five instances, and the PRs that follow from it.
The numbers come from the capability's `## Target` lines `idea-to-prod: <24h>`, `fixed-cost: <…>` and `marginal: <…>`
(without `marginal:`, the first `< N h` bound in Target); a capability without `idea-to-prod:` gets no verdict. `live` is
the historical tail's `ship-tail ship-verify: pass` comment on the last merged PR, else its merge time
(`scripts/lib/idea_to_prod.py`, `live_at`). The tail left under D-111: this is a retained reader of historical
evidence, not a current production verifier; the merge-time fallback does not prove a production deploy. `scripts/structure-check`
runs as the gate's `structure check` stage.
