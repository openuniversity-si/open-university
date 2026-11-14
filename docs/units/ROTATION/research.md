# ROTATION (CANALE3) — research

## Quem já resolveu
- Log rotation (logrotate, Kafka segments): past a size the writer opens the next segment; readers walk segments by a pointer
  or an index.
- GitHub's own advice for long issues: open a new one and link it ("continued in #N").
- Database snapshot plus log (Raft's log compaction): a new segment starts from a snapshot and the entries after it.

## Estado da arte
The writer rotates at a threshold below the hard limit, the new segment starts from a snapshot, and readers follow a pointer from
a fixed start.

## Encaixe em nós
- **Copy**: rotate below the limit; snapshot plus the changes after it; a pointer line.
- **Adapt**: the pointer is a marked comment on the old issue, so the fixed start (the registry default) stays valid.
- **Does not fit**: an external index (a service).

## Escada de ambição
1. (this unit) Rotation in the adapter, with the store carried and the pointer followed.
2. The registry default follows the newest issue (a PR after a rotation).
3. E7: the channel leaves GitHub (Daniel, 15:43 BRT).
