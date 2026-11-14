# The verdict is the last step (Daniel 28/10 20:22)

"É simples: o Gate é uma API que roda os testes e devolve os resultados, seja positivo ou negativo." The gate is an API: give it the head, it runs the tests and returns the result, passed or failed. The last step of every unit is one call, after the last commit is pushed:

```
scripts/gate-verdict --head "$(git rev-parse HEAD)" --pr <n>
```

Run it in the background and let its exit wake the session. There is no wait and no separate reader: the call returns when the judgment does (#797, GATE-WAIT, closed: "Mate o GATE-WAIT").

| Exit | Verdict | Printed |
|---|---|---|
| 0 | PASSED | `verdict PASSED <head> <base> <digest>` |
| 1 | FAILED | `verdict FAILED <head> <base> <digest>`, then `red <stage>: <class>` for each red stage |
| 4 | UNOBSERVABLE | `verdict UNOBSERVABLE <head> <reason>` |
| 64 | usage | the usage error, on stderr |

Exit 0: the PR is judged and passed. Announce it ready and end the turn. Exit 1: the red lines are a task, not a report. Read them (`scripts/gate-dev --why` names the failing test and its log), fix the cause in the code or in the PR body, run the targeted tests, push, and call again. At most three rounds in one turn; after the third FAILED, post a STATUS that quotes the red lines still standing and what you tried, and end. Exit 4: the gate could not run or its input could not be read. Call once more; if it is still UNOBSERVABLE, post a STATUS with the reason and end. It is never a refusal and never reported as a result about the code. Exit 64: the call itself is wrong; fix it.

Asked again about the same head, base and toolchain, the API returns the recorded result instead of running again, so calling again after a FAILED you did not fix changes nothing; push the fix first. `--no-run` asks whether the result is already known without starting the gate. The contract lives in `scripts/lib/gate_verdict.py` and in this table, and `scripts/tests/test_gate_verdict.py` requires them to agree.

`--cold` (D-075, meaning amended by D-076) asks for a verdict with no result of another tree: it never answers from a record (keyed by head, not content), carries no stage over and builds from a fresh build cache, so its `gate.passed` has no `carried_from`; a script test or stage whose content key (the files it reads, the attested `toolchain_id`, the judging runner `gate.content_runner_inputs`; P-56) matches a recorded PASS is reused, from the per-test store and from `gate.content_stage_cache_dir`. With `gate.content_cache_enabled` off (the rollback) every store is fresh and `cache_hits` is 0, as D-075 had it. In a train with `train.admit_mode = verdict` the train asks for it itself when it resyncs a PR (D-075); a session may ask before its first verdict of a head. A cold run of a head and base that already have a warm `gate.passed` publishes the same event id (natural key: repo, pr, sha, plan, `input_digest`), so the forge keeps the warm one: only a new sha carries a cold verdict, which is why the train's resync makes a merge commit. `--cold --no-run` is a usage error.
