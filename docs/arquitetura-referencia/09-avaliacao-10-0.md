# 09. Avaliação e análise para 1 PR/s (10^0)

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

> **Na fronteira de 12:19** ([22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça)): os números e as classes do que
> trava são evidência para os três sistemas. Dos requisitos de §4, são da infraestrutura o estado fora do repositório
> (R0-02), um escritor por ramo (R0-03), os eventos por push (R0-06), o orquestrador durável (R0-07), os executores
> pela mesma porta (R0-08), o forge (R0-09), nenhuma máquina de estimação (R0-11) e a segurança (R0-14); são da
> gestão, sobre o registro e os mecanismos da infraestrutura, as metas de vazão, do gate e da cota (R0-01, R0-05,
> R0-10), a fila de merge como política (R0-04), a observabilidade como painel e métrica (R0-12) e o custo medido
> (R0-13).

Segunda entrega do projeto ARQ-REF. A primeira ([00](00-avaliacao.md) a [08](08-verificacao.md)) desenhou a fábrica para
10^9 PRs/s. Esta recorta, da mesma arquitetura e com as mesmas portas, o que dá para implantar hoje para **1 PR/s
mergeada**, e responde aos problemas que o motor tem agora com gate, merge, fila, Origin, sessões e estado. Marcação
[M]/[F]/[I]/[E] como em [00](00-avaliacao.md).

**O dimensionamento de agora é 1 PR/min** (Daniel, 04/11 01:06): é o regime normal por muito tempo, com entrega
instantânea da PR pronta. Os números de 1 PR/s desta página são o teto que o mesmo desenho alcança só mudando números
([10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia)).

## 1. O pedido

Daniel, 03/11/2026 23:38 BRT (voz, resumido só no tamanho): o foco agora é 1 PR por segundo, não 10^9. Dada a pesquisa
e os fornecedores atuais, qual é a melhor arquitetura para 1 PR/s: as camadas, os componentes, o que fazer hoje para
melhorar de forma significativa. Resolver de forma definitiva os problemas de gate, merge, fila e Origin, e o
gerenciamento de sessão, porque a unidade de trabalho "é feita numa zona". Qual seria o estado da arte com os
fornecedores (agentes da Cursor, do Claude e do Codex na nuvem): uma API rodando, monitoramento de eventos, tudo nos
adaptadores, rodando onde (o box do Grok Bot, uma VM)? O estado hoje é "código escrevendo em cima de código e tudo
mergeado", o que não parece o estado da arte; por exemplo, um banco da Amazon para coordenar o estado. Independente do
programa que rodar, qual seria a arquitetura ideal.

Correção das 23:43 BRT: a escolha é livre, independente do fornecedor; há crédito na Amazon, então preferência por
serviços da Amazon e do Google; no forge, o Origin é o predileto e o principal, e os adaptadores têm que servir ao
Origin e ao GitHub; o runner na VM provavelmente é um erro antigo de arquitetura e pode sair.

Dinheiro continua sendo decisão de Daniel: todo recurso pago aparece aqui como recomendação com custo mensal; nada é
criado.

## 2. O que 1 PR/s significa em números

