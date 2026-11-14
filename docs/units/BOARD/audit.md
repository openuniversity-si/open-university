# BOARD (E2) — audit

## Entradas
- [intake.md](intake.md): the order, the channel's measured hour and the four proofs.
- [research.md](research.md): sticky comments, a view apart from the log, convergence by a deterministic rule.

## Findings
1. Every board kind is a new comment on #865 (`GitHubAdapter.append` posts one comment per chunk); 7 kinds appear in 13–14
   comments each per hour (intake).
2. `upsert_comment` finds its comment only in the newest page: on an issue of 1433 comments a comment from an older page is not
   found, so the next write creates a second one (`scripts/lib/forge_github.py`, `upsert_comment`, `pages=1`).
3. The find-or-create lock is `_upsert_lock(self.env)`, a file lock of one session: two machines can both find none and both
   create.
4. A body above `forge-events.github_comment_max_chars` becomes continuation comments (`_split`), one more comment per overflow.
5. A comment deleted by hand: the PATCH answers 404 and the upsert creates it again (GX-FIX-forge-rate) — the one proof the
   current code already holds.

## Causas raiz

### R1. The view and the log are one stream
Cadeia de porquês:
1. Por que o canal cresce com o batimento? Because each state event is a comment.
2. Por que é um comentário? Because the port has no view: the only way to show state on the forge is to append it.
3. Por que não há vista? Because GV1 built upsert for one gate comment per head, never a board of the flow's state.
Classe: arquitetura/desenho
Evidência: finding 1.

### R2. The upsert is safe for one writer on a short thread only
Cadeia de porquês:
1. Por que um quadro duplicaria? Because the find misses an older page, a second machine, or splits an oversized body.
2. Por que? Because the find reads one page and the lock is a session's file.
3. Por que isso bastou? Because its one caller, the gate's head comment, is written by one process on a PR of a few comments.
Classe: mecanismo faltando
Evidência: findings 2, 3 and 4.

## Distância do estado da arte
We have an upsert keyed by first line (sticky comments' mechanism) and a log on a ref (E1). Missing: the view built from the log,
its own issue, convergence of racing writers, and cutting to size with the excess on a ref. Rung 0; this unit is rung 1.
