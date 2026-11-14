# RETRO-API audit

Unit: RETRO-API, the skeleton of a central store that receives each session's log and keeps it.
Owner: A Torre (engine-defects program). Inserted 2026-10-28 20:00 BRT on Daniel's order
"cria so o esqueleto da API pra receber esses logs e deixar armazenado. Em outro momento no futuro,
futuro proximo, a gente pega e resolve o que faz com esses logs" (Daniel decided: build only the
skeleton that receives and stores session logs; what to do with them is decided later).

Base: `mod/roadmap-integration` at `069145b9`. Branch: `mod/retro-api`. PR #798.

## Findings (cheap evidence only)

| # | Finding | Evidence |
|---|---|---|
| A1 | Nothing in the repo collects session logs today. No `scripts/retro`, no `scripts/lib/retro*`, no test. | `ls scripts/retro* scripts/lib/retro* scripts/tests/test_retro*`: no such file |
| A2 | The rot the brief cites holds on this base: 141 units carry a hand-written `retro.md`, 6 of them carry a descent section. | `ls docs/units/*/retro.md \| wc -l` = 141; `grep -l '^## .*[Dd]escen' docs/units/*/retro.md \| wc -l` = 6 |
| A3 | A Claude Code session transcript is JSONL under `~/.claude/projects/<cwd-slug>/<session-id>.jsonl`. Every line is a JSON object with a string `type` (`user`, `assistant`, `attachment`, ...) and a `sessionId`. | this session's file: 123 lines, 0 unparsable, every line has `type` and `sessionId` |
| A4 | **Measured size of one real session log:** this unit's own transcript was 603,492 bytes (123 lines) about 20 minutes into the session. A full unit session of a few hours is in the low megabytes. | `wc -lc ~/.claude/projects/-home-user-the-tower/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl` |
| A5 | The repo has no per-file size budget for stored data. The registered byte budgets are web bundle, fonts, images and Neon/GitHub client limits. GitHub itself warns at 50 MB per file and refuses 100 MB. | `grep -n '"[a-z_.-]*bytes[a-z_]*"' config/registry/*.json` |
| A6 | The repo's own secret patterns are gitleaks' default rules plus `.gitleaks.toml` (allowlists only). `scripts/lib/local_checks.py::secret_scan_diff` already runs `gitleaks dir --redact` and reports `RuleID`, file and line, never the value. | `scripts/lib/local_checks.py:149`, `config/registry/local-checks.json` `local-checks.gitleaks_config` |
| A7 | Only one transcript is reachable from this container: this session's own. A cloud session is one container; other units' transcripts live in their own containers, which this session cannot read. | `ls ~/.claude/projects/*/`: one `.jsonl` |
| A8 | The motor records (claims log, `sessions.log`, tmux captures) live outside the repo under `/workspace/torre/motor` on A Torre's box, not readable from a cloud session. | `docs/programs/live-planning/audit.md:44,64`; `/workspace/torre/motor` absent here |
| A9 | Setup hit a GitHub rate limit through the config change store (429, wait 2544 s); `OU_CONFIG_STORE=file` is the documented local mode. | `scripts/cloud/setup.sh` output, `scripts/lib/config.py:82` |
| A11 | Every real Claude Code transcript carries `turnAttributionKey` on its launch-prompt line, a UUID (36 characters, hex, 4 dashes). gitleaks' `generic-api-key` matches it on the key name, so the first real ingest was refused (`generic-api-key at line 4:24844`). `retro.scan_allowlist` extends the repo's config for the retro scan only and allows that one key with a UUID-shaped value; the same value under any other key is still refused (test). | first `scripts/retro ingest --unit RETRO-API` run; `scripts/tests/test_retro.py` |
| A12 | `pytest` is not installed on this box; the repo's script tests run as `python3 <test>.py` (unittest) through `scripts/tests/<name>.test.sh`. The targeted command is `bash scripts/tests/retro.test.sh`. | `python3 -m pytest`: No module named pytest |
| A10 | A new engine file must be owned by a unit manifest (`units/<id>/unit.json` `paths`) and covered by a test script (`scripts/tests/covers/<name>.json`). | `units/engine-effort/unit.json`, `scripts/tests/covers/local-checks.json` |

## Store decision (follows from A4, A5, A7)

