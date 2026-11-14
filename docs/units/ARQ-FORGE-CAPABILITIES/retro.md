# ARQ-FORGE-CAPABILITIES — retrospective

## Delivered scope

C1 (`428829fa0`) adds obligation classification over operation_demands, journal
separation and the R3 limit, decision D-286, ownership and three requirement tests.
The three previously unowned paths now resolve to engine-events. This is the forge
boundary's cohesive owner, rather than the generic vendor-baseline checker. The
unit delivery record follows that ownership; no new unit manifest was created.

C2 (`95aee0f49`) adds concrete surface checks without replacing behavioral evidence
or adapter selection. Partial-provider fixtures prove construction refusal for
board issue_comments, configured file main, file-kind journal, default journal,
config store, push heartbeat, routing journals and direct/routed change. The
consolidation adds the same-main journal case and a real GitHub identity whose
merge method disappears despite valid evidence. Missing forge operations name
the concrete provider, not the router.

C3 (`6005f1c9a`) prevents required incompatibility becoming pulls=None or
`overlap: skipped`, while IO failures may still skip advice. Optional calls may
return None, but required role-port construction failures propagate. The foreign
ownership fixture invokes approvals once; the local owner branch invokes it zero
times. Gate metadata uses the checked port and propagates compatibility errors.
The shared contract resolves active demand, including conditional approvals, to
existing local behavioral evidence and rejects removed coverage.

C4 is skipped: #1072, merge d4b1e870b, already implements classification. The
unchanged vendor-ports battery passes 44 tests, including 3 classification tests.
There is no second classification mechanism or repeated implementation.

C5 consolidates four local end-to-end tests (declaration, boundary, contract),
updates covers only for forge_requirements.py (test files already match its glob),
and records these results. Its inspection also closes the main-as-journal branch
when there are no routes. Import paths avoid adding numeric literals to the census.

## Measurements and divergences

The current relation is 18 operations, 45 sites, 19 consumers, rather than the
historical audit's 38 sites and 14 consumers. Existing GitHub/Origin contracts,
operation_demands and engine_role caller composition already satisfy those
parts; production adapter files and engine_role need no redundant edits.
operation_relations.json only reconciles observed line numbers and crossings.
It does not assign responsibility. The before/after operations reports are
byte-identical: 55 findings and 18 missing-responsibility refusals, exit 1.

D-286 was returned by decision-next --claim under the lifted decision-claim
regime, explicitly without a remote claim. Global decision-table --write refused
preexisting D-258, D-272 and D-283 row conflicts. Only D-286's row was rendered
with decision_table.row; older records were preserved.

## Local validation

Commands use OU_CONFIG_STORE=file and PYTHONPATH=scripts/lib/hermetic. The actual
runner is bash scripts/tests/forge-events.test.sh (hyphen, not underscore).

- forge-events: 257 tests, exit 0.
- train: 151 tests, exit 0.
- gate-status: 37 tests, exit 0.
- prepush: 40 tests, exit 0.
- flow-check: 14 tests, exit 0.
- vendor-ports: 44 tests, exit 0.
- structure-check: exit 1, two baseline errors remain in docs/units/R1/plan.md (machine as
  Requirement owner) and docs/units/FORGE-PORT/audit.md (two whys in R2). Neither
  file is changed. Exact final command outcome is reported in the PR.
- commit_check.py --local: exit 0, zero refusals (5.12 s).

The post-commit hook pushes each commit automatically. An extra concurrent push
of C2 was refused because its ref had already advanced to that same C2; no
history rewrite was performed. Hook-selected pr-creation-path tests also expose
a baseline AST expectation that omits forge_origin_client.py; both relevant
files are byte-identical to the base. No repair is included here. The known
non-hermetic test_structure and gate-forge-budget defects are not attributed to
this delivery.

## Limits and follow-up

R3 remains a patch: coordination and accounting still live on the forge adapter.
Follow-up: ARQ-ENGINE-COORDINATION, with its own audit of exclusion, renewal,
release and accounting before migration. Static demands remain a floor; unknown
consumers are exposed, not certified. Conditional approval is proven by fixture,
not by current manifests. Local proofs do not certify remote availability,
production, Origin deployment or causal time savings. D-151's green bypass is
not evidence that suites executed. The PR stays draft; no pr.ready or manual
merge is authorized by this delivery.

Premises: none
