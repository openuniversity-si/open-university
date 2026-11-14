# 22. As três camadas e a fronteira entre infraestrutura e gestão

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

Daniel, 04/11/2026, de 11:37 a 12:19 BRT. Às 11:37, lendo *O Verdadeiro Poder*, de Falconi: alcançar resultado tem três
partes, "liderança, método de gestão e conhecimento técnico" [N17]; o primeiro passo é "implementar só a infraestrutura
técnica", agnóstica, para "testar e implementar ao longo do tempo diferentes frameworks, diferentes sistemas de gestão em
cima". Às 11:39, "manda bala": fase 1, a infraestrutura; fase 2, a gestão; fase 3, a liderança. Às 11:45: a fábrica pode
rodar na conta de quem a usa ou na nossa, com vários programas, e "é extremamente importante que nossa infraestrutura seja
agnóstica ao programa rodado nela". De 12:05 a 12:17, o refino:

- 12:08: "separar o máximo possível a minha infraestrutura do comportamento que de fato vai ser realizado"; "A gente vai
  ser obrigado a abrir uma sessão de IA pra executar um script?"
- 12:11: "A gente vai ter um sistema de liderança, a gente vai ter um sistema de gestão, a gente vai ter um sistema de
  infraestrutura. Ponto." A gestão "pega uma meta abstrata, um desejo abstrato da liderança e transforma em execução".
- 12:14: "Quem disse que meta de fato existe? Pode ter um sistema de gestão que não tem nem meta."
- 12:15: "Campo livre de contexto já me preocupa. [...] Aqui eu tô olhando trabalho, bicho. Trabalho."
- 12:17: "Eu quero que a infra permita acessar todas as informações que forem pertinentes, mas quem vai dizer qual
  informação vai ser é o sistema de gestão."

Às 12:19, a fronteira consolidada pela Torre foi aprovada por Daniel: "Consolida sim [...] porque eu acho importante essa
separação". Depois, duas correções: às 12:37, "Não podemos limitar nossos PRs por causa de burocracia de planejamento"; e
às 12:40, sobre a forma de aplicar a fronteira: "Uma coisa é não limitar o comportamento, outra coisa é não permitir o
comportamento. [...] A fila poder se adaptar a diferentes tipos de prioridade, isso sim é abstraído. [...] uma coisa é ser
adaptável a diferentes parâmetros, outra coisa é você simplesmente tirar o parâmetro, bicho." Este documento passa a arquitetura inteira por ela: o que fica na infraestrutura, o que sai para a gestão ou
para a liderança e o que muda de nome, peça por peça (seção 3), com as tabelas da infraestrutura testadas (seções 5 e 6).

## 1. A fronteira (decisão de Daniel, 12:19)

**Três sistemas, só três.** A liderança diz o que se quer. A gestão transforma o querer em trabalho definido, do macro ao
job. A infraestrutura executa e registra trabalho, sem saber por quê.

**A infraestrutura conhece só trabalho:**

1. o **trabalho**: um identificador, uma entrada opaca e o estado do ciclo (na fila, rodando, esperando, terminou, falhou,
   parado, cancelado);
2. o **executor**, plugado por adaptador: um script ou contêiner, uma IA por assinatura, um modelo próprio, uma pessoa. A
   sessão de IA é um tipo de executor, nunca a unidade central, e rodar um script não abre sessão de IA;
3. a **saída**, devolvida como o executor a produziu;
4. o **registro** bruto de tudo o que a infraestrutura observa;
5. o **acesso** completo a esse registro: um fluxo assinável e a consulta ao histórico;
6. as **propriedades físicas** que existem em qualquer modelo: o isolamento entre tenants, a durabilidade, a segurança e o
   mecanismo de limite.

**A infraestrutura não conhece**, e cada sistema de gestão guarda o que for dele no esquema e nas tabelas dele, que
referenciam o id do trabalho: meta, objetivo, solicitante, projeto, programa no sentido de gestão, a razão de uma
prioridade (a ordenação é mecanismo, e o valor vem de fora), hierarquia;
quais informações importam (tempo, custo e taxa de sucesso são dados do registro que a gestão escolhe ler, não colunas que
a infraestrutura escolhe); métricas, painéis, alertas, relatórios e cobrança; qual executor usar e quando ("existe script?
então roda o script" é comportamento: a infraestrutura só roteia entre os que o trabalho aceita); quem pode criar trabalho (a gestão com chefe, a sem meta e o trabalhador autônomo
usam a mesma porta). **Nenhum campo livre de contexto**: a infraestrutura não guarda nada da gestão.

**Mecanismo e decisão.** A infraestrutura oferece o mecanismo (parar ou recusar ao atingir um limite); quem a usa decide o
valor e a razão (o teto de US$ 60 e por quê).

**Adaptável a parâmetros, nunca o parâmetro tirado** (12:40). A fronteira não tira capacidade da infraestrutura: tira dela
a escolha. Uma fila sem prioridade, ou uma falha sem retentativa, seria a infraestrutura escolhendo um comportamento. Cada
mecanismo tem parâmetros, e quem a usa escolhe os valores: a fila ordena pela política que a fila tiver (ordem de chegada,
`rank`, prazo ou outra que se plugue); a retentativa vale o número de tentativas, a espera e as condições que o trabalho
trouxer; o roteamento escolhe, entre os executores que o trabalho aceita, um com capacidade. O valor padrão é um valor
(a ordem de chegada, uma tentativa), nunca a ausência do parâmetro.

