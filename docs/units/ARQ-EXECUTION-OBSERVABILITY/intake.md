# ARQ-EXECUTION-OBSERVABILITY — intake

## Pedido

Daniel pediu a abertura deste follow-up (t3302u). Decisão literal da ARQ-SISTEMA em [plan.md, seção Escolha](../ARQ-SISTEMA/plan.md#escolha):

> R7 → A1: informa limites e incerteza sem modificar serviço ou interpretar snapshot antigo como falha atual. Follow-up: unidade proposta ARQ-EXECUTION-OBSERVABILITY, ainda não aberta, para correlação A2 após medir identidades disponíveis.

## Intenção

Explicar o percurso de uma mudança entre prontidão, execução e entrega, preservando o que cada observação permite concluir e o que continua desconhecido.

## Contexto

A ARQ-SISTEMA escolheu um remendo limitado para R7, deixando o conserto de classe para esta unidade. F10 e R7 exigiram conciliar ao menos 2 fontes de estado e eventos de entrega. No snapshot histórico de 01/11 às 22:25:11.687Z, readyz respondeu 200/ready=true, com 867 jobs queued, 0 leased e merges recentes. Esses números não medem PRs bloqueados nem indisponibilidade atual; service_status e control plane observam escopos diferentes. Fonte: [audit.md, F10; R7](../ARQ-SISTEMA/audit.md). As contagens pertencem à revisão auditada, não são novas medições desta abertura. O [plano](../ARQ-SISTEMA/plan.md) registra A2 como continuidade proposta, não como desenho já decidido pela pesquisa desta unidade.

## Regras

D-077 e D-081; [Padrão v8, intake e pesquisa](../../padrao/v8/intake-and-research.md). Pela regra de Daniel (t3302u), o requisito nasce da pesquisa desta unidade. Esta entrega abre intake e research; auditoria, plano e execução terão PRs próprias e produtos independentes. Não há autorização de troca de forja, alteração de produção ou desenho fechado nesta abertura.

Premises: none

## Problema real

As visões disponíveis não permitem explicar por si sós quem executará uma mudança; a medição de resolvido é a cobertura de percursos correlacionáveis pelas identidades efetivamente disponíveis, com lacunas declaradas, cujo denominador ainda depende do levantamento. A pesquisa fundamentará os requisitos; a auditoria medirá o universo e o plano escolherá alvos e provas, sem critérios de aceitação novos fixados aqui.

## Lacunas

Não sabemos quais identidades de head, job, lease, prova e transporte sobrevivem entre as fontes nem sua cobertura; depende da pesquisa e de leituras autorizadas pela unidade com engine-lane. Disponibilidade atual não foi medida aqui; ampliar acesso ou mudar semântica operacional depende de Daniel.
