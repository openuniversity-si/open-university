# A lane decides (D-236)

A lane does not wait for a decision and does not ask the coordinating session (D-221). A lane decides everything that involves
neither money nor other people, and then:

1. records the decision with `scripts/decision-next --claim` (the number and the clock time) and `scripts/decision-record --text T --proof PATH`;
2. carries it in its own PR (one commit is enough);
3. reports to the coordinating session after the fact, in one line, with the decision number.

A request for a decision from a lane is an incident: `scripts/incident open lane-asked-decision "TEXT"`. The register keeps it
with its case, class and design fix, so the next lane that meets the same question finds the answer in the register.

Only money and other people go to Daniel. Everything else is the lane's to decide.
