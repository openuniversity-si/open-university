# TRAIN-DEFINITIVE — intake

## Pedido
Daniel, 02/11/2026 15:58 BRT, as given:

> "Abra uma PR para resolvermos essa questão de forma DEFINITIVA. Trabalhe em cima do redesenho e das causas
> fundamentais, inclusive. A VM tem 10 segundos para realizar tudo - seja dar positivo e seguir, seja dar negativo e
> estar liberada para o próximo. Se necessário, faça com que os testes estejam rodando mais rápido de modo que o Gate
> rode todo nesses 10 segundos."

Read literally: every job the VM takes (gate or train) finishes in 10 s or less, start to finish; in either outcome the
runner and the lock are free for the next job; the gate as a whole fits in those 10 s.

## Intenção
Make the train an unattended service with a bounded lifetime for every job and every resource it owns. A negative
answer must leave the next job runnable just as a positive answer does.

## Contexto
PR #1086 continues the existing branch, targeting `mod/roadmap-integration`. The initial Claude session exhausted its
quota after implementing plan items 1–8. Codex resumed at `b6ece23206612695d45d544cd19be7797c07b7d8`; this is the same unit.
The audit records dead train locks, stale work, missing deployments and a silently rotated runner credential.
ORIGIN-FINISH (#1087) is concurrent; shared-file work is announced in the engine diary.

## Regras
No new PR, no force push, no secret values in output. Status belongs in the engine diary. Do not modify
`I-052b7eed.md`, `I-12caecdd.md` or #1066. The train is the only merger. VM or Worker-secret operations are delivered
as exact coordinator instructions, not executed by this session. Replace mechanisms outright, without compatibility paths.

## Problema real
Job lifetime, lock lifetime, queue lifetime, deployed code and credential consumers disagree. Resolved means all six
outcomes hold with measured evidence:

- (a) A finished, dead or restarted job leaves neither its lock nor its runner held.
- (b) Every VM job returns a definite answer within 10 seconds, enforced outside the job, including checks and reporting.
- (c) The real gate, including its tests, fits in 10 seconds; bypass and proof lookup do not establish this outcome.
- (d) A merged control-plane change deploys itself.
- (e) A rotated secret cannot silently break a holder.
- (f) Closed, superseded or dead work cannot accumulate into another stale backlog.

## Lacunas
This session cannot execute on the runner VM or provision Worker secrets. VM phase times must come from actual runner
results after coordinator rollout. The real gate's 10-second target remains a requirement even though the initial
plan deferred it to another lane; that deferral does not satisfy (c).
