# CONTROL-CHANNEL (CANALE7) — research

## Quem já resolveu
- Cloudflare Durable Objects as a single-writer log (the Durable Objects docs: storage per key, list by prefix, one object per
  name): exactly-once ordering without a lock service.
- Event stores behind an HTTP append and a paged read by sequence (EventStoreDB's HTTP API, Kafka REST proxy): append returns the
  sequence; a reader asks from a sequence.
- Ports and adapters (Cockburn): the caller sees one port; the provider is chosen by configuration.

## Estado da arte
An append-only log with a monotonic sequence, paged reads from a sequence, bounded retention, behind a token; clients choose the
store by configuration.

## Encaixe em nós
- **Copy**: sequence per record, read from a sequence, retention by count.
- **Adapt**: one Durable Object we already run; each record its own storage key (`ev:<sequence>`), so the dump stays small.
- **Does not fit**: a new database or queue service (a credential and a deploy we do not have).

## Escada de ambição
1. (this unit) The route, the adapter, the key, the acceptance test; GitHub remains for the code.
2. (CANALE8) One forge port of six operations, Origin as the second adapter.
