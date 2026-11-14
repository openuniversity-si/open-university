# Rule challenges (D-138)

Rules exist to be followed. A Torre must also be able to change its own rules, or it becomes rigid. So every rule is
followed AND evaluated: when evidence shows a rule hurts more than it helps, the executor raises its hand with a record
in this folder, graded by impact. Never by quietly working around the rule.

## The three grades (Daniel, 31/10 13:44 BRT)
1. **Clearly stupid, low impact, reversible** (after due consideration): the executor changes or ignores the rule itself,
   records a D-xxx with the evidence and keeps going. Record `Grade: 1`, `Status: changed`.
2. **Debatable**: the executor does NOT break it. It posts on the PR and in chat a block starting `**REGRA EM QUESTÃO**`
   (rule, evidence, harm, proposed change, impact), keeps working on other things, and the watchman (Daniel's
   assistant) decides: lift it (then records it and tells Daniel afterwards), keep it, or escalate. Record `Grade: 2`.
3. **Serious** (affects other people, costs money, touches production, or is otherwise grave): the watchman takes it
   to Daniel. The executor never acts on it. Record `Grade: 3`, `Status: escalated`.

## The record
One file per challenge, `RC-NNN.md` (next free number), with these lines at the top, in order, one line each:

```
# RC-NNN — short title
- Grade: 1 | 2 | 3
- Status: open | changed | lifted | upheld | escalated
- Rule: the rule as written, with its source
- Evidence: what was measured or observed (a command, a number, a link)
- Harm: what the rule costs here
- Proposal: the change asked for
- Impact: who and what the change touches, and whether it is reversible
- Decision: empty while open; otherwise what was decided, by whom, when (BRT)
- D: D-NNN, or none
```

`scripts/rule-challenge list` prints them with grade and status; `scripts/rule-challenge check` fails a record with a
missing line, an unknown grade or status, a status other than `open` without a Decision, a grade 1 without a D-NNN, a
grade 3 that is `changed` or `lifted` without a Decision made by Daniel, and a number that is not the next free one.
An `open` grade 2 or 3 is shown by `list` first, so the watchman sees what waits.

## Relation to the rule register
`scripts/rule` (RULE-AUDIT) tracks rules that can stop a flow and reviews them on a schedule. A challenge is the
event-driven path: it starts from evidence found while working, not from a review date. A lifted or changed rule that
lives in `config/registry/rules.json` is also changed there, in the same commit.

## Proposed padrão rule (for the next padrão version; v8's list is frozen, a change is a new version folder)
> **Question the rules.** Follow every rule and evaluate it. When evidence shows a rule hurts more than it helps, open a
> challenge record (`docs/process/rule-challenges/`). Grade 1 (clearly stupid, low impact, reversible): change it and
> record a D-xxx. Grade 2 (debatable): do not break it; post `**REGRA EM QUESTÃO**` on the PR and in chat and go on
> with other work. Grade 3 (people, money, production, grave): never act; the watchman takes it to Daniel.

Adoption is the watchman's, since it changes the launch rules of every program (D-138 records it as proposed).
