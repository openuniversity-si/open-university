# BASE-REGIME — intake

## Pedido
From the FLUXO-AMPLO relaunch brief (01/11 13:55 BRT, Daniel's order to A Torre): "If either says BASE BROKEN, fix the base
first in its own PR." `scripts/lane-status` and `scripts/gate-shadow` (the real gate, bypass off) report BASE BROKEN on the
base tip `3d641027` (01/11 14:0x BRT): the shadow run fails in the stage "script tests" (35.5 s, exit 1). The same ten test
names fail in `scripts/test-suite` on the lane's head `c5a21e700`, which is the base plus three generated brief files.

## Intenção
Put the base back to green, so the lanes' gates and the train's shadow judge real code again, and so the rules the script
tests assert are the rules the tooling enforces. The exception regime Daniel granted stays exactly as it is.

## Contexto
- Commit `9c41dc836` (01/11 10:52 BRT, "FLUXO-AMPLO: the exception regime is on, granted by Daniel (D-260)") set the default of
  `regime.exception_active` to `true` in `config/registry/regime/regime.exception_active.json` and in `config/registry/regime.json`.
- From that commit on, every lock that asks `regime.lifted()` or `regime.lift()` lifts: it prints a warning and emits
  `lock.lifted` instead of refusing. The locks are the structure check, commit-check, the flow-metrics count guards, the
  decision claim, the gate lock and the train's tier 2.
- The script tests of those locks assert the refusal. Under the regime they receive a warning and exit 0. Six test modules
  fail: `test_commit_check`, `test_config_check`, `test_structure_effort`, `test_flow_metrics`, `test_lane_ship`,
  `test_structure`, `test_unit_check`.
- Those gates stayed green: the PRs ran under `gate.bypass`, and a PR's gate runs only the tests its covers select, so the
  regime key's readers (declared as `scripts/lib/regime.py` only) selected none of the lock tests. The shadow run is the only
  gate that runs the whole suite.
- Daniel's grant is recorded in the shared store: `regime.exception_active = True`, `granted_by = Daniel`,
  `kept = [money, people]`.

## Regras
- D-260: the exception regime is one recorded state; every lock lifts through `regime.lifted(lock)`; a kept lock never lifts.
- D-151: the gate bypass is one case of the regime; its verdict is green at once and marked.
- D-069 item 5: a verdict depends on the head, the registry and the checkout's local log, never on the shared store.
- D-077 and D-081: intake, research, audit and plan come before the code; every root cause ends in a structural cause.
- D-054: no production change. D-138: a rule that hurts is challenged with a record, never worked around.
- D-272 (this unit's decision, recorded with this PR): the script tests judge the lock rules as written, with the judges' view
  of the exception regime pinned off, and the regime's own lift keeps its own tests.

## Problema real
The base's whole script suite has been red since 10:52 BRT, so the shadow, the train's base health and every lane's
picture of the base are wrong for a reason that is not in the code, and no scoped gate can see it. Resolved means:
`scripts/test-suite` exits 0 on the new base tip, the shadow run passes on it, and `regime.exception_active` is unchanged.

## Lacunas
- Daniel's call, not this unit's: whether the registry default stays `true` (the grant is in force in every checkout) or
  returns to `false` (the registry's own description says "Off by default"). The description and the default disagree since
  `9c41dc836`. The unit does not change the regime's state; it records the question.
- Whether a change to the regime key should select the lock tests (the key's declared readers do not include the locks, which
  read it through `regime.lifted()`). That is a selection rule for the gate: a follow-up, not this unit.
- Whether any test outside the script suite reads the regime live. The gate's own tests (`gate-regime-lock`) and the train's
  tests (`test_train.py`) already set it explicitly; the audit checks the rest.
