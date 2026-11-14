# engine-premises contract (1.0.0)

The unit is logical (S1, P-03) and has no `@ou/` address, so the manifest `contract` slot stays empty (a filled slot is red in `scripts/unit-battery`). The published surface keeps its paths and behaviour:

| Surface | Behaviour |
|---|---|
| `scripts/premises [--root DIR] [--at TIME] find\|propose\|answer\|list\|blast …` | the premise register (D-066) |
| `premises.load`, `check_line`, `setting`, `computed_radius`, `sealed`, `digest` | imported by `structure.py`, `lessons.py`, `defects.py`, `local_checks.py` |
| `decision_premises` | D-NNN rows and their `Premises:` clause, read by the structure check |

`premises.setting` now reads each `premises.*` registry value once per process; the values and names are unchanged. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: none (the no-literals check finds zero; no `x-literal-sites` entry names the unit). Battery: `scripts/unit-battery engine-premises`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate` shows no drift for this unit.
