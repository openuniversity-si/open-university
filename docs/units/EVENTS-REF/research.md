# EVENTS-REF (E1) — research

## Quem já resolveu
- Kafka and every log-structured broker (Kreps, "The Log", 2013): state changes are an append-only log separated from the
  human-facing views built on it; a view never carries the log's volume.
- Git as a database: Gerrit's NoteDb (review metadata in `refs/changes/*/meta`, one commit per update), git-appraise and
  git-bug (issues and reviews as commits on refs), and GitHub's own merge queue state off issue comments.
  https://gerrit-review.googlesource.com/Documentation/note-db.html
- Bors-NG and Homu (merge trains): they keep queue state in their own store and write to the PR only the human result
  (merged, failed with the reason).
- GitHub's documented limits: secondary limits are per account across all its processes ("content creation" writes), and an
  issue holds at most 2500 comments; GitHub recommends serialising writes rather than parallel requests.
  https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

## Estado da arte
The standard: an event log in a store built for appends (a broker, a database, or refs), and the forge receives only the
records people act on, written by one publisher. The most advanced (NoteDb): the metadata lives in git itself, versioned with
the code, replicated by the same protocol, with optimistic concurrency by fast-forward. It requires nothing but git and a
bounded retry on a lost race.

## Encaixe em nós
- **Copy**: NoteDb's shape: one ref, one commit per append, the record as the commit's content, compare-and-swap by
  fast-forward. We already do it for `train/wake` and the lock (D-070).
- **Adapt**: one ref for every channel (the record names its channel), because the proxy allows creating and fast-forwarding
  `refs/heads/*` but not deleting them, so a ref per PR would accumulate forever.
- **Does not fit**: a broker or a database (a new service, money, a credential); GitHub's Checks API (REST, the same limits).

## Escada de ambição
1. (this unit) State kinds go to `refs/heads/train/events`; record kinds stay on the forge; one registry key flips back.
2. (E2) The board is one issue with a fixed set of comments edited in place, written by one publisher with the account's
   write queue; record kinds go to the PR they belong to.
3. (E3) Rotation is code: past a threshold the next board opens and config points to it.
4. Reads of the ref are windowed and incremental (a local mirror updated by fetch), so no reader pays for the log's length.
