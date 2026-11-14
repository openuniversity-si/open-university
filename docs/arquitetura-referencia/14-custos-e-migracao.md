# 14. Custo mensal por opção, crédito AWS e o plano de migração

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

> **Na fronteira de 12:19** ([22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça)): infraestrutura e instalação. O
> custo da AWS e o crédito são da instalação, com o valor do teto decidido pela liderança (D-303); o custo dos agentes
> (§3) é um dado que a gestão calcula do registro; do plano de migração (§4), os passos que tiram do repositório o
> estado da gestão (a fila, o diário, as lições, os atritos) passam para a fase 2.

Custos a **1 PR/min**, o dimensionamento de agora (Daniel, 04/11 01:06), e a 0,1 e a 1 PR/s, para as opções de
[10 §2](10-arquitetura-10-0.md#2-onde-cada-componente-roda), com a A1 na forma definitiva de
[10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia) e os serviços mais baratos da AWS (01:08);
quanto crédito AWS cada uma consome por mês, o caminho sem dinheiro e os passos da migração, cada um com critério de
pronto.
Nenhum recurso é criado: cada item pago é recomendação para a decisão de Daniel. O crédito AWS é de **US$ 1.100**, nada
usado em 04/11/2026: US$ 1.000 do AWS Activate Founders (vence em 31/10/2028) e US$ 100 da camada gratuita (vence em
07/10/2027); gasto do mês, US$ 0 (dado da Torre, lido no console da conta em 04/11 00:26 BRT [M]). A seção 6 diz
quanto ele dura em cada opção.

## 1. O custo, separado em três partes

O custo da fábrica tem três partes de tamanhos muito diferentes, e misturá-las esconde a decisão:

1. **Infraestrutura da fábrica** (entrada, orquestração, estado, fila, observação): a seção 2.
2. **Computação do gate** (o tier 2 nos runners): a seção 2.
3. **Agentes** (tokens e o tempo de sandbox de cada sessão): a seção 3. É a maior parte, de longe.

## 2. Infraestrutura e gate por opção

Carga de referência por PR: 15 passos de workflow, 20 escritas, 50 leituras, 10 mensagens, 5 webhooks, 30 KB de log e
um tier 2 de 20 a 40 vCPU·s ([11 §4](11-gate-merge-fila-origin.md#4-as-contas)); mês de 43.200 PRs a 1 PR/min e de
2.592.000 a 1 PR/s; preços
de us-east-1 e us-central1 em nov/2026 [C35–C50] e as contas da pesquisa de preços [I]. Nas outras opções, rede, KMS
e suporte ficam fora; na A1, que é a forma definitiva, entram o runner quente da entrega em ~1 s
([11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s)), os IPs públicos
das tarefas e dos runners e a fila de ingresso, sem NAT [C52]; o KMS usa as chaves gerenciadas da AWS, sem custo. As
linhas da A2 à A4 a 0,1 e a 1 PR/s são as da primeira conta, sem runner quente: quem quiser a entrega instantânea soma
~US$ 26 por mês em qualquer opção.

| Opção ([10 §2](10-arquitetura-10-0.md#2-onde-cada-componente-roda)) | Maior parte | 1 PR/min por mês | 0,1 PR/s por mês | 1 PR/s por mês | Crédito AWS a 1 PR/min |
|---|---|---|---|---|---|
| **A1** AWS com Postgres e DBOS, na forma definitiva | a 1 PR/min: banco db.t4g.micro numa zona US$ 14, orquestrador numa tarefa de 0,25 vCPU US$ 7, runner quente em Fargate Spot US$ 22, IPs públicos US$ 7, S3 US$ 2, o resto na franquia grátis; a 1 PR/s: banco db.t4g.medium Multi-AZ US$ 116, duas tarefas US$ 57, ingresso US$ 31, logs US$ 36, S3 US$ 52, gate US$ 247–1.189 | **~US$ 53** (~US$ 87 com o runner sob demanda) | ~US$ 131–235 | ~US$ 552–1.495 | todo: **~21 meses** |
| A1 numa caixa EC2 (a sugestão de Daniel; **não recomendada**: máquina de estimação a trocar depois, [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia)) | instância m8g.large US$ 65 no lugar do Fargate; gate em 10 c8g.large (US$ 574 sob demanda, ~US$ 243 spot) | — | ~US$ 120–200 | ~US$ 475–805 [I] | — |
| A2 AWS sem servidor | orquestrador: Step Functions (US$ 16 a 1 PR/min, US$ 972 a 1 PR/s) ou funções duráveis do Lambda (US$ 5 e US$ 321); DynamoDB ~US$ 1 a 1 PR/min; gate em CodeBuild (computação Lambda) US$ 1.037 ou Fargate Spot US$ 220 a 1 PR/s | ~US$ 34–45 com runner quente [I] | ~US$ 70–220 | ~US$ 725–2.190 [I] | todo: até o vencimento (~24 meses) |
| A3 Google Cloud | Workflows US$ 389; gate em Cloud Build (pool privado) US$ 1.685 ou pool do Cloud Run | não calculado: fora da AWS (01:08) | ~US$ 140–240 | ~US$ 1.400–2.380 [I] | nenhum (é crédito do Google, se houver) |
| A4 Cloudflare pago | plano de controle US$ 141; gate em Containers US$ 1.454 (ou fora, na AWS) | não calculado: fora da AWS (01:08) | ~US$ 20–160 | ~US$ 360–1.600 [I] | só o gate, se rodar na AWS |
| A0 sem dinheiro | — | não chega | não chega | não chega | — |

**O caminho sem dinheiro (A0).** As franquias grátis cobrem quase nada da carga: o orquestrador e o gate acabam primeiro
(4.000 transições do Step Functions cobrem ~267 PRs por mês; 100 minutos de CodeBuild, ~100 gates; os 5.000 passos do
Workflows do Google, ~333 PRs) [I]. O que cabe sem pagar é o motor de hoje com os passos 0.1 e 0.2 da seção 4: o lote
com filtro na mesma caixa leva a ~150–190 PRs/h (~0,05 PR/s) [T7], e o control plane grátis da Cloudflare segura algo
entre ~0,06 e ~0,12 PR/s antes da cota ([10 §2](10-arquitetura-10-0.md#2-onde-cada-componente-roda)). O crédito de
conta nova é pequeno: US$ 100 a 200 na AWS (~3 dias da A2 a 1 PR/s) e US$ 300 no Google [C50, I].

## 3. Agentes

**No degrau atual** (decisão de Daniel, 04/11 00:35 BRT; [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau)) os
agentes rodam nas assinaturas que ele já tem: Claude Code em nuvem (Max, US$ 100/mês, e Pro, US$ 20/mês [A46]), Cursor
e Codex. O custo marginal por PR é zero até a cota do plano, com uma exceção: os agentes em nuvem da Cursor cobram pelo
preço de API do modelo (t) [A39]. O que limita não é dinheiro, é a cota: as janelas de 5 h e semanal e os limites de
concorrência, que o workflow mede no estado `esperando_cota`. Pela estimativa de [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau),
as assinaturas somadas ficam na faixa de ~0,03 a ~0,1 PR/s [E]: cabem as ~15 sessões simultâneas de 1 PR/min (A = 1).

**Depois de um gatilho de troca** (G1 a G4 de [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau): o uso deixa de
ser pessoal, interno ou não comercial, o volume passa da cota, o fornecedor avisa ou falta capacidade), os agentes vão
para o adaptador próprio com modelos no Bedrock, e o custo é o das tabelas abaixo. É o custo que decide. Com o padrão de
tokens que o motor mede por PR (~50 mil tokens não cacheados, ~14 mil de saída e ~936 mil de leitura de cache,
[02](02-estado-atual.md)) e os preços do Bedrock, iguais aos da Anthropic no endpoint global [A34]:

| Modelo | Tokens por PR | Por mês a 1 PR/min com A = 1 | a 1 PR/s com A = 1 | a 1 PR/s com A = 10 |
|---|---|---|---|---|
| Haiku 5.5 | ~US$ 0,023 | ~US$ 1 mil | ~US$ 59 mil | ~US$ 5,9 mil |
| Sonnet 5.5 | ~US$ 0,36 | ~US$ 15 mil | ~US$ 929 mil | ~US$ 93 mil |
| Opus 5.5 | ~US$ 0,72 | ~US$ 31 mil | ~US$ 1,86 milhão | ~US$ 186 mil |
| mistura da escada de modelos (70 % Haiku, 25 % Sonnet, 5 % Opus) [E] | ~US$ 0,14 | ~US$ 6,1 mil | ~US$ 366 mil | ~US$ 37 mil |

E o tempo de sandbox das sessões: ~900 simultâneas a 1 PR/s com A = 1 ([12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau)),
de 2 vCPU e 4 GB cada:

| Onde a sessão roda | Por hora de sessão | Por mês, 900 sessões | com A = 10 |
|---|---|---|---|
| Fargate Spot (preço de guia, x86) [C46] | ~US$ 0,031 | ~US$ 20 mil | ~US$ 2 mil |
| Fargate ARM sob demanda [C46] | ~US$ 0,079 | ~US$ 51 mil | ~US$ 5 mil |
| Claude Managed Agents (só o tempo rodando; os tokens à parte, pela API da Anthropic) [A32] | US$ 0,08 | ~US$ 52 mil | ~US$ 5 mil |
| AgentCore Runtime pelo preço cheio de vCPU·h e GB·h [A41] | ~US$ 0,22 | ~US$ 140 mil | ~US$ 14 mil |

**O que isso quer dizer.** A 1 PR/min, depois de um gatilho, a fábrica custaria ~US$ 6,5 mil por mês com a mistura de
modelos (US$ 6,1 mil de tokens, ~US$ 0,3 mil de sandbox, US$ 53 de infraestrutura); com as assinaturas, só os US$ 53.
A 1 PR/s com a IA escrevendo cada PR, ~US$ 390–420 mil por mês (US$ 0,6–1,5 mil de infraestrutura, US$ 20–51 mil de
sandbox, ~US$ 366 mil de tokens). Com
amplificação A ≥ 10, cai para ~US$ 40–43 mil por mês; e 0,1 PR/s com A = 1 custa o mesmo que 1 PR/s com A = 10. A
infraestrutura que resolve gate, merge, fila, Origin e sessões é **menos de 1 %** disso com A = 1, e de 1 a 3 % com
A = 10. O crédito AWS cobre a infraestrutura por meses e os agentes por API só por dias (seção 6).

**O registro dos termos** fica em [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau): os limites dos planos da
Anthropic assumem uso individual comum, e quem constrói produtos deve usar chave de API ou provedor de nuvem [A31]. É
por isso que o gatilho G1 (o uso deixar de ser pessoal, interno e não comercial) troca o adaptador antes de qualquer
mudança de volume. O Max e o Ultra trazem US$ 100 e US$ 200 de crédito de API por mês [A46], o que paga poucos milhares
de PRs no Haiku 5.5 pelo adaptador próprio, útil para o teste em sombra dele.

## 4. O plano de migração

Passos pequenos, cada um com valor próprio e critério de pronto medido de fora. Os passos 0.x não pedem dinheiro nem
fornecedor novo e cabem no motor de hoje; do passo 1 em diante cada um depende da decisão de Daniel sobre a opção da
seção 2. Cada passo de 1 a 6 implanta um componente já na forma final de [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia),
sem nada provisório a trocar depois; do passo 7 em diante só mudam números. Cada passo vira unidades da fila do motor;
nada disto é implementado nesta PR.

| Passo | O que muda | Critério de pronto | Precisa de |
|---|---|---|---|
| 0.1 | **Um escritor por branch.** O `deliver` e o trem deixam de mesclar a base no branch da PR; o lote é montado num ramo próprio (`queue/<lote>`); conflito com a base ejeta a PR para a sessão autora | zero `push-refusal` por "non-fast-forward" em 48 h de operação | nada |
| 0.2 | **Filtro antes da caixa e lote ligado.** O tier 1 verde no head exato vira condição para pedir a caixa; `delivery.batch` passa a `auto` com k adaptativo, como o D-297 já prevê | vermelho na caixa ≤ 0,03 nas últimas 50 PRs e ≥ 150 PRs/h processadas na hora de pico (a pesquisa da caixa prevê ~190/h com p ≈ 0,02 e k = 12 [T7]) | nada |
| 0.3 | **Medir o Origin.** E1: quantos merges por minuto pela API o repositório aceita (rajada controlada com PRs de teste numa base de teste); E2: os cabeçalhos do recurso `git` num push (o orçamento de git); E3: se o merge de PRs empilhadas serve de pouso em lote | os três números registrados num documento de unidade | nada |
| 0.4 | **O contrato da unidade na fila.** Cada linha `F<n>` ganha os campos do contrato de [12 §2](12-unidade-e-sessoes.md#2-o-contrato-da-unidade-de-trabalho): escopo, critério de aceite, orçamento, capacidades, prazos | o coordenador recusa lançar uma unidade sem o contrato completo | nada |
| 0.5 | **O app do Origin.** Criar o app da fábrica (chave Ed25519, assinatura de webhooks, token de instalação) e usar o JWT de app nas chamadas da fila | as chamadas da fila saem com o app; a chave de usuário sai da automação | credencial (Torre) |
| 1 | **Conta e guarda-corpos na AWS.** Contas ou ambientes separados, papéis IAM por componente, AWS Budgets com alarme em 50, 80 e 100 % do teto mensal escolhido, a chave do app no Parameter Store | um alarme de orçamento de teste dispara e chega à Torre | decisão de Daniel (dinheiro) |
| 2 | **Ingresso de eventos em sombra.** API Gateway e Lambda verificando a assinatura Ed25519 do Origin e gravando na fila SQS de entrada; o serviço de workflows grava cada evento no banco de estado com o `event_id` do envelope; o Worker de hoje continua | 100 % das entregas do Origin em 48 h estão nos dois com o mesmo `event_id`; a reentrega do Origin cobre as falhas | passo 1 |
| 2.5 | **Modelo de domínio v1 nos contratos.** Os contratos das entidades e do envelope v2 de [16](16-modelo-de-dominio.md), a migração inicial do banco e o carregamento da fila de hoje para a tabela de processos | a migração roda no PostgreSQL 18.6 do toolchain e a fila inteira entra na tabela sem perda (mesma contagem, mesmas chaves `F<n>`) | nada |
| 3 | **Estado fora do repositório.** A fila, o diário, as sobreposições de configuração, heartbeats, lições e fricções passam para o banco atrás das portas que o motor já tem (um adaptador de banco para a porta de eventos e para o armazém de configuração) | uma semana com as ferramentas lendo do banco e nenhuma escrita no log em git-ref nem na fila em arquivo | passo 2 |
| 4 | **Runner do tier 2 gerenciado.** Imagem com o toolchain fixado (o mesmo `scripts/cloud/setup.sh`), o runner quente que prova cada head no push, o veredito por alvo pela chave das entradas, cache em S3 que só o runner escreve; em sombra contra a caixa | 100 provas com o mesmo veredito da caixa em ≥ 99 %, prova de um head p50 ≤ 20 s | passo 1 |
| 5 | **Fila de merge no orquestrador.** Primeiro só calcula lotes, vereditos e o que pousaria (sombra); depois pousa, com o check run do app e a regra `merge_branch` exigindo-o | 500 PRs pousadas com zero recusa de push, vermelho na fila ≤ 2 %, "pronta → mergeada" p50 ≤ 1 s e p99 ≤ 3 s com lote de uma | passos 3 e 4 |
| 6 | **Corretor de sessões e workflow da unidade.** A porta de [12 §4](12-unidade-e-sessoes.md#4-a-porta-do-corretor-de-sessões) com os adaptadores das assinaturas como principais no degrau atual (Claude Code em nuvem, Cursor pela API, Codex) e o do agente próprio com Bedrock pronto e testado em sombra para os gatilhos de [12 §6](12-unidade-e-sessoes.md#6-a-escolha-por-degrau); prazos, retomada e `esperando_cota` como timers | 100 unidades de ponta a ponta sem ação manual, inclusive um reset de cota retomado sem ninguém | passo 3 e orçamento de agentes |
| 7 | **Desligar o que saiu.** A VM e2-micro, o Durable Object, a trava e a pasta de fila da caixa, o log em git-ref e os scripts de sessão do box | 7 dias sem dependência deles no caminho crítico, medido pelos eventos | passos 5 e 6 |
| 8 | **Escalar de 1 PR/min a 1 PR/s, só com números.** Classe do banco e a réplica em outra zona, tamanho e número das tarefas, partições e lote da fila, rajada de runners, concorrência de sessões por fornecedor, amplificação A ≥ 10 pelo planejador; nenhum componente trocado | 1 PR/s sustentada numa hora com todas as guardas ([11 §6](11-gate-merge-fila-origin.md#6-metas-numéricas)) | passos 5 a 7, e orçamento de agentes |

## 5. O que dá para fazer amanhã

Sem dinheiro e sem fornecedor novo, no motor de hoje:

1. **Passo 0.1** (um escritor por branch): ataca a maior classe de incidentes (8 das 19 recusas de push foram
   "non-fast-forward").
2. **Passo 0.2** (filtro antes da caixa e lote ligado): o maior ganho sem custo, de ~41 PRs/h na melhor hora para ~150–190
   PRs/h estimados na mesma caixa [T7].
3. **Passo 0.3** (medir o Origin): três medidas que decidem o pouso em lote.
4. **Passo 0.4** (o contrato da unidade): a forma que o orquestrador vai executar depois.

E as decisões que destravam o resto, todas de Daniel, porque são dinheiro:

1. **A opção** da seção 2. A recomendada é a A1 (AWS com Postgres e DBOS), com todos os componentes desde o primeiro dia
   e dimensionada para 1 PR/min ([10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia)): ~US$ 53
   por mês, ~US$ 131–235 a 0,1 PR/s e ~US$ 552–1.495 a 1 PR/s de infraestrutura e gate. A caixa EC2 que ele sugeriu
   fica de fora: seria uma máquina de estimação a trocar depois.
2. **O runner quente** (pool mínimo de um, ~US$ 26 por mês com o IP): é ele que faz a entrega em ~1 s
   ([11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s)); sem ele a A1
   custa ~US$ 31–47 e cada prova paga a partida a frio. A recomendação é ligá-lo.
3. **O teto mensal de crédito AWS.** Com os US$ 1.100, a recomendação é um teto de US$ 60/mês no AWS Budgets, com
   alarmes em 50, 80 e 100 % no passo 1; o teto sobe com a vazão, por decisão dele, porque é dinheiro.
4. **O orçamento de agentes** (seção 3): no degrau atual, as assinaturas que ele já paga; quando um gatilho de troca
   disparar, qual degrau, qual mistura de modelos e quando a amplificação A ≥ 10 do planejador entra. É a maior parte
   do custo e não se resolve com infraestrutura.

**Decididas** (Daniel, 04/11 01:39 BRT): "Aprovo: A1 a 1 PR/min com o runner sempre ligado e teto de US$ 60/mês no AWS
Budgets". As decisões 1 a 3 valem; a 4 fica para quando um gatilho de troca disparar. O orçamento já existe: a Torre o
criou no console às 01:44 (`torre-motor-teto-60`, US$ 60 por mês, custos não mesclados, alertas reais em 50, 80 e 100 %
e previsto em 100 %). Sem filtro de tipo de cobrança, ele inclui os créditos, que é o padrão da AWS [C54]: enquanto
houver crédito, o custo líquido fica perto de zero e nenhum alerta dispara. Para o teto valer sobre o consumo do
crédito, o orçamento precisa excluir os tipos de cobrança crédito e reembolso. A implantação segue em PR própria,
empilhada nesta, com o registro formal da decisão e o teste que a prova.

## 6. O crédito de US$ 1.100: quanto dura

A 1 PR/min, a A1 com todos os componentes custa **~US$ 53 por mês** e o crédito dura **~21 meses** (até ~jul/2028,
antes do vencimento do Activate em 31/10/2028); os US$ 100 da camada gratuita vencem antes, em 07/10/2027, e são
gastos primeiro. Os agentes ficam nas assinaturas e não entram nessa conta.

**Infraestrutura e gate** (preços da seção 2, de [C41], [C46] e [C52]; contas [I]):

| Configuração | Degrau | Por mês | Quanto os US$ 1.100 duram |
|---|---|---|---|
| **A1 a 1 PR/min**: RDS db.t4g.micro numa zona (20 GB, backup contínuo), uma tarefa Fargate ARM de 0,25 vCPU e 0,5 GB para o DBOS, um runner quente Fargate Spot de 2 vCPU e 4 GB, 2 IPs públicos, ingresso, S3, Parameter Store e CloudWatch na franquia grátis | 1 PR/min (43.200 PRs por mês) | **~US$ 53** | **~21 meses** |
| a mesma, com o runner quente sob demanda (Fargate ARM) | 1 PR/min | ~US$ 87 | ~13 meses |
| a mesma, sem runner quente (provas a frio; a entrega deixa de ser instantânea) | 1 PR/min | ~US$ 31–47 | até o vencimento (~24 meses) |
| A1 a 0,1 PR/s: db.t4g.small Multi-AZ, duas tarefas de 0,5 vCPU, runner quente e rajada | 0,1 PR/s | ~US$ 131–235 | ~5–8 meses |
| A1 a 1 PR/s: db.t4g.medium Multi-AZ com 100 GB, duas tarefas de 1 vCPU, runner quente e rajada | 1 PR/s | ~US$ 552–1.495 | ~3 semanas a ~2 meses |
| A2 AWS sem servidor, com runner quente | 1 PR/min | ~US$ 34–45 | até o vencimento (~24 meses) |
| A1 numa caixa EC2 (não recomendada, [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia)) | 0,1 PR/s / 1 PR/s | ~US$ 145–180 / ~US$ 475–805 | ~6–8 meses / ~1,4–2,3 meses |

A 1 PR/min a conta é: banco US$ 14, runner quente US$ 22, orquestrador US$ 7, IPs públicos US$ 7, S3 US$ 2, imagens
US$ 0,2; o ingresso (US$ 0,2), os logs, os alarmes, os segredos e o orçamento cabem na franquia grátis. O tier 2 de 1
PR/min (240 a 480 vCPU·h por mês) cabe inteiro no runner quente, então o custo não muda entre 20 e 40 vCPU·s por PR.
Nas linhas de 0,1 e 1 PR/s, a faixa vai do runner em Spot com 20 vCPU·s por PR ao runner sob demanda com 40 vCPU·s.
**Depois do crédito**, o mesmo valor sai do bolso: ~US$ 53 por mês a 1 PR/min.

**O que muda de 1 PR/min a 1 PR/s, só números** (a tabela de [10 §3](10-arquitetura-10-0.md#3-a-forma-definitiva-desde-o-primeiro-dia)):
a classe do banco (micro, small, medium), a réplica dele em outra zona (de zero para uma, a partir de 0,1 PR/s), o
disco (20 para 100 GB), as tarefas do orquestrador (uma de 0,25 vCPU para duas de 1 vCPU), a rajada de runners (de
zero para ~50 vCPU), o lote (de uma PR para até 24) e as partições. Nenhum componente entra nem sai.

**Agentes**, se o crédito puder pagar os modelos do Bedrock (os termos do Activate dizem se cobrem modelos de
terceiros; **a conferir no console** [E]):

| Tokens por mês | 1 PR/min | 0,1 PR/s | 1 PR/s |
|---|---|---|---|
| Haiku 5.5 | ~US$ 976: o crédito dura ~1 mês | ~US$ 5,9 mil: ~6 dias | ~US$ 59 mil: ~14 horas |
| mistura da escada de modelos | ~US$ 6,1 mil: ~5 dias | ~US$ 37 mil: ~1 dia | ~US$ 366 mil: ~2 horas |

Mais o tempo de sandbox das sessões, só com o adaptador próprio: ~US$ 335/mês a 1 PR/min (15 sessões) e ~US$ 2 mil a
0,1 PR/s em Fargate Spot (A = 1).

**O que eu faria com o crédito.** Gastá-lo na A1 a 1 PR/min, com todos os componentes: ela fecha as sete classes de
problema de [09](09-avaliacao-10-0.md), entrega a PR pronta em ~1 s, custa ~US$ 53 por mês e dura ~21 meses; com um teto
de US$ 60/mês no AWS Budgets, nenhum mês consome mais que ~5,5 % do crédito. O runner quente fica em Spot, sem reserva
sob demanda: quando falta Spot, a prova roda a frio numa tarefa de rajada e só aquelas entregas perdem o 1 s. Quando a
vazão subir, só números mudam, e o teto sobe junto. Os agentes ficam nas assinaturas enquanto o uso for pessoal,
interno e não comercial, sem gastar o crédito; **não** pagar agentes por API com o crédito, que dura dias nesse uso.
Quando um gatilho de troca disparar, os agentes viram a decisão de orçamento de Daniel (seção 3), e a amplificação
A ≥ 10 é o que torna esse orçamento pequeno.

**Antes de criar qualquer coisa** (passo 1 da seção 4): o acesso à conta sem chave de longa duração na caixa (IAM
Identity Center ou um papel assumido, com MFA na conta raiz), o orçamento com alarmes e só então os recursos. Hoje não
há CLI nem chave de acesso na caixa; criar o acesso é credencial, portanto de Daniel.

