# ARQ-ARCHITECTURE-VIEWS — intake

## Pedido

Daniel pediu a abertura deste follow-up (t3302u). Decisão literal da ARQ-SISTEMA em [plan.md, seção Escolha](../ARQ-SISTEMA/plan.md#escolha):

> R6 → A1: remove contradições conhecidas com custo limitado; automatizar toda afirmação agora competiria com R2. Follow-up: unidade proposta ARQ-ARCHITECTURE-VIEWS, ainda não aberta, para fonte de relações e recusa A2.

## Intenção

Permitir confiar nas relações descritas pelas vistas de arquitetura quando o engine muda, reduzindo reconciliação manual de documentos e implementação.

## Contexto

A ARQ-SISTEMA escolheu um remendo limitado para R6, deixando o conserto de classe para esta unidade. F9 e R6 encontraram dois leitores retirados ainda descritos em AGGREGATES e reconciliação de ao menos 3 documentos, 4 incluindo PORTS. Na base de abertura, AGGREGATES e PORTS já receberam a correção limitada prevista; a evidência histórica sustenta a recorrência possível, não uma declaração de que os mesmos erros persistem. Fonte: [audit.md, F9; R6](../ARQ-SISTEMA/audit.md). As contagens pertencem à revisão auditada, não são novas medições desta abertura. O [plano](../ARQ-SISTEMA/plan.md) registra A2 como continuidade proposta, não como desenho já decidido pela pesquisa desta unidade.

## Regras

D-077 e D-081; [Padrão v8, intake e pesquisa](../../padrao/v8/intake-and-research.md). Pela regra de Daniel (t3302u), o requisito nasce da pesquisa desta unidade. Esta entrega abre intake e research; auditoria, plano e execução terão PRs próprias e produtos independentes. Não há autorização de troca de forja, alteração de produção ou desenho fechado nesta abertura.

Premises: none

## Problema real

A validade das relações descritas depende de conferência manual; a medição de resolvido é a correspondência verificável entre relações descritas e fatos no universo de vistas explicitado, sem usar quantidade de documentos como fidelidade. A pesquisa fundamentará os requisitos; a auditoria medirá o universo e o plano escolherá alvos e provas, sem critérios de aceitação novos fixados aqui.

## Lacunas

Não sabemos quais relações admitem verificação automática nem qual fonte representa suas garantias sem confundir arquivo presente com comportamento; depende da pesquisa e do levantamento da unidade, de engine-lane para os leitores e de Daniel para os limites de escopo.
