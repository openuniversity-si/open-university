# ARQ-EXECUTION-OBSERVABILITY — research

## Quem já resolveu

- [OpenTelemetry, propagação de contexto](https://opentelemetry.io/docs/concepts/context-propagation/): transporta contexto entre serviços para correlacionar sinais de uma execução.
- [Google SRE, Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/): distingue observação interna e externa, com foco em sintomas e causas; saúde parcial não substitui resultado observado.
- [Kubernetes, probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/): separa liveness, readiness e startup por perguntas operacionais diferentes; uma probe não certifica entrega de uma mudança.

## Estado da arte

A correlação distribuída usa contexto propagado para ligar etapas e sinais; sua utilidade depende de continuidade de identidade e instrumentação nas fronteiras. Probes respondem a perguntas locais delimitadas. Observação externa acrescenta resultado percebido e não se deduz de um processo saudável. Em conjunto, essas referências sustentam distinguir saúde, execução e efeito, preservando ausência de evidência como desconhecido. Adotar tracing não reconstrói automaticamente identidade ausente no histórico nem prova que um executor assumirá um trabalho futuro.

## Encaixe em nós

O [intake](intake.md) parte de [F10/R7](../ARQ-SISTEMA/audit.md): ao menos 2 fontes de estado e eventos de entrega precisavam ser conciliados; o snapshot tinha readyz verde, 867 jobs queued, 0 leased e merges recentes. É exposição histórica de escopos diferentes, não diagnóstico atual ou contagem de mudanças bloqueadas.

É aproveitável a separação de perguntas das probes e do SRE; é adaptável a propagação de contexto às identidades que existirem no engine. Instalar OpenTelemetry ou exigir um trace por mudança agora anteciparia o desenho sem medir head, job, lease, prova e transporte. A pesquisa sugere que continuidade de identidade e significado de cada estado precisam ser conhecidos para que correlação explique algo. Ausência local, heartbeat antigo e entrega recente continuam evidências distintas.

## Escada de ambição

O primeiro degrau útil é explicitar o que cada fonte já permite afirmar e onde o percurso permanece desconhecido. A evolução passa por medir identidades disponíveis e sua continuidade entre fontes; só então a correlação A2 herdada pode ganhar alcance demonstrável. Uma visão ponta a ponta é ambição posterior, dependente de cobertura e custo. Auditoria e plano decidirão requisitos e intervenção, sem alterar readyz, transporte, armazenamento ou semântica de disponibilidade nesta abertura.
