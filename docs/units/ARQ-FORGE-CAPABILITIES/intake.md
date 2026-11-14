# ARQ-FORGE-CAPABILITIES — intake

## Pedido

Daniel pediu a abertura deste follow-up (t3302u). Decisão literal da ARQ-SISTEMA em [plan.md, seção Escolha](../ARQ-SISTEMA/plan.md#escolha):

> R3 → A1: a matriz orienta o desenho sem alterar seleção de forja ou fingir que nove métodos equivalem a 24 requisitos. Follow-up: unidade proposta ARQ-FORGE-CAPABILITIES, ainda não aberta, para A2 e tratamento das 13 exceções.

## Intenção

Tornar demonstrável a compatibilidade de um fluxo com a forja escolhida, sem redescobrir capacidades e exceções a cada troca.

## Contexto

A ARQ-SISTEMA escolheu um remendo limitado para R3, deixando o conserto de classe para esta unidade. F6 e R3 contaram 24 métodos públicos diretamente definidos em GitHubAdapter e 9 em OriginAdapter, mais 13 sites GitHub autorizados fora dos adaptadores em scripts/lib/adapters/engine-vendors.json. São superfícies diferentes, não 24 requisitos universais. ForgeEvents._operation detectava ausência na chamada. Fonte: [audit.md, F5–F6; R3](../ARQ-SISTEMA/audit.md). As contagens pertencem à revisão auditada, não são novas medições desta abertura. O [plano](../ARQ-SISTEMA/plan.md) registra A2 como continuidade proposta, não como desenho já decidido pela pesquisa desta unidade.

## Regras

D-077 e D-081; [Padrão v8, intake e pesquisa](../../padrao/v8/intake-and-research.md). Pela regra de Daniel (t3302u), o requisito nasce da pesquisa desta unidade. Esta entrega abre intake e research; auditoria, plano e execução terão PRs próprias e produtos independentes. Não há autorização de troca de forja, alteração de produção ou desenho fechado nesta abertura.

Premises: none

## Problema real

A seleção da forja não demonstra compatibilidade do fluxo; a medição de resolvido é a cobertura dos requisitos de capacidade identificados por fluxo e a situação das 13 exceções, distinguindo compatibilidade demonstrada de dependência ainda externa. A pesquisa fundamentará os requisitos; a auditoria medirá o universo e o plano escolherá alvos e provas, sem critérios de aceitação novos fixados aqui.

## Lacunas

Não sabemos os requisitos de todos os fluxos nem o destino justificável de cada exceção; dependem da pesquisa da unidade e dos consumidores mantidos por engine-lane. Uma mudança de seleção ou de fonte da verdade depende de decisão de Daniel e não está autorizada por esta abertura.
