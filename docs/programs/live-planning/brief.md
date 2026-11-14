# Live planning — brief (LP2)

Ordered by Daniel 15:02 BRT 27/10/2026, confirmed 15:03; gate-excellence keeps running on its own plan in parallel.

**Intention.** Plans are static: information found mid-flight is rediscovered by every unit instead of changing the plan.
A planning coordinator keeps the plan alive: on every new piece of information it openly judges pertinence ("does this
change the plan? can I make the rest better or faster?") and acts (insert a short prep unit, reorder, re-split, change the
next launches, reuse or redo running sessions). PRs never stop or wait; only the plan moves. Every decision is recorded with
context and intention. Values: agility and robustness. General (Padrão level), not only gate-excellence.

**LP2 scope (preparation before the fan-out, D-071).** Program record and premises (LP-P1..P5 = P-48..P-52); the three
docs from LP1 (`audit`, `design`, `plan`, unchanged from `mod/lp1` 857955b8); the `plan.*` event contracts; the
`planner.*` registry keys; the engine-coordinator manifest paths; stubs of `plan_live`, `plan_triage`, `scripts/plan`;
the hand runbook (live-planning.md). On its merge LP3-LP8 launch together and find
every shared file written. No gate file is touched; `gate-script-tests.json` is not edited (GX-08 replaces it with
`# gate-covers:` headers).
