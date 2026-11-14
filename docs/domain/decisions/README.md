# Decisions as records (D1, D-217)

One file per decision: `D-NNN.md`, written once by `scripts/decision-record --text T --proof PATH`, with its number and time from the claim (`scripts/decision-next --claim`). The table in `docs/domain/DECISIONS.md` is generated from these records in the next step of unit D1; until then the older decisions stay in the table.
