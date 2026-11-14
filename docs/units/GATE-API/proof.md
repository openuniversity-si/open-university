# GATE-API: proof on real heads of tonight

`scripts/gate-verdict` from this branch on this box, 28/10 21:03-21:33 BRT: first with 2ac5c710's code, then the
two bare runs again with this commit's code (the quoted lines). The gate it ran is the pinned base tooling, gate
version `50170989720d558726a0a894787b20c08e0326bf` (the tree of `scripts/` at 069145b9), the same version tonight's
real gates on #659 report. stdout is quoted verbatim; the gate's own output went to stderr. No call wrote to another
PR: a bare `--head` publishes nothing (tier 2: no event, status or record) and `--no-run` only reads.

## 1. A head that passed: 069145b9 (the base tip, the merge of #592 at 19:24 BRT)

```
$ scripts/gate-verdict --head 069145b95c13ee2bf883d80ff6d7966bb87af220
verdict PASSED 069145b95c13ee2bf883d80ff6d7966bb87af220 069145b95c13ee2bf883d80ff6d7966bb87af220 unbound
exit 0, 393 s
```

The gate pinned to 069145b9 (`gate: pinned to 069145b95c13…`), ran all 21 dev stages green in 391 s and printed
`GATE: PASSED`. The first run (21:03-21:11) took 462 s (script tests 318 s, lint 216 s, integration tests 185 s, unit
tests 182 s) and printed the same verdict with the digest `48647d61…`. A bare head is tier 2, so `.gate/verdicts` was
never created. The gate's `.pass` record carries no `input_digest`, because a bare `--sha` run hands its proof hook no
base. The first run also printed a misleading "not recorded" note for a call that records nothing anyway; this commit
drops it.

## 2. A head that failed: 96939004 (#659's head, gated FAILED tonight at 20:01-20:04 BRT)

```
$ scripts/gate-verdict --head 969390040f456f749a170f3f18d325f00ccb5cc4
verdict FAILED 969390040f456f749a170f3f18d325f00ccb5cc4 069145b95c13ee2bf883d80ff6d7966bb87af220 unbound
red generated drift: code
red script tests: code
red unit tests: code
exit 1, 380 s
```

The red tests are the ones tonight's gate on #659 named: `apps/web/tsconfig.paths.json: differs from its
regeneration`, the unit test `ou-addresses.test.ts > … TX32: a new web unit leaves the generated paths file stale …`,
and the script tests `census`, `generate`, `merge-regenerate`, `rule` and `units` (the head is behind the base, which
has files it lacks). Every line of the answer is a task with its class.

**What this run found in the API.** The first run of this call, with 2ac5c710's code at 21:12-21:24, printed
`verdict FAILED … 3c078b31f78e193fe853ad86ff624c9818847d57c34088e9fa82c6a9d8bb9d0f` with the same three red lines.
Tonight's `--pr 659` gate on the same head and base bound that same digest, yet had five red stages (also `structure
check` and `schema compat`). A bare head runs as `gate-local --dev --sha`, which gives its proof hook and its diff
checks no base. So the gate binds nothing, and structure check and schema compat judge without a diff base. One
digest stood for two measurements. Since this commit, a bare head is answered `unbound` and never recorded; the
recorded, keyed answers are the `--pr` ones (section 3).

## 3. A head whose records do not exist: 96939004 asked as #659's head, `--no-run`

```
$ scripts/gate-verdict --head 969390040f456f749a170f3f18d325f00ccb5cc4 --pr 659 --no-run
verdict UNOBSERVABLE 969390040f456f749a170f3f18d325f00ccb5cc4 no recorded result for this input (--no-run)
exit 4, 8 s
```

The PR metadata check ran live and green (P-42), nothing is recorded for this input on this box, and the gate did not
start. With `--json`, the digest the API bound for (96939004, 069145b9):

```
{"base": "069145b95c13ee2bf883d80ff6d7966bb87af220", "digest": "3c078b31f78e193fe853ad86ff624c9818847d57c34088e9fa82c6a9d8bb9d0f", "exit": 4, "head": "969390040f456f749a170f3f18d325f00ccb5cc4", "pr": 659, "reason": "no recorded result for this input (--no-run)", "recorded": false, "recorded_at": null, "red": [], "report": null, "tier": 1, "verdict": "UNOBSERVABLE"}
```

`3c078b31…d9d0f` is the `input_digest` of tonight's real v4 `gate.failed` on #659 for the same head and base (event
`f5e6a839…`, 23:04:55 UTC, bound by another box with the same `toolchain_id` `1b5fd805…`). The key the API looks up is
the one the gate binds.

## 4. The early stop: this PR's own head 91581ac9, `--pr 800 --no-run`

```
$ scripts/gate-verdict --head 91581ac970f0ac5ddb003ae1d1a3914d2bc25b8b --pr 800 --no-run
verdict FAILED 91581ac970f0ac5ddb003ae1d1a3914d2bc25b8b 069145b95c13ee2bf883d80ff6d7966bb87af220 fe398824e8dbe402c7c9991e918520d3adfe7aee7f08355fcc5ed63270e61f71
red pr metadata: code
exit 1, 6 s
```

Plan items 6 and 7 had no commit yet, so the live metadata check was red (`plan: item(s) 6, 7 not ticked by a commit`).
The answer came back in 6 s, and the gate never started, which saves a full run (#780 F1, F2).

## 5. A bare head is never recorded

```
$ scripts/gate-verdict --head 069145b9 --no-run
verdict UNOBSERVABLE 069145b95c13ee2bf883d80ff6d7966bb87af220 a head without --pr is never recorded: the gate binds it to no base (--no-run)
exit 4
```

A bare head is the batch tier (gate_tier.derive, like the gate's own tier hook for `--sha` without `--pr`) and is
unbound, so `--no-run` has nothing to look up. Before this commit the reason read `tier 2 never reads the box-local
store (D-065 (5), --no-run)`. That still holds for a `--pr` call made inside a tier-2 or tier-3 gate run.

## What is proved here and what is not

Proved on real heads: a pass and a failure returned by one call with exit 0 and 1; each red stage with its class;
an unknown result answered 4 without starting the gate; the key equal to the gate's own `input_digest`; the
metadata early stop. The tier-1 record (asked again, answered without a run) needs a `--pr` run that passes or fails
on a content stage. This PR's final head is the first such head this unit can run without writing to another PR.
Item 7's verdict of record shows it: the second call answers from the record. The unit tests cover the rest
(`scripts/tests/test_gate_verdict.py`, 26 cases).