**Os três testes de cada peça:**

| Teste | Pergunta | Se sim |
|---|---|---|
| (a) | Isso existiria em qualquer modelo de gestão imaginável: com ou sem meta, com chefe ou autônomo, por IA ou por pessoa? | infraestrutura |
| (b) | Se ninguém nunca ler isso, a infraestrutura continua correta? | é observação: a infraestrutura só registra e expõe |
| (c) | Isso expressa preferência sobre o que é bom, ruim ou importante? | gestão (ou liderança) |

**O teste de aceite:** trocar o sistema de gestão inteiro, ou o comportamento de execução, sem mudar uma linha da
infraestrutura; e o mesmo trabalho rodar como script, sem sessão de IA, e como sessão de IA, também sem mudar nada nela.

**A regra de dependência.** A liderança fala com a gestão; a gestão fala com a infraestrutura pelo contrato da seção 4; a
infraestrutura não chama ninguém acima dela, só publica o registro. A planta com os três sistemas está em
[18 §4](18-planta-geral.md#4-os-três-sistemas-e-as-conexões).

## 2. Como os melhores separam o mecanismo da política

| Lição | Fonte | O que a infraestrutura adota |
|---|---|---|
| O problema central não é definir funções para necessidades específicas, mas dar um núcleo sobre o qual uma hierarquia de sistemas atenda a "diverse requirements of program scheduling and resource allocation" | Brinch Hansen, 1970 [K1] | é o teste de aceite: a infraestrutura não sabe qual gestão roda sobre ela |
| O núcleo dá mecanismos, dos quais um conjunto arbitrário de políticas se constrói; decisão de política não é material de núcleo | HYDRA [K2] | a infraestrutura não escolhe trabalho, não define etapas, não julga valor, não escolhe executor |
| A separação completa é impraticável; o meio-termo é uma política do núcleo parametrizada | Levin et al., 1975 [K3] | toda política da infraestrutura é um parâmetro com valor padrão: a ordem da fila, a retentativa, o roteamento, a exclusão mútua numa chave, o limite |
| Separar a proteção da gestão: proteger o disco sem entender o sistema de arquivos | Exokernel [K4] | o isolamento, o lease e o limite sem entender o método que os usa |
| O limite de memória é "the main mechanism to limit memory usage": ao passar, o núcleo age; o valor é de quem configura | cgroups v2 [K14] | o limite como mecanismo (parar ou recusar), com o valor dado de fora |
| O mestre oferece recursos a vários frameworks, por uma política de alocação plugável ("fair sharing or strict priority"); o escalonador tem "a pluggable policy" que reparte os recursos entre as filas | Mesos [K5], YARN [K6] | vários sistemas de gestão sobre a mesma infraestrutura, cada um com o seu planejador, fora dela; a fila com um módulo de ordenação plugável |
| A prioridade é um objeto que mapeia um nome para um valor inteiro, e quem cria o pod escolhe a classe | Kubernetes, PriorityClass [K16] | o `rank` do trabalho e a política da fila: o mecanismo é da infraestrutura, o valor é de quem cria |
| A política de retentativa tem intervalo inicial, coeficiente, intervalo máximo, número de tentativas e erros que não se repetem, todos com valores padrão | Temporal [K15] | a retentativa como mecanismo do trabalho, com os mesmos parâmetros |
| Uma tarefa é uma unidade atômica de trabalho, de serviço, de script ou de pessoa; executores com "a common API", "pluggable" | BPMN no Camunda [K11], Temporal [K12], Airflow [K13] | o executor por adaptador, e a pessoa como um executor |
| A saída de uma ação se guarda pelo digest da ação | Bazel, Remote Execution API [V6] | o cache de resultado por executor e digest da entrada, que faz a verificação instantânea sem a infraestrutura saber o que é uma verificação |
| Rótulos e anotações guardam metadado do cliente no próprio objeto, e um seletor escolhe por eles | Kubernetes [K7], o Memo do Temporal [K8] | no trabalho, **não**: a fronteira de 12:15 tira todo campo de contexto, e a gestão guarda o dela com o id do trabalho; no executor, sim: propriedades técnicas que um seletor pede |
| O `type` de um evento leva o domínio de quem o define | CloudEvents [W6] | o registro da infraestrutura só leva os tipos que ela observa; os eventos da gestão ficam no registro dela |
| Políticas de linha restringem que linhas cada usuário vê | PostgreSQL [K10] | toda linha leva o tenant; o modo com vários clientes liga essas políticas sem mudar o esquema |

## 3. O inventário, peça por peça

Cada peça dos documentos 09 a 21 e das versões anteriores deste, passada pelos três testes. Na terceira coluna, a forma e
o nome que a peça tem na infraestrutura; na quarta, o que sai dela e para onde.

**Trabalho e execução**

| Peça (onde estava) | Teste | Fica na infraestrutura como | Sai para |
|---|---|---|---|
| o processo `F<n>`, `work.process` ([16](16-modelo-de-dominio.md), [17](17-ciclo-do-processo.md)) | (a) | o **trabalho** (`work.job`): id, entrada opaca, executor, estado | a gestão: a chave `F<n>`, o pai (aposta ou objetivo), o domínio, o aceite |
| a tentativa, `work.attempt` (16) | (a) | a **execução** (`work.run`), cada despacho ao executor, e a **retentativa** como mecanismo: número de tentativas, espera crescente, os desfechos que pedem outra e os erros que nunca pedem, com padrão de uma tentativa; o novo despacho quando o executor some é durabilidade e não conta tentativa | a gestão: os valores, e o que fazer quando as tentativas acabam |
| a sessão (12, 16) | (a) | a execução do adaptador `agent-session`, com o id externo | — |
| o fornecedor, a conta e a cota (12, 16) | (a) | o **executor** (`work.executor`) e a **capacidade** (`work.capacity`) | — |
| o corretor de sessões ([10](10-arquitetura-10-0.md), [12](12-unidade-e-sessoes.md)) | (a) | o **corretor de execução**: uma porta, um adaptador por tipo (contêiner, sessão de agente, pessoa, forge) | — |
| a escolha do fornecedor por degrau (12 §6) | (c) | o roteamento entre os executores aceitos, pela capacidade | a liderança (em que gastar) e a gestão (que executores aceitar para que trabalho) |
| os executores aceitos em ordem e o tipo do brief (a versão anterior deste) | (a) mecanismo, (c) valor | o **roteamento**: um executor exato, ou um seletor (uma lista em ordem, um adaptador, propriedades técnicas do executor), e a capacidade decide entre os aceitos; o adaptador recusa a entrada que não entende | a gestão: quais aceitar e em que ordem |
| o brief, as instruções (12 §2, [19 §5](19-direcao-ideal.md#5-o-padrão)) | (a) | a **entrada opaca** do trabalho, por referência e digest | a gestão: o conteúdo, o padrão, as versões |
| as oito etapas, `work.stage` (17 §2) | (c) | o relato bruto do executor no registro, que aceita qualquer marca que o brief pedir | a gestão: os nomes, a ordem, as durações |
| o modelo com a lista de passos (a versão anterior deste) | (a), não | — | a gestão |
| o plano de commits, os itens, o caminho crítico (17 §3) | (a), não | — | a gestão |
| o teto de 1 a 8 itens do plano (D-022, D-025; `budgets.pr_commits_max` em `commit_check.py`) | (c) | — | nem a gestão o mantém: "Não podemos limitar nossos PRs por causa de burocracia de planejamento" (Daniel, 12:37); a PR se divide pelo conteúdo ([21 §6](21-revisao-geral.md#6-as-instruções-e-os-prompts)) |
| `labels`, `annotations` e a chave do programa (a versão anterior deste) | campo de contexto | só a **chave de idempotência**, para não criar o mesmo trabalho duas vezes | a gestão, nas tabelas dela, pelo id do trabalho |
| a prioridade (16, a versão anterior deste) | (a) mecanismo, (c) valor | a **ordenação configurável**: cada fila tem uma política (ordem de chegada, `rank`, prazo, ou outra que se plugue), e cada trabalho leva os parâmetros (`rank`, `not_before`, `deadline`); o padrão é a ordem de chegada, como valor | a gestão: a política de cada fila e os valores |
| as dependências entre trabalhos, `work.dependency` (16) | (a) mecanismo | as **dependências**: um trabalho só fica pronto quando outros terminam, ou terminam com sucesso | a gestão: quais e por quê |
| o orçamento da unidade (12 §2) | (a) mecanismo, (c) valor | o **limite** (`work.limits`): parar ou recusar ao passar um máximo num medidor | quem o define: o valor e a razão |
| a espera com motivo, `work.block` (a versão anterior deste) | (b) | o estado `waiting`, o relato bruto do executor e a **retomada** por quem está de fora, com um conteúdo opaco que o executor recebe | a gestão: a classe da parada, o pedido à Torre |
| as condições `stalled`, `waiting_quota`, `blocked`, `stale` (16 §5.4) | (a) e (c) | o lease vencido (com novo despacho) e a espera por capacidade | a gestão: `blocked` (dependência, pedido) e `stale` (a base andou) |
| o lease com fencing token (16 §5.5) | (a) | igual | — |
| a entrega `merge`, `pr` ou `none` (a versão anterior deste) | (a), não | abrir a PR e pousar são trabalhos do executor `forge`, que as dependências encadeiam | — |
| o domínio (capacidade, eficiência, administração) ([AGENTS.md](../../AGENTS.md)) | (c) | — | a gestão |

**Verificação e integração**

| Peça (onde estava) | Teste | Fica na infraestrutura como | Sai para |
|---|---|---|---|
| a prova por alvo e o cache atestado, `verification.target_verdict` ([11 §5](11-gate-merge-fila-origin.md#5-o-caminho-de-baixa-vazão-da-pr-pronta-à-mergeada-em-até-1-s), 16) | (b) | o **cache de resultado** (`work.result_cache`): a saída assinada de um executor para um digest de entrada; um trabalho com `memoize` a reaproveita sem rodar | — |
| o certificado, `verification.proof` (11, 16) | (c) | — | a gestão: que trabalhos de checagem provam um head |
| que checagens rodar para que caminhos (o mapa de áreas e os covers do gate de hoje) | (c) | cada checagem é um trabalho do executor `container` | a gestão, como configuração do repositório |
| o tier 1 na sessão (10, 11) | (c) | — | a gestão: o que o brief manda conferir antes de entregar |
| a checagem de estrutura e a de metadados da PR (o gate de hoje) | (c) | — | a gestão |
| o runner quente (10, [14](14-custos-e-migracao.md)) | (a) | a capacidade do executor `container` | — |
| a PR, `integration.pr`, com `ready` e `queued` (16) | (c) | os webhooks do forge, brutos no registro; o executor `forge` para abrir, empurrar e pousar | a gestão: o estado da PR para o método |
| a fila de merge, o lote, a ejeção, a bissecção, `integration.batch` (11, 16) | (a) e (c) | a **chave exclusiva** (um trabalho por vez no mesmo ramo), o pouso com compare-and-swap pelo executor `forge`, as dependências (o pouso espera as checagens) e a fila com a política que se quiser; um trabalho pode levar várias mudanças na entrada | a gestão: o que pousar, quando e em que lote |
| a entrega em ~1 s (11 §5) | (a) e (c) | os mecanismos que a permitem: o cache, o executor quente, o pouso, o registro em tempo real | a gestão: a meta e o fluxo |
| a porta do forge, Origin e GitHub (10, 11) | (a) | o adaptador `forge` e o ingresso dos webhooks | — |

**Registro e medição**

| Peça (onde estava) | Teste | Fica na infraestrutura como | Sai para |
|---|---|---|---|
| o envelope de eventos v2 (16 §7.2) | (a) | o **registro** (`log.event`), só com o que a infraestrutura observa: `job.*`, `run.*`, `executor.*`, `capacity.*`, `limit.*`, `cache.*`, `forge.*`, `platform.*` | — |
| os eventos de processo, plano, aposta, lição e padrão (16 §7.2, 17 §4, [20 §6](20-sistema-de-aprendizado.md#6-tabelas-e-eventos)) | (c) | — | a gestão, no registro dela |
| os eventos do programa com prefixo no registro da infraestrutura (a versão anterior deste) | campo de contexto | — | a gestão |
| a janela de autonomia, a vazão, as durações, as guardas, as visões `metrics.*` ([19 §7](19-direcao-ideal.md#7-a-medição-da-direção), [21 §4](21-revisao-geral.md#4-a-medição), a versão anterior deste) | (b) e (c) | o registro bruto e o acesso a ele: o fluxo assinável (`log.subscription`) e a consulta, com os filtros e as agregações que quem consulta definir | a gestão, que escolhe o que ler e como medir |
| o uso e o custo, `agents.usage` e `cost_usd` (21 §1, a versão anterior deste) | (b) | o uso relatado pelo adaptador, bruto (`run.usage`, com o medidor e a quantidade), e o **preço por medidor** (`work.meter_rate`), que converte um medidor em outro para que um limite possa ser em dinheiro; o limite conta só os medidores que alguém limitou | a gestão: o preço, o custo por PR |
| painéis, alarmes, relatórios, cobrança (10 camada 7, 21 §4 e §7) | (c) | o fluxo de eventos da plataforma, que quem quiser assina | a gestão |
| o diário e as notas (16 §6) | (c) | — | a gestão |

**Plataforma**

| Peça (onde estava) | Teste | Fica na infraestrutura como | Sai para |
|---|---|---|---|
| o programa da versão anterior deste (`work.program`) | (a) | o **tenant** (`work.tenant`): só o isolamento | a gestão: o que o programa é para ela |
| os limites do tenant (concorrência, dinheiro por dia) | (a) mecanismo, (c) valor | `work.limits` com o escopo do tenant | quem os define |
| o isolamento, as políticas de linha, as contas | (a) | igual; as políticas de linha quando houver vários clientes | — |
| a durabilidade: o orquestrador durável, o novo despacho, as partições, as cópias (10, [13](13-estado-e-coordenacao.md)) | (a) | igual | — |
| a segurança: identidades sem chave, cofre, sandbox, a assinatura do resultado (10, [21 §7](21-revisao-geral.md#7-a-padronização-na-aws)) | (a) | igual | — |
| a infraestrutura como código, o deployer, a campainha (a #265) | (a) | igual | — |
| o orçamento da AWS de US$ 60 (D-303) | (a) mecanismo, (c) valor | o mecanismo, o AWS Budgets | a liderança: o valor e a razão |
| a conta e a região (a #265) | instalação | parâmetros da instalação | — |
| a API da fábrica (10 camada 1) | (a) | a porta do trabalho: criar, cancelar, consultar, assinar o registro; a mesma para qualquer modelo de gestão | as "intenções", para a liderança |
| os comandos (21 §5) | (a) e (c) | `tower job`, `tower log`, `tower executor`, `tower limit`, `tower tenant` | a gestão: o gate, o trem, medir, dirigir, aprender, governar |

**Direção, aprendizado e liderança**

| Peça (onde estava) | Teste | Fica na infraestrutura como | Sai para |
|---|---|---|---|
| objetivo, aposta, escolha, planejador, premissas (19) | (c) | — | a gestão; e um modelo de gestão pode nem ter meta (12:14) |
| o padrão, as instruções e os prompts (19 §5, 21 §6) | (c) | — | a gestão |
| o aprendizado, as lições, a retrospectiva, os experimentos (20) | (c) | a entrega em sombra vira um trabalho como outro qualquer, que a gestão não pousa | a gestão |
| a intenção, a trava, a métrica-norte, os limites e a autoridade, a Torre, as decisões (19 §6 e §7, a [SEMENTE](../SEMENTE.md)) | (c) | — | a liderança |

## 4. O contrato entre a infraestrutura e a gestão

**A porta, a mesma para qualquer sistema de gestão:**

| Comando | Quem chama | O que a infraestrutura faz |
|---|---|---|
| registrar um tenant | a instalação | isola as linhas, as execuções e o registro dele |
| registrar um executor, com as propriedades técnicas dele | a instalação, ou um tenant com a chave dele | conduz pelo adaptador; acompanha a capacidade; o executor privado serve só ao tenant dele |
| configurar uma fila: a política de ordenação e os parâmetros dela | quem cria trabalho no tenant | ordena pela política; o padrão é a ordem de chegada |
| definir o preço de um medidor em outro | quem tem o valor | converte o uso relatado, para os limites |
| definir um limite (escopo, medidor, máximo, parar ou recusar) | quem tem o valor e a razão | soma o uso relatado no medidor e para ou recusa ao passar |
| criar um trabalho: a entrada por referência e digest; o executor exato ou o seletor; a fila e os parâmetros de ordenação (`rank`, `not_before`, `deadline`); a política de retentativa; as dependências; a chave de idempotência; a chave exclusiva; se reaproveita saída | qualquer um com acesso ao tenant: uma gestão com chefe, uma sem meta, um trabalhador autônomo | põe na fila, despacha pela política da fila quando as dependências estão satisfeitas, há capacidade num executor aceito e a chave está livre; tenta de novo pela política; devolve a saída e registra tudo |
| cancelar um trabalho; retomar um trabalho em espera, com um conteúdo para o executor | idem | cancela ou retoma, com evento |
| consultar um trabalho; assinar e consultar o registro | idem | devolve o estado, a saída e o registro bruto, sem escolher o que importa |

**O que o executor relata, pelo adaptador:** que começou, que espera algo de fora, o que produziu, o que usou (tokens,
segundos de CPU, minutos de uma pessoa: um medidor e uma quantidade) e como terminou. O que for além disso (as marcas de
etapa que o brief pedir, por exemplo) entra no registro como relato bruto, que a infraestrutura não interpreta.

**O que a infraestrutura nunca faz:** guardar contexto da gestão; escolher no lugar de quem a usa um valor que é dele (a
política da fila, as tentativas, os executores aceitos, os limites), e cada padrão é um valor que se troca; calcular uma
métrica que ela mesma escolheu; julgar uma saída; interpretar um relato. E nunca tira um parâmetro para resolver a
adaptabilidade (12:40).

## 5. As tabelas da infraestrutura

Dois esquemas, `work` e `log`, mais o `dbos` do orquestrador; 13 tabelas. Rodaram no PostgreSQL 18.6 do toolchain com o
teste da seção 6 [M]:

```sql
create table work.tenant (                                      -- o isolamento: quem divide a infraestrutura sem se ver
  id uuid primary key default uuidv7(), name text not null unique check (name ~ '^[a-z][a-z0-9-]{1,39}$'),
  state text not null default 'active' check (state in ('active','paused','retired')), version int not null default 1);
create table work.executor (                                    -- quem ou o que executa, por um adaptador
  name text primary key, adapter text not null,                 -- a infraestrutura não conhece a lista de adaptadores
  tenant_id uuid references work.tenant,                        -- nulo: da instalação; senão, só daquele tenant
  config jsonb not null default '{}',                           -- o que o adaptador precisa; segredo só por referência
  capabilities jsonb not null default '{}',                     -- propriedades técnicas que um seletor pode pedir
  state text not null default 'active' check (state in ('active','paused')));
create table work.capacity (                                    -- a capacidade física: vagas, cota que zera, agenda
  executor text not null references work.executor, account text not null,
  slots int not null check (slots >= 0), in_use int not null default 0 check (in_use >= 0), resets_at timestamptz,
  primary key (executor, account), check (in_use <= slots));
create table work.queue (                                       -- uma fila e a política dela; os valores vêm de fora
  tenant_id uuid not null references work.tenant, name text not null,
  policy text not null default 'fifo',                          -- o módulo de ordenação: fifo, rank, deadline ou outro plugado
  config jsonb not null default '{}', primary key (tenant_id, name));
create table work.job (                                         -- um trabalho: identificador, entrada opaca, estado
  id uuid primary key default uuidv7(), tenant_id uuid not null references work.tenant,
  queue text not null default 'default',
  rank numeric, not_before timestamptz, deadline timestamptz,   -- parâmetros de ordenação; a política da fila escolhe quais usa
  executor text references work.executor,                       -- um executor exato, ou
  selector jsonb not null default '{}',                         -- o que se pede: any_of em ordem, adapter, capabilities
  input_uri text not null, input_digest text not null,          -- a entrada, que só o executor lê
  idempotency_key text, exclusive_key text, memoize boolean not null default false,
  max_attempts int not null default 1 check (max_attempts >= 1),   -- a retentativa; o padrão é um valor: uma tentativa
  backoff_initial interval not null default '10 seconds', backoff_factor numeric not null default 2,
  backoff_max interval not null default '10 minutes',
  retry_on text[] not null default '{failed,timed_out}', non_retryable text[] not null default '{}',
  state text not null default 'queued'
    check (state in ('queued','running','waiting','succeeded','failed','stopped','cancelled')),
  result jsonb,                                                 -- a saída, como o executor a produziu
  attempts int not null default 0,
  lease_run_id uuid, lease_expires_at timestamptz, fencing_token bigint not null default 0,
  version int not null default 1,
  unique (tenant_id, idempotency_key), unique (tenant_id, id), foreign key (tenant_id, queue) references work.queue,
  check (executor is not null or selector <> '{}'::jsonb));
create unique index job_exclusive on work.job (exclusive_key)  -- a exclusão mútua, imposta pelo banco
  where state in ('running','waiting') and exclusive_key is not null;
create table work.dependency (                                  -- um trabalho espera outro, do mesmo tenant
  tenant_id uuid not null, job_id uuid not null, depends_on uuid not null,
  condition text not null default 'succeeded' check (condition in ('succeeded','ended')),
  primary key (job_id, depends_on), check (job_id <> depends_on),
  foreign key (tenant_id, job_id) references work.job (tenant_id, id),
  foreign key (tenant_id, depends_on) references work.job (tenant_id, id));
create table work.run (                                         -- cada despacho do trabalho a um executor
  id uuid primary key default uuidv7(), job_id uuid not null references work.job, n int not null,
  executor text not null references work.executor, account text, external_id text,
  state text not null check (state in ('starting','running','waiting','ended')),
  outcome text check (outcome in ('succeeded','failed','timed_out','stopped','lost','cancelled')),
  error_type text, unique (job_id, n));                         -- o erro, como o adaptador o nomeou
create table work.limits (                                      -- o mecanismo de limite; o valor vem de quem o define
  id uuid primary key default uuidv7(), tenant_id uuid not null references work.tenant,
  scope text not null check (scope in ('tenant','executor','job')), scope_id text not null,
  meter text not null, maximum numeric not null check (maximum >= 0), used numeric not null default 0,
  action text not null check (action in ('stop','refuse')), unique (tenant_id, scope, scope_id, meter));
create table work.meter_rate (                                  -- converte um medidor em outro (tokens em dólares)
  tenant_id uuid not null references work.tenant, meter text not null, derived_meter text not null,
  rate numeric not null check (rate >= 0), primary key (tenant_id, meter, derived_meter));
create table work.result_cache (                                -- a saída de entrada idêntica, assinada pelo executor
  executor text not null references work.executor, input_digest text not null,
  result jsonb not null, signature bytea not null, stored_at timestamptz not null default now(),
  primary key (executor, input_digest));
create table log.event (                                        -- tudo o que a infraestrutura observa, bruto
  event_id text not null, tenant_id uuid references work.tenant, type text not null, occurred_at timestamptz not null,
  producer text not null, subject text not null, correlation_id text, causation_id text,
  payload jsonb not null, published_at timestamptz,
  primary key (occurred_at, event_id)) partition by range (occurred_at);
create table log.received (event_id text primary key, received_at timestamptz not null default now());
create table log.subscription (                                 -- o fluxo assinável, e até onde cada um já leu
  id uuid primary key default uuidv7(), tenant_id uuid not null references work.tenant,
  sink text not null, types text[] not null default '{}', read_until timestamptz,
  state text not null default 'active' check (state in ('active','paused')));
```

**Os mecanismos, em funções e gatilhos:** `work.next_job` escolhe o próximo trabalho pronto de uma fila pela política
dela (as dependências satisfeitas e o `not_before` passado); `work.route` resolve o executor exato ou o primeiro que o
seletor aceita e tem vaga, só entre os da instalação e os do próprio tenant; `work.finish_run` aplica a retentativa do
trabalho ao desfecho de uma execução, com a espera crescente, e redespacha sem contar tentativa quando o executor sumiu; e
quatro gatilhos: um executor privado serve só ao tenant dele; um trabalho novo não entra quando um limite de recusa já
passou; um uso relatado soma nos limites daquele medidor e dos medidores derivados pelo preço, e para o trabalho ao passar
um limite de parada; e só os tipos que a infraestrutura observa entram no registro.

**Das versões anteriores para cá:** o processo, a tentativa, a sessão, o fornecedor e a cota viram o trabalho, a execução,
o executor e a capacidade; o programa vira o tenant; saem o modelo de passos, `labels`, `annotations`, a chave do
programa, a espera com motivo, as visões de métrica, o custo em colunas e os eventos do programa; voltam como mecanismo
parametrizável (12:40) a ordenação, por fila e política; a retentativa; as dependências; o roteamento entre executores
aceitos; a retomada de uma espera; e o preço por medidor. O veredito por alvo vira o cache de resultado; a PR, o lote e a
prova saem para a gestão, e ficam a chave exclusiva, as dependências e o executor `forge`.

## 6. O teste de aceite

Três partes, as três executáveis:

1. **Estático: o vocabulário.** Os esquemas da infraestrutura são `work`, `log` e o `dbos`; nenhuma tabela, coluna ou
   visão deles nomeia gestão ou liderança (meta, objetivo, aposta, escolha, intenção, lição, hipótese, experimento,
   retrospectiva, auditoria, planejamento, padrão, premissa, decisão, domínio, programa, projeto, prioridade, solicitante,
   hierarquia), um campo de contexto (rótulo, anotação, contexto, modelo de passos), uma medida escolhida (métrica,
   painel, alerta, relatório, cobrança, custo, orçamento) ou um tipo de executor (agente, sessão, modelo de IA, prompt,
   fornecedor).
2. **Dinâmico: dois modelos de gestão, executores de vários tipos e políticas diferentes.** Rodou no PostgreSQL 18.6
   [M]:
   - o tenant `torre` tem uma gestão com metas e apostas, nas tabelas dela (`gestao_torre.processo`, com a chave `F135`,
     o objetivo e a aposta), que referenciam o trabalho pelo id; o tenant `livre` é de trabalhadores autônomos, sem meta e
     sem nenhuma tabela;
   - **o mesmo trabalho** (a mesma entrada) roda por um script num contêiner, sem nenhuma sessão de IA, e por uma sessão
     de IA, nas mesmas tabelas; um terceiro pedido do script, com `memoize`, sai do cache sem despacho;
   - **a mesma função de fila** escolhe o próximo pela maior `rank` numa fila de política `rank`, pela ordem de chegada
     numa `fifo` (mesmo com `rank` maior no segundo) e pelo prazo mais curto numa `deadline`, do outro tenant;
   - **o roteamento**: um trabalho que aceita duas sessões de IA, com a primeira sem vaga, vai para a segunda; um que pede
     um contêiner com acesso de root vai para o runner;
   - **a retentativa**: um trabalho de três tentativas volta à fila com espera de 10 s e de 20 s e falha na terceira; o
     padrão de uma tentativa falha na primeira; um erro marcado como não retentável falha logo; o executor que some
     redespacha sem contar tentativa;
   - **as dependências**: o pouso só fica pronto depois que as duas checagens terminam com sucesso;
   - **o preço por medidor**: com o preço do token dado de fora, 12 mil tokens viram US$ 0,036, e o limite de US$ 0,03
     para o trabalho;
   - os trabalhos do `livre` são executados por uma pessoa;
   - a gestão da Torre calcula, do registro bruto, quanto durou a auditoria que ela mesma pediu ao executor para marcar; a
     infraestrutura não sabe o que é auditoria;
   - são recusados: o executor privado do `livre` usado pela `torre`; um trabalho sem executor nem seletor; um trabalho
     novo além de um limite de recusa; dois pousos ao mesmo tempo no mesmo ramo; um evento de gestão
     (`torre.bet.accepted`) no registro da infraestrutura; a mesma chave de idempotência duas vezes;
   - o catálogo tem 13 tabelas nos esquemas `work` e `log` e nenhum nome proibido.
3. **De instalação.** Nenhum modelo em `infra/` fixa conta ou região, e todo valor da instalação chega por parâmetro (a
   D-304 e a D-306 na #265, seção 8).

Quando os serviços existirem, a parte 2 vira teste de contrato da porta, e a 1 ganha a regra de importação: nenhum módulo
da infraestrutura importa um da gestão.

## 7. Sem amarrar a uma conta, a um programa ou a um método

| Modo (11:45) | O que a fase 1 já faz | O que fica para depois |
|---|---|---|
| **Na conta de quem usa**, com as chaves dessa pessoa | a infraestrutura como código usa a conta e a região da pilha (`AWS::AccountId`, `AWS::Region`), e o repositório, a base e o e-mail de alerta são parâmetros; a chave de um fornecedor é um executor privado do tenant que a trouxe; o estado mora no que existe em qualquer nuvem (PostgreSQL, armazém de objetos, contêineres), e o que é só da AWS fica na borda, atrás de portas ([T4]) | o instalador, o guia para outra conta e os adaptadores de outra nuvem |
| **Gerenciada por nós**, com vários clientes | toda linha e todo evento levam o tenant; os limites são por tenant; o registro é assinável por tenant; um executor pode ser da instalação ou de um tenant só | o cadastro por conta própria, a cobrança (que é da gestão de quem vende), as políticas de linha por tenant [K10] e o isolamento por conta |

**Os executores da fase 1** são os que a fábrica já usa: o contêiner do runner, para scripts e checagens, a sessão de
agente pelas assinaturas e o forge. Uma pessoa, um modelo próprio ou uma IA por API entram como adaptadores novos, sem
mudar a infraestrutura.

**A instalação de hoje** é a nossa: a conta 123456789012, a região us-east-1, o orçamento `torre-motor-teto-60` de
US$ 60 (D-303), o repositório no Origin e o e-mail de alerta da Torre. São valores de uma instalação, registrados no
runbook da #265 (`docs/operations/aws.md`) e na D-303, e não da infraestrutura.

## 8. O que muda na #265

A #265 não tem DDL nem tabela: tem o bootstrap sem chave, o orçamento declarado e a pilha de rede, as três de
infraestrutura. O que entrou e o que entra:

1. **A D-304** (11:37 a 11:45): as três camadas e a infraestrutura agnóstica ao programa, ao método e à conta, com o teste
   que a prova: nenhum nome de gestão ou liderança nos modelos de `infra/aws`, só os esquemas da infraestrutura em
   qualquer SQL que chegar ali, nenhuma conta ou região fixa.
2. **O bootstrap com a região da pilha**, sem `us-east-1` escrito no modelo.
3. **A D-305** (12:05 e 12:08): a execução de trabalho como unidade, não a sessão de IA.
4. **A D-306** (12:19), a fronteira de Daniel, emendando as duas: os esquemas da infraestrutura passam a ser `work` e `log`
   (e o `dbos`); o teste recusa no SQL sob `infra/` também os campos de contexto, as medidas escolhidas e os nomes de
   gestão que a fronteira lista (meta, programa, projeto, prioridade, solicitante, hierarquia).
5. **O DDL vem na PR da pilha de dados**, só com as tabelas da seção 5, que passam na trava da D-306 sem nenhum
   problema. Ela traz também as decisões de 12:37 e 12:40 com a prova delas: o teste de aceite da seção 6. A pilha de
   dados é outra PR porque é outra unidade (o primeiro recurso pago, o banco e o DDL da infraestrutura), não por um
   contador de plano; uma correção do bootstrap, da rede ou das travas continua na #265.

Uma peça do bootstrap fica com o nome antigo: o tópico `tower-alerts`, que na fronteira é o fluxo de eventos da
plataforma, assinável por quem quiser. Trocar o nome agora recriaria o tópico e as assinaturas dele no meio da
atualização que a Torre tem pendente; ele muda quando o bootstrap mudar por outro motivo.

## 9. As fases 2 e 3

| Fase | O que é | Insumo já pronto | Como liga à infraestrutura |
|---|---|---|---|
| **2. Gestão** | um sistema próprio, com esquema, tabelas e lógica dele: no nosso caso, o objetivo, a aposta, a escolha e o planejador; o processo, as etapas e o plano de commits; o padrão e os briefs; que checagens provam uma PR, quando pousar e em que lote; que executor usar para que trabalho; as métricas, os painéis e os alertas; as premissas; o aprendizado. Outro sistema de gestão pode não ter nada disso | [17](17-ciclo-do-processo.md), [19 §3 a §5 e §8](19-direcao-ideal.md#3-as-entidades-da-direção), [20](20-sistema-de-aprendizado.md), [21 §4 a §6](21-revisao-geral.md#4-a-medição), o desenho de [11](11-gate-merge-fila-origin.md) como política de integração, as fontes N e L | cria trabalhos, define limites e executores, assina e lê o registro; guarda o que é dele nas tabelas dele, com o id do trabalho |
| **3. Liderança** | a intenção com a trava, a métrica-norte, os limites e a autoridade, o canal com a Torre, as decisões | [19 §6 e §7](19-direcao-ideal.md#6-a-governança), a [SEMENTE](../SEMENTE.md), o Falconi [N17] | fala só com a gestão |

**O que fica aberto para as fases 2 e 3:** se a gestão de hoje (o METODO, o padrão v8, a SEMENTE e as ferramentas de gate
e de trem) vira o primeiro sistema de gestão sobre a infraestrutura como está ou já na forma de 19 e 20; e se a
métrica-norte é a janela de autonomia, que é de Daniel ([19 §7](19-direcao-ideal.md#7-a-medição-da-direção)). Nenhuma das
duas respostas muda a infraestrutura.

## 10. O teste de escala

| | A 1 PR/min | A 1 PR/s | A forma muda? |
|---|---|---|---|
| tenants | um, o nosso | vários, cada um com os seus limites | não: o tenant já está em toda linha |
| executores | o contêiner do runner, as sessões pelas assinaturas, o forge | mais tipos e mais contas, cada um com a sua capacidade | não: um executor novo é uma linha e um adaptador |
| trabalhos | ~3 por PR (o de código, as checagens que o cache não resolve, o pouso) | ~11 mil por hora | não; a fila é um índice parcial por tenant e fila |
| filas e políticas | uma ou duas filas, ordem de chegada | as que a gestão quiser, cada uma com o seu módulo de ordenação | não: uma política nova é um módulo plugado, sem mudar as tabelas |
| registro | algumas dezenas de eventos por PR | ~100 mil por hora, partição por mês | não; quem lê muito assina o fluxo em vez de consultar |
| limites | poucos, do tenant | os mesmos, mais os de cada trabalho que a gestão quiser | não |