| Grandeza | Conta | Valor a 1 PR/s | Fonte |
|---|---|---|---|
| PRs mergeadas | 1 × 86.400 | 86.400 por dia (72.000 num dia de 20 h); ~2,6 milhões por mês | [I] |
| Distância de hoje | 1 ÷ 0,0028 a 1 ÷ 0,0114 | 90 a 360 vezes a vazão medida | [02](02-estado-atual.md) [M] |
| Gates que chegam | 1,25 gates por merge hoje | 1,25 por segundo | [M, [sistema](../programs/vazao/sistema.md)] |
| Sessões de agente em voo (A = 1) | Little: λ × tempo de sessão por PR, 10 a 20 min hoje (8 PRs em 71 min com 1 a 2 frentes) | 600 a 1.200 sessões simultâneas | [Q1, M, I] |
| Sessões em voo com amplificação A ≥ 10 | idem ÷ 10 | 60 a 120 | [I] |
| CPU do gate como é hoje | 105 s × 4 CPUs × 1,25 ÷ 0,75 | ~700 vCPU ocupadas | [M, I] |
| CPU do gate com fila em lote e cache | ≤ 20–40 vCPU·s por PR mergeada ÷ 0,75 | ~27–53 vCPU | meta [I], conta em [11 §4](11-gate-merge-fila-origin.md#4-as-contas) |
| API do forge como é hoje | ~60 pontos por PR × 60 por minuto | 3.600 pontos/min, acima do token de instalação (3.000) | [02](02-estado-atual.md), [S21] |
| API do forge com eventos e merge em lote | ≤ 25 pontos por PR × 60 | ≤ 1.500 pontos/min, 25 % do JWT de app | meta [I] |
| Avanços da base | hoje um merge commit por PR | 60 por minuto; o GitHub recomenda até 1 merge por minuto por repositório [S14] | [I] |
| Eventos de estado | ~20 por PR | ~20 por segundo, ~30 escritas por segundo num banco | [I] |
| Tokens de IA (A = 1) | ~10^6 por PR com leitura de cache | ~10^6 por segundo; ~US$ 0,28 por PR no Sonnet 5.5 por API (~US$ 720 mil/mês), ~US$ 0,018 no Haiku 5.5 (~US$ 47 mil/mês) | [02](02-estado-atual.md), [05 §1](05-orcamento-e-degraus.md) |

Duas consequências antes de qualquer desenho:

1. **A infraestrutura de 1 PR/s é pequena** (dezenas de vCPU, dezenas de escritas por segundo, um forge a 25 % da cota).
   O que não cabe no motor de hoje é a forma: uma caixa com trava, estado em arquivo e em git, sessões por script.
2. **O custo de 1 PR/s é a IA**, não a infraestrutura. Com IA escrevendo cada PR, 1 PR/s custa de ~US$ 47 mil a
   ~US$ 720 mil por mês só em tokens por API. A amplificação de [06](06-contrato-planejador.md) (A ≥ 10 em 1/s) divide
   isso por 10; a capacidade das assinaturas, quando os termos permitem, é a outra alavanca (ver
   [12](12-unidade-e-sessoes.md)).

## 3. O que trava hoje, por classe

Evidência: os 27 incidentes em docs/operations/incidents/ até 03/11 (por tipo: 19 recusas
de push, 1 control plane, 1 janela do armazém de configuração, 1 parada por cota, 1 fim de turno, 1 parada para o dono,
1 lane pedindo decisão, 1 ambiente, 1 recusa de corpo), as medidas de [02](02-estado-atual.md) e a pesquisa da caixa
([docs/research/box.md](../research/box.md)).

| # | Classe | Evidência | Causa estrutural | O que a solução definitiva exige |
|---|---|---|---|---|
| K1 | **Dois escritores no mesmo branch** | das 19 recusas de push, 8 foram "non-fast-forward" (o branch andou por outro escritor ou ficou para trás; dois escritores confirmados no retro do TRAIN-TEMP-FIX), 8 foram checagens locais recusando o push e 3 foram credencial, acesso ou rede; `units/f23` recusou 3 vezes em um minuto (03/11 17:01–17:02 UTC; I-cfe21b97, I-dc6e9e49, I-f76ac711) [M] | o `deliver` mescla a base no branch da PR a partir de outro checkout e o push guard empurra de clones diferentes; nada garante um dono por branch | **um escritor por branch** (a sessão autora); a mistura com a base acontece num ramo de lote da fila, nunca no branch da PR |
| K2 | **Credencial e rede do forge nas sessões** | "credential helper ... told us to quit" e "Failed to connect" no push para o Origin (03/11 13:37 e 13:57 UTC; I-113901d1, I-69de9e61) [M] | cada ambiente de fornecedor configura credencial à mão; a chave pessoal precisa ser trocada pela CLI | **identidade de serviço** para a fábrica (app do Origin com JWT e token de instalação) e credencial de sessão injetada pelo orquestrador, com prazo curto e preflight |
| K3 | **Estado operacional em git e no plano gratuito** | o Durable Object fora do ar por cota provável (I-5102f4e9); a janela do log em git-ref sem snapshot recusou toda regeneração (03/11 16:50 UTC; I-f080dca5); filas em `pr-N.json` e trava de kernel na caixa (train) [M] | estado de execução guardado onde não há transação, índice nem orçamento de leitura | **banco transacional** para o estado de execução; git só para o estado desejado ([13 §1](13-estado-e-coordenacao.md#1-o-que-fica-em-git-e-o-que-sai)) |
| K4 | **Sessões que param e ninguém retoma** | o limite de 5 h parou três lanes às 06:47 BRT, a cota voltou às 07:10 e nada retomou até 07:42 (I-2012f37d); a sessão encerrou o turno e o fluxo ficou parado de 02:33 a 03:06 BRT (I-0d1c3a25); paradas para pedir decisão (I-ddaca17c, I-10901f05) [M] | sessão gerida por scripts no box do bot e leitura de eventos por consulta periódica, sem máquina de estados com prazos | **orquestrador durável** com timers por unidade, retomada automática no reset de cota e contrato de unidade com política de decisão |
| K5 | **Computação do gate fixa e pequena** | a VM e2-micro tem 953 MB e faz swap; a caixa de 4 CPUs roda uma suíte por vez (113 s sozinha, 346 s cada com três juntas); mediana de 105 s do head ao merge [M] | capacidade fixa sem elasticidade; o runner em VM é, nas palavras de Daniel, um erro antigo de arquitetura | **computação efêmera e elástica** para o gate, gerenciada, com cache por conteúdo compartilhado e atestado |
| K6 | **Fornecedor sem a capacidade que a unidade pede** | o Codex não tinha root para a prova de sessão uid 0 (03/11 14:07 UTC; I-986a5daf) [M] | a unidade vai para um ambiente sem conferir o que ele oferece | **matriz de capacidades** por fornecedor; o orquestrador só despacha para quem tem a capacidade |
| K7 | **Merge serial pela API, uma PR por vez** | um merge commit e uma chamada de merge (10 pontos) por PR; ~60 pontos por PR [M, E] | a fila só agrega a verificação, não o pouso | **pouso em lote**: um avanço da base por lote, prova do lote no head exato |

Nenhuma dessas classes é falta de esforço: todas são forma. É por isso que remendos sucessivos não resolveram.

## 4. Requisitos da solução definitiva

| ID | Requisito | Meta a 1 PR/s |
|---|---|---|
| R0-01 | Vazão | 1 PR mergeada/s sustentada numa janela de 1 h; capacidade de 1,33× em todo estágio |
| R0-02 | Estado fora do repositório | zero estado operacional commitado (filas, claims, leases, eventos, diário, resultados de gate, sessões, overrides de configuração) |
| R0-03 | Um escritor por branch | zero recusas de push por concorrência |
| R0-04 | Fila de merge | lote, especulação e partição por unidade; um avanço da base por lote (≤ 4 por minuto); prova no head exato do lote |
| R0-05 | Gate | p50 ≤ 60 s por lote; ≤ 40 vCPU·s por PR mergeada (meta 20); vermelho dentro da fila ≤ 2 % (filtro na sessão antes da fila) |
| R0-06 | Eventos por push | webhooks assinados com reentrega e transmissão ao vivo; nenhuma consulta periódica no caminho normal; reconciliação só como rede de segurança |
| R0-07 | Orquestrador durável | cada unidade e cada PR é um workflow com estado, prazos e retomada; sobrevive à queda de qualquer máquina |
| R0-08 | Sessões de qualquer fornecedor pela mesma porta | lançar, acompanhar, retomar e encerrar; concorrência e cota por fornecedor; retomada automática no reset |
| R0-09 | Forge | Origin principal e GitHub segundo, pela mesma porta; a fábrica age com identidade de serviço |
| R0-10 | Cota do forge | ≤ 50 % de cada limite: ≤ 25 pontos por PR com o JWT de app a 1 PR/s |
| R0-11 | Nenhuma máquina de estimação no caminho crítico | o box do Grok Bot e qualquer VM fixa saem do caminho; tudo o que é crítico é gerenciado ou efêmero |
| R0-12 | Observabilidade | vazão, latência por estágio, vermelho, flake e custo por PR (tokens, vCPU·s, pontos de API) num painel, medidos de fora |
| R0-13 | Custo | infraestrutura com custo mensal escrito por opção e um caminho gratuito; IA medida por PR com a amplificação como alavanca |
| R0-14 | Segurança | segredos num cofre gerenciado, privilégio mínimo por papel, sandbox para código, prova do gate assinada por chave fora do alcance das sessões |

Os requisitos são o corte de 1 PR/s dos de [01](01-requisitos.md): R0-02 é P3 e RNF-09, R0-04 é AD-3, R0-05 é AD-4,
R0-07 é AD-5, R0-08 é a porta de sandbox e de inferência, R0-11 é P10. Os documentos seguintes mostram a forma
([10](10-arquitetura-10-0.md)), a fila e o gate ([11](11-gate-merge-fila-origin.md)), a unidade e as sessões
([12](12-unidade-e-sessoes.md)), o estado ([13](13-estado-e-coordenacao.md)), o custo e a migração
([14](14-custos-e-migracao.md)).
