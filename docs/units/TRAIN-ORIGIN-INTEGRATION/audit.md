# TRAIN-ORIGIN-INTEGRATION — audit

## Entradas
[intake.md](intake.md), [research.md](research.md), a8feab76d and both merged units.

## Findings
1. The declared census is 55 sites/19 files; actual source has 62/24. Demand confrontation has zero findings.
2. The full ordinary gate fails forge-events, gate-forge-budget, operation-relations, PR creation and push-guard.
3. Origin's incident regression passes `root=`, while the selected reporting function requires `cwd`.
4. Journal fixtures select GitHub while surviving assertions require no GitHub journal writes. The creation guard
   still requires a lane_ship direct POST although lane_ship now uses the port.
5. The machine lacked ShellCheck. A checksum-verified local Debian package restores that host tool; the actual check
   reports one SC2034 warning for gate_run_key_parts, which gate-local consumes after the proof hook returns.

## Causas raiz
### R1. Derived observations describe different snapshots
Cadeia de porquês:
1. The census and static consumer expectations disagree with the merged calls.
2. Conflict selection kept one parent's observations while other-parent source also survived.
3. Derived facts were treated as independently mergeable authority instead of observations of the combined tree.
Classe: mecanismo faltando.
Evidência: operation_relations.confront on a8feab76d and the baseline gate in validation.md.

### R2. Fixtures and public function contracts came from opposite parents
Cadeia de porquês:
1. Incident, journal and creation regressions fail.
2. The selected signature and fixture routes retain assumptions their callers and assertions no longer share.
3. Textual conflict resolution does not check the joined API and responsibility boundaries.
Classe: bug local.
Evidência: test_push_guard.py::RefusalIncident, test_gate_forge_budget.py and test_pr_creation_path.py.

### R3. A cross-file hook output lacks its lint contract
Cadeia de porquês:
1. Standalone ShellCheck reports gate_run_key_parts unused.
2. Its consumer is in gate-local rather than proof.sh.
3. The output assignment does not declare that cross-file use to the lint analyzer.
Classe: bug local.
Evidência: full local ShellCheck after its host binary is installed.

## Distância do estado da arte
Both implementations exist; the combined tree needs a coherent observation and interface.

## Base defects expected
The five observed failures and precise hook annotation are this repair's scope, with no deferred blocker list.