- One log is about 0.6 to a few MB, far under any per-file limit, so the store keeps the **bytes**, not a pointer.
  The ceiling is 50 MB per file (GitHub's warning size, so a later move of the store into a git ref stays possible).
  A log over the ceiling is stored as a header plus the digest and the source path (a pointer), stated as such in the
  header (`"stored": "pointer"`); a log is never truncated.
- Layout, as the brief names it: `retro/logs/<unit>/<session>.jsonl`. Line 1 is the header
  (`{"retro": "header", "v": 1, "unit", "session", "kind", "source", "bytes", "sha256", "stored"}`); the rest is the
  file exactly as the session produced it, byte for byte. A motor record goes to `<session>.motor.log`. A name already
  taken by other bytes (a transcript that grew since the last copy) gets the full sha256 before the extension, so
  nothing is ever overwritten (the file is opened with `O_EXCL`).
- The store root is `<checkout>/retro`, or `$TOWER_RETRO_STORE`. **It is not committed in this PR, and `retro/` is
  gitignored.** Reason: a transcript carries the full launch brief, the operator's e-mail address and every tool
  output; once in git history it cannot be taken out of every clone. Choosing where the central copy lives
  (a dedicated git ref with one writer like `plan/live` (P-48), or the R2 bucket inside the D-073 free allowance) is
  the first future unit below, and it is reversible: the store is a plain directory plus an index, so it moves as is.
- The index is `retro/index.jsonl`, one line per stored file: unit, session, kind, path, bytes, sha256, stored,
  received_at. It is the only derived thing.
- The secret scan is the repo's own: gitleaks with `.gitleaks.toml`, `--redact`, extended for this scan only by
  `retro.scan_allowlist` (A11). A hit refuses the file and names the
  rule and the line:column offset. No gitleaks means no scan, and the file is refused (fail closed).

## Future consumers (nothing consumes the store yet, on purpose)

**Nothing reads `retro/` today.** No merge-path step, check, gate stage, event or report opens the store or the index,
and this PR adds none. The seam is `retro/index.jsonl` plus `scripts/lib/retro.py::indexed()`, read-only.
These units would read it later, each a unit of its own:

1. **The central copy**: puts the store where every session can reach it (a one-writer git ref like `plan/live`, or the
   R2 bucket inside the D-073 free allowance), so a log outlives its container; first, because without it a log dies
   with its cloud session.
2. **The hand-in at session end**: makes every session call `scripts/retro receive` (or its API successor) on its own
   transcript when its unit ends, so the coordinator does not have to fetch logs that live in other containers.
3. **The retro document**: writes a unit's `retro.md` from the unit's stored logs instead of from a session's memory.
4. **The analysis session**: reads the stored logs of many units to find repeated work, waits and failures (the descent
   ladder), and proposes rules.
5. **The batch aggregation**: turns index lines and logs into per-program numbers (bytes, sessions, refusals per unit)
   for the planner and the dashboard.

## Proof of storage on real data (2026-10-28, head of plan item 5)

Store root: `<checkout>/retro` (gitignored). Each ingest run below ran twice in one shell call, so the live transcript
could not grow between the two runs.

| Unit | Running tonight | Reachable here | Result |
|---|---|---|---|
| RETRO-API (this unit, PR #798) | yes | yes: its transcript under `~/.claude/projects/` | stored, 1,350,871 bytes |
| REQUESTS-REGISTER (PR #799) | yes | **no**: its transcript lives in its own cloud container | `no transcript for REQUESTS-REGISTER under /root/.claude/projects` |
| ui-playback (PR #659) | yes | **no**: same | `no transcript for ui-playback under /root/.claude/projects` |
| motor records, every unit | n/a | **no**: `/workspace/torre/motor` is on A Torre's box | `no motor records: /workspace/torre/motor is not on this box` |

Plainly: only one of the three units has a log this container can reach. No other log was fabricated or rebuilt from
an API. Ingesting the other two needs the hand-in (future unit 2) or a run on A Torre's box (below).

Run 1, then run 2 of `scripts/retro ingest --unit <u>` for the three units:

```
took logs/RETRO-API/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl from /root/.claude/projects/-home-user-the-tower/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl (1350871 bytes, stored bytes)
index lines after run 1: 1
skipped /root/.claude/projects/-home-user-the-tower/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl: already stored (sha256 eba3f14721681956de71bd533a9e966641e22cf365c99cb9e1444ff054e3bbb3)
index lines after run 2: 1
```

The stored body is the source, byte for byte: body 1,350,871 bytes = header `bytes`, and `sha256(body)` = header
`sha256` (True).

`scripts/retro receive` on a real log path (the same transcript, grown since): kept as a new file, the first one
untouched:

```
took logs/RETRO-API/cc45a4f7-dd10-5b26-92cb-79d0ed703725.85d71dd82573219586c9c4357537b886233d1d049ac5f934418ed1f1a403feba.jsonl from /root/.claude/projects/-home-user-the-tower/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl (1368021 bytes, stored bytes)
exit=0
```

The index after both:

```
{"bytes": 1350871, "kind": "transcript", "path": "logs/RETRO-API/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl", "received_at": "2026-10-28T23:26:52+00:00", "session": "cc45a4f7-dd10-5b26-92cb-79d0ed703725", "sha256": "eba3f14721681956de71bd533a9e966641e22cf365c99cb9e1444ff054e3bbb3", "source": "/root/.claude/projects/-home-user-the-tower/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl", "stored": "bytes", "unit": "RETRO-API"}
{"bytes": 1368021, "kind": "transcript", "path": "logs/RETRO-API/cc45a4f7-dd10-5b26-92cb-79d0ed703725.85d71dd82573219586c9c4357537b886233d1d049ac5f934418ed1f1a403feba.jsonl", "received_at": "2026-10-28T23:27:04+00:00", "session": "cc45a4f7-dd10-5b26-92cb-79d0ed703725", "sha256": "85d71dd82573219586c9c4357537b886233d1d049ac5f934418ed1f1a403feba", "source": "/root/.claude/projects/-home-user-the-tower/cc45a4f7-dd10-5b26-92cb-79d0ed703725.jsonl", "stored": "bytes", "unit": "RETRO-API"}
```

Total stored: 2,718,892 bytes of logs (1,350,871 + 1,368,021) in 2 files; the store directory is 2,720,477 bytes with
headers and index.

Refusals:

```
refused /home/user/the-tower/AGENTS.md: not a transcript log (line 1 is not JSON)                       exit=1
refused .../scratchpad/fake-token.jsonl: carries a secret (github-pat at line 2:37; value not shown)    exit=1
value printed: False
```

The fake token is built at run time from a hash (`'gh' + 'p_' + sha256(...)`), so no token-shaped literal sits in
the repo or in a transcript. The output was checked for the value and does not contain it. (These two lines were
captured before the commit that prints the source once; the reason text is unchanged.)

### What must run after merge (DONE MEANS RUNNING)

The command has run end to end in its real cloud environment (above). The motor-record half can only run where the motor
lives: on A Torre's box, `scripts/retro ingest --unit <id>` for tonight's units reads `/workspace/torre/motor`
(`retro.motor_dir`) and prints one line per record. That first run is the coordinator's, right after merge.
