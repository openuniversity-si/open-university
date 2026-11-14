# 15. Verificação do desenho de 10^0 e retrospectiva

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

> **Camada:** a verificação de todas as entregas; a da separação em camadas e a da fronteira de 12:19 estão nas seções 7
> e 8.

Confere se a segunda entrega fez o que o pedido de Daniel (03/11 23:38 BRT, com as correções e pedidos de 23:43 a 04/11
01:08) pediu, se os números batem entre os documentos e o que ainda falta medir.

## 1. O pedido, item por item

| Pedido | Onde está respondido | Resultado |
|---|---|---|
| A arquitetura de 10^0 implantável hoje: camadas, componentes, adaptadores, onde cada um roda e por quê, como recorte da de 10^9 com as mesmas portas | [10](10-arquitetura-10-0.md) §1 a §4 | **atendido** |
| A solução definitiva para gate, merge, fila e Origin, com o padrão do estado da arte e metas numéricas para 1 PR/s | [11](11-gate-merge-fila-origin.md) §1 a §9 | **atendido**; o mecanismo de pouso no Origin depende da medida E1 |
| A unidade de trabalho e as sessões no estado da arte, com orquestrador durável e eventos; o contrato da unidade | [12](12-unidade-e-sessoes.md) §2 a §6 | **atendido** |
| Estado e coordenação fora do repositório: qual banco, fila e armazém; o que fica em git e o que sai | [13](13-estado-e-coordenacao.md) §1 a §5 | **atendido** |
| Custo mensal por opção e o caminho gratuito; recursos pagos só como recomendação | [14](14-custos-e-migracao.md) §2 e §3 | **atendido**; nada foi criado |
| Plano de migração em passos pequenos com critério de pronto, e o que dá para fazer amanhã | [14](14-custos-e-migracao.md) §4 e §5 | **atendido** |
| Correção das 23:43: fornecedor livre, preferência por AWS e Google, Origin principal e GitHub pela mesma porta, o runner da VM pode sair | opções A1 a A4 em [10 §2](10-arquitetura-10-0.md#2-onde-cada-componente-roda); pouso por forge em [11 §3](11-gate-merge-fila-origin.md#3-como-fica-no-origin-e-no-github); a VM sai no passo 7 de [14 §4](14-custos-e-migracao.md#4-o-plano-de-migração) | **atendido** |
| Sugestão das 23:49: a caixa da AWS paga com crédito, e quanto crédito cada opção consome | a caixa EC2 em [10 §2](10-arquitetura-10-0.md#2-onde-cada-componente-roda) e [14 §2](14-custos-e-migracao.md#2-infraestrutura-e-gate-por-opção); quanto os US$ 1.100 duram em cada opção em [14 §6](14-custos-e-migracao.md#6-o-crédito-de-us-1100-quanto-dura) (dado da Torre de 04/11 00:26 BRT) | **atendido** |
| Correção das 00:35: enquanto o uso é pessoal, interno e não comercial, as sessões pelas assinaturas (Claude Code, Cursor, Codex) | [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau); [14 §3](14-custos-e-migracao.md#3-agentes); o passo 6 de [14 §4](14-custos-e-migracao.md#4-o-plano-de-migração) | **atendido**, com o registro dos termos e os quatro gatilhos de troca |
| Correção das 00:38: a forma definitiva desde o primeiro dia, sem troca depois, e o custo mensal da A1 completa no degrau de hoje contra o crédito | [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia); [14 §2, §4 e §6](14-custos-e-migracao.md#6-o-crédito-de-us-1100-quanto-dura) | **atendido**: só crescem números até 1 PR/s; o custo foi refeito às 01:06 (linha abaixo) |
| Pedido das 01:01: entrega instantânea (verificação e merge em até 1 s) no regime de baixa vazão, que será o normal por muito tempo | [11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s): lote de uma sem janela, prova do head no push com veredito por alvo, orçamento por etapa até ~0,8 s; [10 §4](10-arquitetura-10-0.md#4-o-caminho-de-uma-unidade-de-ponta-a-ponta) | **atendido** para "pronta → mergeada"; rodar os testes fica acima de 1 s e vai para antes da pronta, e o forge depende da medida E4 (dito em [11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s)) |
| Pergunta das 00:43 e correção das 00:44: o modelo das entidades afeta tabelas, bancos e eventos? O modelo de hoje é falho e tem de ser refinado | [16](16-modelo-de-dominio.md): o modelo de hoje (§2), onde falha (§3, dez falhas com evidência), o estado da arte (§4), o refinado nos níveis do METODO (§5), o mapa (§6) e o que deriva dele (§7) | **atendido**: afeta tabelas, eventos e workflows, não os componentes; o núcleo das tabelas rodou no PostgreSQL 18.6 |
| Perguntas das 01:56 e 01:57: o mapeamento dos eventos dentro de uma PR e das etapas de uma unidade de trabalho (auditoria, planejamento, execução item a item pelo caminho crítico dos commits) | [17](17-ciclo-do-processo.md): as etapas com entrada, produto, fim e executor (§2), o plano como grafo com caminho crítico (§3), as máquinas de estado e os eventos com emissor e causa do push ao merge (§4), o que muda no 16 (§5), o que falha hoje com evidência e o estado da arte (§6) | **atendido**; as tabelas novas rodaram no PostgreSQL 18.6 |
| Decisão das 01:39: A1 a 1 PR/min, runner sempre ligado, teto de US$ 60/mês no AWS Budgets | [14 §5](14-custos-e-migracao.md#5-o-que-dá-para-fazer-amanhã) | **registrada**; o orçamento existe (Torre, 01:44) e precisa excluir créditos para alertar enquanto houver crédito [C54]; a implantação segue na PR de infraestrutura |
| Correções das 01:06 e 01:08: dimensionar para 1 PR/min com os serviços mais baratos da AWS, custo contra o crédito, e o que muda (só números) para 1 PR/s | [10 §2 e §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia); [14 §2 e §6](14-custos-e-migracao.md#6-o-crédito-de-us-1100-quanto-dura) | **atendido**: ~US$ 53 por mês, ~21 meses de crédito; a tabela de [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia) dá cada componente a 1 PR/min e a 1 PR/s |

## 2. Cada classe de problema e o que a fecha

| Classe ([09 §3](09-avaliacao-10-0.md#3-o-que-trava-hoje-por-classe)) | Mecanismo | Critério de pronto |
|---|---|---|
| K1 dois escritores no mesmo branch | um escritor por branch; o lote no ramo da fila; a base só pela fila ([11 §2](11-gate-merge-fila-origin.md#2-o-desenho)) | zero recusas "non-fast-forward" em 48 h (passo 0.1) |
| K2 credencial e rede do forge | app do Origin com JWT para a fábrica; credencial de sessão injetada | as chamadas da fila com o app (passo 0.5) |
| K3 estado em git e no plano gratuito | Postgres gerenciado e S3; git só para o estado desejado ([13](13-estado-e-coordenacao.md)) | uma semana sem escrita no log em git-ref nem na fila em arquivo (passo 3) |
| K4 sessões que param | workflow durável por unidade, lease, timers de prazo e de reset de cota ([12](12-unidade-e-sessoes.md)) | 100 unidades sem ação manual, um reset de cota retomado sozinho (passo 6) |
| K5 computação do gate fixa | runner quente e runners de rajada, veredito por alvo num cache que só o runner escreve, a VM sai | prova de um head p50 ≤ 20 s em 100 provas (passo 4) |
| K6 fornecedor sem a capacidade | matriz de capacidades no corretor de sessões | nenhuma unidade despachada a quem não tem a capacidade exigida |
| K7 merge serial | lote de uma sem espera quando nada espera; lote verificado uma vez quando há fila; pouso na ordem do lote com prova de árvore | 500 PRs pousadas, vermelho na fila ≤ 2 %, "pronta → mergeada" p50 ≤ 1 s a 1 PR/min (passo 5) |

## 3. Os números entre os documentos

| Número | Onde nasce | Onde é usado | Confere |
|---|---|---|---|
| ~27 pontos de API por PR | [11 §3](11-gate-merge-fila-origin.md#3-como-fica-no-origin-e-no-github) | 1.620 pontos/min a 1 PR/s = 27 % do JWT de app (R0-10 pede ≤ 50 %); o Origin aguenta ~1,8 PR/s a 50 % ([10 §1](10-arquitetura-10-0.md#1-as-camadas)) | sim |
| 20 a 40 vCPU·s de tier 2 por PR | [11 §4](11-gate-merge-fila-origin.md#4-as-contas) | o gate de [14 §2](14-custos-e-migracao.md#2-infraestrutura-e-gate-por-opção) e R0-05 | sim |
| ~900 sessões simultâneas a 1 PR/s com A = 1 | [09 §2](09-avaliacao-10-0.md#2-o-que-1-prs-significa-em-números) (600 a 1.200) e [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau) | o tempo de sandbox de [14 §3](14-custos-e-migracao.md#3-agentes) | sim |
| ~15 passos de workflow por PR | carga de referência | 15 passos/s a 1 PR/s contra ~1.000/s por vCPU de Postgres no DBOS [C44] | sim, com folga de ~60× |
| ~US$ 0,14 de tokens por PR na mistura de modelos | [14 §3](14-custos-e-migracao.md#3-agentes) | o contrato do planejador de [06](06-contrato-planejador.md) (PC-14 ≤ US$ 0,03 em 1/s) | **não**: a 1 PR/s com A = 1 o custo por PR fica ~5 vezes acima de PC-14; só fecha com A ≥ 10 ou mais Haiku |
| o forge sai do caminho crítico em 1/s | [05 §6](05-orcamento-e-degraus.md#6-o-que-muda-de-um-degrau-para-o-outro) (com ~60 pontos por PR) | revisto em [10 §1](10-arquitetura-10-0.md#1-as-camadas): com ~27 pontos o Origin fica até ~1,8 PR/s | corrigido |
| ~0,8 s de "pronta" a "mergeada" | [11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s): merge-tree e digests medidos (~5 ms cada [M]), o resto estimado | a meta p50 ≤ 1 s de [11 §6](11-gate-merge-fila-origin.md#6-metas-numéricas) e o passo 5 de [14 §4](14-custos-e-migracao.md#4-o-plano-de-migração) | sim, se o merge do Origin couber em ~0,6 s (E4) |
| 240 a 480 vCPU·h de tier 2 por mês a 1 PR/min | 20 a 40 vCPU·s por PR × 43.200 PRs | um runner quente de 2 vCPU a 70 % dá ~1.000 vCPU·h ([14 §6](14-custos-e-migracao.md#6-o-crédito-de-us-1100-quanto-dura)) | sim, com folga de ~2× |
| ~US$ 53 por mês a 1 PR/min | [14 §6](14-custos-e-migracao.md#6-o-crédito-de-us-1100-quanto-dura) | [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia), o README e o teto de US$ 60 de [14 §5](14-custos-e-migracao.md#5-o-que-dá-para-fazer-amanhã) | sim |

A linha em "não" é a mesma conclusão da primeira entrega dita de outro jeito: 1 PR/s com IA escrevendo cada PR passa
do orçamento de tokens que o contrato do planejador fixa para esse degrau. A infraestrutura deste documento resolve gate,
merge, fila, Origin e sessões; o custo da IA é a amplificação (A ≥ 10 em 1/s, [06 §4](06-contrato-planejador.md#4-os-requisitos-e-as-metas)).

**Diagramas e referências.** Todos os diagramas mermaid da pasta passam no parser do mermaid 11.4.1; todo identificador
citado existe em [referencias.md](referencias.md), conferido por script.

## 4. O que ainda falta medir

| Medida | Por que importa | Onde entra |
|---|---|---|
| E1: merges por minuto que o Origin aceita pela API no mesmo repositório | decide o pouso PR a PR ou por push com fechamento ([11 §3](11-gate-merge-fila-origin.md#3-como-fica-no-origin-e-no-github)) | passo 0.3 |
| E2: o orçamento de git do Origin (cabeçalhos do recurso `git`) | ~4 pushes por PR das sessões a 1 PR/s | passo 0.3 |
| E3: se o merge de uma pilha serve de pouso em lote | uma chamada para N PRs | passo 0.3 |
| se o crédito Activate cobre modelos de terceiros no Bedrock | decide se o crédito pode pagar agentes (dias, não meses) | os termos do crédito no console |
| preços spot do Fargate e do EC2 | vieram de guias de terceiros [C46, C48] | o primeiro mês de uso |
| a cobrança do AgentCore (tempo ativo de CPU ou de parede) | muda o custo de sandbox em até ~7× | o passo 6 |
| E4: a latência de uma chamada de merge pela API do Origin (p50 e p99) | decide se a entrega cabe em 1 s ([11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s)) | passo 0.3 |
| E5: a latência das entregas de webhook do Origin | o sinal de push e o de pronta | passo 0.3 |
| E6: a partida a frio de uma tarefa Fargate com a imagem do toolchain | o custo de não ter runner quente | passo 4 |
| a fração de provas que terminam antes da pronta | a entrega em 1 s de fato, meta ≥ 90 % | passo 5 |
| os webhooks da API v1 da Cursor | vistos só por trecho [A37] | o adaptador da Cursor no passo 6 |

## 5. Retrospectiva

**O que aconteceu.** A #263 já tinha os oito itens do plano preenchidos, o limite do `commit-check`; a segunda entrega
foi numa PR nova, empilhada sobre ela (#264), como o Origin faz pilhas. Na retomada da sessão o remote `origin` voltou a
apontar para o GitHub arquivado e foi corrigido antes de qualquer push. Três pesquisas rodaram em paralelo (filas de
merge, fornecedores de agentes, preços de nuvem), com a maioria dos sites primários bloqueada pelo egress; as fontes
oficiais foram lidas nos repositórios do GitHub, na API de preços da AWS e nas páginas de preço do Google. O hook de
parada pediu commit do que estava em andamento; os rascunhos que ainda dependiam da pesquisa ficaram fora da árvore
até ficarem completos. Com os preços na mão, a recomendação mudou: de AWS sem servidor para AWS com Postgres e DBOS,
mais barata e igual ao motor de hoje.

**O que se aprendeu.**

1. No Origin, só o merge pela API marca a PR como mergeada; a que chega por push fica fechada (#253, #233).
2. Os limites dos planos de assinatura da Anthropic assumem uso individual comum, e produtos devem usar chave de API ou
   provedor de nuvem [A31]. Daniel decidiu (04/11 00:35 BRT) seguir com as assinaturas enquanto o uso é pessoal,
   interno e não comercial; a troca para o adaptador próprio tem gatilhos escritos ([12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau)).
3. A infraestrutura que resolve os problemas de Daniel, com todos os componentes desde o primeiro dia, custa ~US$ 53
   por mês a 1 PR/min e ~US$ 550–1.500 a 1 PR/s; o custo de 1 PR/s está nos agentes, de ~US$ 40 mil a ~US$ 420 mil por
   mês conforme a amplificação.
4. A entrega em 1 s não pede verificação mais rápida, pede verificação mais cedo: a prova roda no push, em paralelo com o
   tier 1 da sessão, e a chave do veredito passa a ser por alvo, sem o sha da base, para a base que anda não invalidar
   o que não mudou.
5. O METODO já tinha a hierarquia que faltava ao motor: "uma PR é um conjunto de operações" faz do processo a unidade
   de trabalho e do evento o registro da operação. O que faltava era guardar os níveis como dado, com dono, estado e
   identidade alocada pelo banco ([16](16-modelo-de-dominio.md)).
6. O orquestrador durável não precisa de servidor próprio: o DBOS grava o workflow no mesmo Postgres, e as funções
   duráveis do Lambda existem desde dez/2025.

**O que muda no padrão** (propostas, nenhuma aplicada por esta PR):

1. O motor mede os gatilhos de troca de [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau) (uso, volume em
   `esperando_cota`, aviso do fornecedor, capacidade) e mantém o adaptador próprio com Bedrock testado em sombra.
2. `scripts/flow-metrics` mede os tokens por PR mergeada por modelo, porque é a linha que decide o custo.
3. No [RETOMAR](../RETOMAR.md), conferir `git remote -v` depois de toda retomada de sessão, porque o ambiente pode
   devolver o `origin` ao GitHub arquivado.

## 6. A verificação do passo zero

O pedido de Daniel de 04/11 10:44 e 10:46, item por item ([18](18-planta-geral.md) a [21](21-revisao-geral.md)):

| Pedido | Onde está respondido | Resultado |
|---|---|---|
| Partir da intenção de origem, não do que existe; o que existe é insumo e evidência | [18 §1](18-planta-geral.md#1-a-intenção-como-ponto-de-partida): as classes de parada derivadas da intenção; [19 §1](19-direcao-ideal.md#1-o-que-falha-na-direção-de-hoje) e [20](20-sistema-de-aprendizado.md) usam o que existe só como evidência | **atendido** |
| O estado ideal de todo o modelo, com por que existe, identidade, estados, relações, quem cria, quem consome e o que se mede de cada entidade | o catálogo de [21 §3](21-revisao-geral.md#3-o-catálogo-das-entidades-do-modelo-ideal), com o detalhe em [19](19-direcao-ideal.md) e [20](20-sistema-de-aprendizado.md) | **atendido** |
| A direção, inclusive eliminar níveis | [19 §2](19-direcao-ideal.md#2-os-níveis-quais-ficam-e-quais-saem): o portfólio e a fase saem; o programa vira objetivo e o projeto, aposta | **atendido**; a troca da métrica da semente é proposta a Daniel |
| O planejador, o padrão e o ciclo de melhoria dele | [19 §4 e §5](19-direcao-ideal.md#4-o-planejador); [20](20-sistema-de-aprendizado.md) | **atendido** |
| A retrospectiva como sistema de aprendizado autônomo | [20 §1](20-sistema-de-aprendizado.md#1-o-que-existe-hoje) (o que existe) e [§3 a §7](20-sistema-de-aprendizado.md#3-o-ciclo-da-evidência-à-mudança-medida) (o ciclo) | **atendido** |
| A planta: sistema, subsistemas, conexões, contratos | [18 §3 a §7](18-planta-geral.md#4-os-três-sistemas-e-as-conexões) | **atendido** |
| Uma pesquisa de como os melhores do mundo fazem | [18 §2](18-planta-geral.md#2-como-os-melhores-desenham-e-documentam-sistemas) (plantas e decisões), [19 §8](19-direcao-ideal.md#8-o-que-o-estado-da-arte-ensina-à-direção) (direção), [20 §2](20-sistema-de-aprendizado.md#2-o-que-o-estado-da-arte-ensina) (aprendizado) e [21 §7](21-revisao-geral.md#7-a-padronização-na-aws) (AWS), com as fontes nos grupos B, L e N de [referencias](referencias.md) | **atendido**; a maior parte dos sites estava bloqueada, e cada fonte diz se foi lida na página ou só no trecho |
| Estruturas, comandos, instruções e prompts, e o que padronizar na AWS | [21 §2](21-revisao-geral.md#2-as-estruturas), [§5](21-revisao-geral.md#5-os-comandos), [§6](21-revisao-geral.md#6-as-instruções-e-os-prompts) e [§7](21-revisao-geral.md#7-a-padronização-na-aws) | **atendido**; a estrutura de contas da AWS fica para Daniel decidir quando o uso deixar de ser pessoal |
| O que o modelo considera e não deveria, e o que não considera e deveria | [21 §8](21-revisao-geral.md#8-o-que-o-modelo-considera-e-não-deveria-e-o-que-não-considera-e-deveria) | **atendido** |
| Testar contra a escala, 1 PR/min e 1 PR/s | [21 §9](21-revisao-geral.md#9-o-teste-de-escala), [20 §5](20-sistema-de-aprendizado.md#5-o-que-dá-para-provar-a-1-prmin-e-a-1-prs) e [19 §4](19-direcao-ideal.md#4-o-planejador) | **atendido** |
| Antes de qualquer DDL na #265 | só documentos; o esquema revisto rodou no PostgreSQL 18.6 só como conferência | **atendido** |

**O que a auditoria achou** (04/11, sobre os arquivos do repositório e os 522 eventos do log de 03/11 17:15 a 04/11
12:06 UTC): 66 comandos, com sobreposições, apelidos e quatro que não fazem o que o nome diz
([21 §5](21-revisao-geral.md#5-os-comandos)); sete regras escritas que o código desmente, nove pares de regras que se
contradizem e três envelhecidas ([21 §6](21-revisao-geral.md#6-as-instruções-e-os-prompts)); 16 lições, nenhuma
aplicada, e nenhum efeito de mudança medido ([20 §1](20-sistema-de-aprendizado.md#1-o-que-existe-hoje)); cinco
definições de programa e três sentidos para `F<n>` ([19 §1](19-direcao-ideal.md#1-o-que-falha-na-direção-de-hoje)). As
contagens de arquivo valem para a base desta PR; as de evento, para o recorte do log lido.

**As tabelas revistas** (os documentos 16 e 17 na forma do passo zero: objetivo e aposta no lugar de programa, projeto e
fase; a versão do padrão em cada tentativa; início e fim de etapas e itens) rodaram juntas no PostgreSQL 18.6 do
toolchain: 20 tabelas, e as regras de um pai só e da versão do padrão obrigatória recusaram o que deviam [M].

## 7. A verificação da separação em três camadas

O pedido da Torre de 04/11, com a decisão de Daniel de 11:37 e 11:39 e o registro de 11:45, item por item
([22](22-tres-camadas.md)):

| Pedido | Onde está respondido | Resultado |
|---|---|---|
| Separar nos documentos 09 a 21 o núcleo técnico agnóstico do resto | [22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça), documento por documento, e a marca de camada no topo de cada um | **atendido** |
| O critério (o núcleo não sabe por que o trabalho existe) e o teste de aceite (dois programas, a mesma infraestrutura, nenhuma linha mudada) | [22 §1](22-tres-camadas.md#1-a-fronteira-decisão-de-daniel-1219) e [§6](22-tres-camadas.md#6-o-teste-de-aceite) | **atendido**, com duas cláusulas a mais no critério: nem como o método decompõe o trabalho, nem de quem é a conta |
| A leitura da Torre sobre o que fica e o que sai | [22 §1, §3 e §4](22-tres-camadas.md#4-o-contrato-entre-a-infraestrutura-e-a-gestão) | **atendido**, com quatro acréscimos (abaixo) |
| Os ganchos genéricos: o metadado opaco e as etapas como lista configurável | [22 §4](22-tres-camadas.md#4-o-contrato-entre-a-infraestrutura-e-a-gestão) e [§5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura) | **atendido**: `annotations` e o modelo com a lista de passos, validada por gatilho |
| Enxugar a #265 para só o núcleo, sem tabelas de direção ou aprendizado | [22 §8](22-tres-camadas.md#8-o-que-muda-na-265) | **atendido**: a #265 não tinha DDL nem tabela de gestão; ganha a D-304, o teste que a prova e o bootstrap sem região fixa |
| As fases 2 e 3 no README, com a pesquisa da #266 como insumo, sem implementar | o README, "Três camadas, em três fases", e [22 §9](22-tres-camadas.md#9-as-fases-2-e-3) | **atendido** |
| A unidade da infraestrutura é a execução de trabalho, não a sessão de IA, e um script roda sem abrir sessão de IA (12:05 e 12:08) | [22 §1](22-tres-camadas.md#1-a-fronteira-decisão-de-daniel-1219), [§4](22-tres-camadas.md#4-o-contrato-entre-a-infraestrutura-e-a-gestão), [§5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura) e [§6](22-tres-camadas.md#6-o-teste-de-aceite) | **atendido**: o executor é um tipo plugado (script ou contêiner, sessão de IA, pessoa); o programa diz quais servem, e o núcleo registra qual rodou, o que mediu e quanto custou; a D-305 o prova na #265 |
| Não amarrar a infraestrutura a uma conta, a um programa ou a um método (11:45) | [22 §7](22-tres-camadas.md#7-sem-amarrar-a-uma-conta-a-um-programa-ou-a-um-método) | **atendido** no que a fase 1 precisa; o instalador, a cobrança e o isolamento por programa ficam para quando um dos dois modos chegar |

**Os quatro acréscimos ao corte da Torre**, julgados pela sessão:

1. **As checagens de política saem das etapas fixas do gate.** A checagem de estrutura e a de metadados da PR são o
   método (o plano de 1 a 8 itens, os trailers, a revisão de encaixe, as premissas) e hoje rodam como etapas `always`; um
   segundo programa seria recusado por elas. No núcleo, elas são checagens que o repositório registra. Mudar o gate pede
   uma decisão aprovada, e a D-304 é ela.
2. **`labels` além das `annotations`.** Só o metadado opaco não deixa a gestão medir por objetivo ou por aposta; os
   rótulos selecionáveis, como no Kubernetes e no Temporal [K7, K8], deixam, sem o núcleo saber o que significam.
3. **A entrega em sombra** (`delivery = none`): o aprendizado da fase 2 reexecuta casos passados com uma versão candidata
   do padrão, e o núcleo precisa saber verificar sem integrar.
4. **O programa em toda linha desde já**, embora o modo com vários clientes não seja para agora: pôr a coluna depois é
   migrar todas as tabelas e consultas; agora é uma coluna e uma linha, a do nosso programa. Cadastro, cobrança e políticas
   de linha por programa ficam de fora.

**Na restrição de 12:05 e 12:08**, a sessão seguiu a leitura da Torre (a execução como unidade, o executor por
adaptador, nenhuma escolha de executor pelo conteúdo) e acrescentou três coisas: o tipo do brief, que casa o trabalho com
os executores que o recebem; o executor privado de um programa, que é a chave de quem a trouxe (11:45); e o uso por
medidor, em que os tokens são um medidor entre outros, como os segundos de CPU e os minutos de uma pessoa.

**As tabelas do núcleo** rodaram no PostgreSQL 18.6 do toolchain com dois programas de métodos diferentes, um de cinco
passos e outro de dois, e executores de três tipos: o mesmo trabalho por um script, sem sessão de IA, e por uma sessão de
IA, nas mesmas tabelas; uma pessoa executando o outro programa; 19 tabelas em seis esquemas, nenhum nome de gestão,
liderança ou tipo de executor no catálogo; recusados o executor que a unidade não aceita, o brief de tipo errado, o
executor privado de outro programa, o passo de um método no outro, a dependência entre programas e o evento com o
prefixo de outro programa; e as mesmas visões medindo tudo [M].

## 8. A verificação da fronteira de 12:19

O pedido de Daniel, consolidado pela Torre e aprovado às 12:19: passar toda a arquitetura pela fronteira entre
infraestrutura e gestão, peça por peça ([22](22-tres-camadas.md)).

| Pedido | Onde está respondido | Resultado |
|---|---|---|
| Três sistemas, só três | [22 §1](22-tres-camadas.md#1-a-fronteira-decisão-de-daniel-1219) e a planta de [18 §4](18-planta-geral.md#4-os-três-sistemas-e-as-conexões) | **atendido** |
| A infraestrutura conhece só trabalho: o trabalho, o executor, a saída, o registro, o acesso e as propriedades físicas | [22 §1, §4 e §5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura) | **atendido**: 10 tabelas em `work` e `log` |
| O que a infraestrutura não conhece, sem campo livre de contexto | o inventário de [22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça) e o teste de vocabulário de [§6](22-tres-camadas.md#6-o-teste-de-aceite) | **atendido** |
| Mecanismo e decisão | o limite de [22 §5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura); o orçamento da AWS no inventário | **atendido** |
| Os três testes e o teste de aceite | [22 §1](22-tres-camadas.md#1-a-fronteira-decisão-de-daniel-1219) e [§6](22-tres-camadas.md#6-o-teste-de-aceite) | **atendido**, executado no PostgreSQL 18.6 |
| Revisar toda a arquitetura, não acrescentar uma seção | [22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça), a planta de [18](18-planta-geral.md) refeita, o veredito no topo de cada documento de 09 a 21 e as correções no 10, no 16, no 17 e no 21 | **atendido** |
| O DDL da #265 | [22 §8](22-tres-camadas.md#8-o-que-muda-na-265) | **atendido**: a #265 não tinha DDL; a D-306 fixa `work` e `log` como os esquemas da infraestrutura e amplia o vocabulário recusado |
| A infraestrutura adaptável a parâmetros, nunca o parâmetro tirado (Daniel, 12:40) | [22 §1](22-tres-camadas.md#1-a-fronteira-decisão-de-daniel-1219), [§3](22-tres-camadas.md#3-o-inventário-peça-por-peça) e [§5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura) | **atendido**: a ordenação por fila e política, a retentativa, as dependências, o roteamento entre executores aceitos, a retomada de uma espera e o preço por medidor viram mecanismos com valores de fora; o padrão é um valor |
| A PR não se limita por burocracia de planejamento (Daniel, 12:37) | [17 §3](17-ciclo-do-processo.md#3-o-plano-de-commits-como-dado), [21 §6](21-revisao-geral.md#6-as-instruções-e-os-prompts) e [22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça) | **atendido** no desenho: o plano não tem teto, e esta PR segue com um nono item; a trava de hoje só avisa, e o que muda nela está em 21 §6 |

**O que a fronteira tirou, o que voltou como mecanismo e o que mudou de nome.** Tirados por serem contexto da gestão: os
`labels` e as `annotations`, o modelo com a lista de passos, a chave do programa, a espera com motivo, as visões de
métrica, o custo em colunas e os eventos do programa no registro. Na primeira passada, a sessão tinha tirado também a
prioridade, a retentativa, as dependências e a escolha entre executores; a correção de Daniel de 12:40 ("uma coisa é ser
adaptável a diferentes parâmetros, outra coisa é você simplesmente tirar o parâmetro") os trouxe de volta como mecanismos
parametrizáveis: a ordenação por fila e política, a retentativa com tentativas, espera e condições, as dependências, o
roteamento por seletor e capacidade, a retomada de uma espera e o preço por medidor, cada um com o padrão como valor. Com
outro nome, o que é físico: o programa virou o tenant; o veredito por alvo, o cache de resultado; o pouso, a exclusão
mútua por ramo e o executor `forge`.

**As tabelas da infraestrutura** rodaram no PostgreSQL 18.6 do toolchain: dois modelos de gestão (um com metas nas tabelas
dele, outro sem tabela nenhuma); o mesmo trabalho por script e por sessão de IA; a mesma função de fila escolhendo pelo
`rank`, pela ordem de chegada e pelo prazo, conforme a política de cada fila; o roteamento pulando a sessão de IA sem vaga;
a retentativa com espera de 10 s e de 20 s, o padrão de uma tentativa, o erro não retentável e o redespacho do executor que
sumiu; o pouso esperando as checagens; o limite em dinheiro pelo preço do token; a saída reaproveitada do cache; e
recusados o executor privado de outro tenant, o trabalho sem executor nem seletor, o trabalho além de um limite de recusa,
dois pousos ao mesmo tempo no mesmo ramo, um evento de gestão no registro e a mesma chave de idempotência duas vezes; 13
tabelas, nenhum nome proibido [M].


## 9. A verificação da arquitetura-alvo e do plano (Daniel, 12:56 e 12:57)

| Pedido | Onde está respondido | Resultado |
|---|---|---|
| Um documento único da arquitetura-alvo da fase 1, consolidando 09 a 22 sob a fronteira, sem contradições | [ARQUITETURA-ALVO](ARQUITETURA-ALVO.md), com o DDL e o teste como [anexos](anexos/infra-v1.sql) | **atendido**: ela absorve os números, os custos e as escolhas de serviço de 09 a 14 na forma da fronteira, e vale sobre qualquer outro documento |
| Os demais documentos como referência e histórico | o selo no topo de 00 a 22 e a [tabela de referência](ARQUITETURA-ALVO.md#12-os-documentos-de-referência) | **atendido** |
| As dependências entre as PRs abertas e a ordem de merge | [PLANO §0](PLANO-DE-IMPLEMENTACAO.md#0-as-prs-abertas-dependências-e-ordem-de-merge) | **atendido**: um conflito só, no registro de decisões, entre a #265 e a #268; a ordem proposta é a #268, a pilha de documentos pelo topo e a #265 |
| O plano de implementação em projetos, fases e PRs, com critério de pronto e dependências, a partir de `work` e `log` | [PLANO §1 a §9](PLANO-DE-IMPLEMENTACAO.md#1-os-projetos) | **atendido**: sete projetos; o esquema (P2 F1) e as regras do gate como configuração (P5 F1) começam já, sem depender da AWS |
| O gate e o trem continuam, com os mecanismos na infraestrutura e as regras de hoje como configuração padrão da nossa gestão | [ARQUITETURA-ALVO §7](ARQUITETURA-ALVO.md#7-o-gate-e-o-trem-continuam) e o projeto P5 do plano | **atendido**: cada regra de hoje tem a sua linha, com o mecanismo e a configuração padrão |
| A métrica-norte e a gestão de hoje como primeiro programa | — | **adiadas** por Daniel (12:53); nada aqui as decide |
| A pessoa como executor, sem implementar agora (Daniel, 13:18) | [PLANO §5](PLANO-DE-IMPLEMENTACAO.md#5-p4-os-executores) e [ARQUITETURA-ALVO §6](ARQUITETURA-ALVO.md#6-os-executores-e-os-adaptadores) | **atendido**: a fase P4 F4 saiu; fica dormente, com o requisito de caber depois sem migração, que o esquema já cumpre |
| O alvo de agora, 1 PR/min, com o P7 dormente (leitura da Torre) | o topo do [plano](PLANO-DE-IMPLEMENTACAO.md) e [§8](PLANO-DE-IMPLEMENTACAO.md#8-p7-a-escala-até-1-prs-dormente) | **atendido**: P1 a P6 são a fase 1, 14 PRs novas; o P7 espera o gatilho medido |
