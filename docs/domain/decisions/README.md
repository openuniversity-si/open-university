# Decisions as records (D1, D-217)

One file per decision: `D-NNN.md`, written once by `scripts/decision-record --text T --proof PATH`, with its number and time from the claim (`scripts/decision-next --claim`). The table in `docs/domain/DECISIONS.md` is generated from these records in the next step of unit D1; until then the older decisions stay in the table.

When the owner asks the session a question that is not money or other people, the session answers it by recording the decision itself under D-325 (a record here, with its reason and revert path); Daniel may supersede it with a later decision (I-c16f2b7c).
