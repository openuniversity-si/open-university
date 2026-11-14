# GX-16 audit (base fbc09f28)

## Already done by merged units (not redone)
| Goal item | Where on the base | Unit |
|---|---|---|
| failed PATCH never POSTs a duplicate | `forge_github.py` `upsert_comment` (re-raises unless 404) | GX-FIX-forge-rate #718 |
| secondary-limit 403/429 = wait + bounded retry, not fatal auth | `github_api.py` `_request` (`_limit_kind`, `limit_retries`), `forge_rate.py` | #718/#720 |
| best-effort live edits dropped, not delayed | `gate_status.push(force=False)` -> `max_wait_s=0` | #718 |
| own `tower/gate` commit status | `gate_status.set_status` | GX-17 #699 |
| write/read count (W/R by method) | `forge_rate.count_request/counts`, `github-client.count_file_env`, `report['forge']` | #720 |

## Still to do (file:line on the base)
1. Counter by method AND endpoint: `forge_rate.count_request` records only `W|R METHOD` (forge_rate.py:154) and is called from `github_api._request`. The file `forge_rate.py` is not in my list; the counter hook lives in `github_api.py`, which I own, so the endpoint is passed there and the count file gains the endpoint (backward compatible `W|R` prefix). -> commit 1.
2. One comment per PR, not per head+mode: `gate_status.marker_line` (gate_status.py:46) carries `sha=` and `mode=`, so every push posts a new comment. Needs a per-PR marker, edited across heads, superseded heads collapsed. `gate.status_one_per_pr` (new).
3. PATCH only at stage end, at most once per interval: `stage_event` pushes at stage start too (gate_status.py:~268); `gate.status_min_interval_s` is 15 (gate.json:447) -> 60.
4. `begin` twice (gate-local:290 and :386): the second `begin` forces a publish and a second `pending` status (gate_status.py `begin`). Becomes a replan: state update only, no forced edit, no second status. gate-local is not touched.
5. Red rows lack the D-027 class and the log path: `render_final` (gate_status.py) has stage/result only. The class is the `GATE-CLASS:` machine line in the stage log (`gate_classify.py`); the log is `<logs>/<slug>.log`.
6. Failure signatures not redacted: `render_final` prints `item['signature']` via `cell()`; `github_cli.redact` exists. Apply in `cell` for signatures.
7. Body above the limit: `gate_status.render_final` cuts the events but a table above `gate.status_max_chars` still fails the write at the API; `forge_github.upsert_comment` has no split. Add: overflow goes to continuation comments, never fails the gate.
8. Registry: `github-client.secondary_limit_retries/backoff_s` are covered by `limit_retries` and `min_block_s` (#720); I add no duplicate keys (stated in plan). New: `gate.status_one_per_pr` (true).

## Fences
`gate-local`, `gate_report.py`, `gate_publish.py`, `forge_events.py` untouched.
