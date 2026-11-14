# ENV-FIX-PREMISE-BLAST: plan

Base `mod/roadmap-integration` at `069145b9`. Class `env` (D-027). See audit.md.

## Commits
1. Audit and plan (`audit.md`, `plan.md`).
2. `premises.producer` = `premises`, with a registry test that every `*.producer` matches the envelope pattern.
3. The config store reader quarantines invalid envelopes (`config.store_quarantine_log`), tested with the real
   `premise.blast` event of #548.
4. Known-defect record for the incident (`scripts/defects record`).
5. Retro (`retro.md`), after the gate on the head.
6. Gate round 1 (`gate-dev --pr 801` on `8db14e03`, class `code`): the regenerated
   `scripts/lib/generated/config_registry_config.py`, the quarantine test without new literals (census), and the
   effort block of this plan.

## Cheapest useful effort
Action: the final `scripts/gate-dev --pr 801` on the final head.
Cost: one gate run, about 8 min wall (a `scripts/lib/config.py` change runs the full script suite).
Requirement: Daniel needs the merge door: every queued PR (#800, #798 and the rest) waits on a readable config store.
Cheaper rejected: only the targeted unittest modules (they prove the fix, not that setup.sh, pre-push and the other
suites read the store again).

Premises: none
