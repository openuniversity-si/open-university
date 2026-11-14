# 13. Estado e coordenação fora do repositório

> **Referência e histórico.** A fonte da verdade da fase 1 é a [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano
> para implementá-la está no [plano de implementação](PLANO-DE-IMPLEMENTACAO.md); onde este documento divergir dela,
> vale ela.

> **Na fronteira de 12:19** ([22 §3](22-tres-camadas.md#3-o-inventário-peça-por-peça)): infraestrutura: o banco de
> execução, a orquestração durável e a escolha do PostgreSQL. Da tabela de §1, o que não é trabalho (as decisões, as
> premissas, as lições, a fila, o diário, os atritos) é estado da gestão ou da liderança, no sistema delas; as tabelas
> de §6 derivam agora de [22 §5](22-tres-camadas.md#5-as-tabelas-da-infraestrutura).

Responde à classe K3 de [09](09-avaliacao-10-0.md) e ao pedido de Daniel: o estado hoje é "código escrevendo em cima de
código e tudo mergeado". A regra do estado da arte é simples: **o git guarda o estado desejado; um banco guarda o
estado de execução; um armazém de objetos guarda os artefatos.** É a divisão do GitOps, em que o repositório declara o
que se quer e os controladores mantêm o que acontece num banco próprio (no Kubernetes, o etcd). O git é ótimo para o
que muda pouco, precisa de revisão e de história; é ruim para o que muda muitas vezes por minuto, precisa de transação,
de índice e de leitura barata.

## 1. O que fica em git e o que sai

| Estado de hoje | Onde está | Natureza | Para onde vai |
|---|---|---|---|
| código, testes, scripts | git | desejado | **fica em git** |
| contratos (`contracts/`) e manifestos de unidade (`units/<id>/unit.json`) | git | desejado | **fica em git** |
| registro de configuração: valores padrão por chave (`config/registry/`) | git | desejado | **fica em git**; muda por PR, como hoje |
| decisões (`docs/domain/DECISIONS.md`), premissas, a semente, o padrão, os documentos de unidade, programa e projeto | git | conhecimento | **fica em git** |
| narrativa dos incidentes (caso, classe, desenho) | git (`docs/operations/incidents/`) | conhecimento | **fica em git** como relato; o estado aberto ou fechado vai para o banco |
| a fila de unidades de trabalho (linhas `F<n>`) | git ([fila](../programs/vazao/fila.md)), mergeada por PR | execução | **banco**: a tabela de processos do modelo de [16](16-modelo-de-dominio.md), com o contrato de [12](12-unidade-e-sessoes.md) |
| claims e posse em voo de cada lane | arquivos e convenção | execução | **banco**: o lease do processo, com fencing token ([16 §5.5](16-modelo-de-dominio.md#55-regras-que-valem-para-todas-as-entidades)) |
| o diário do motor e o log de eventos | git-ref no Origin (D-300) | execução | **banco**: tabela de eventos só de anexo, com stream para o barramento |
| a prova do gate | git-ref e `.dev.pass` | execução | **banco** (veredito) e **forge** (check run do app no head exato) |
| sobreposições de configuração em tempo de execução (`config.changed`) | arquivo por checkout ou o Durable Object | execução | **banco**: tabela de sobreposições com autor, motivo e reversão; o padrão continua no registro em git |
| a fila da caixa (`pr-N.json`) e a trava de kernel | pasta e `flock` na caixa | execução | **banco** (estado da fila e lease do lote) |
| heartbeats do push guard, fricções, livro de cada lane | arquivos locais | execução | **banco** |
| lições (`scripts/lessons`) | journal no control plane | execução, até virar padrão | **banco**; a promoção a padrão continua por PR |
| relatórios e logs completos do gate | `.gate/records/` local, fora do git | artefato | **armazém de objetos**, com retenção |
| o cache de resultados por conteúdo | disco da caixa e de cada sessão | artefato | **armazém de objetos**: só os runners escrevem, as sessões só leem |

O que essa divisão elimina: o merge de PR só para mudar estado, os conflitos entre sessões que escrevem o mesmo arquivo
de fila, as janelas de log que perdem o snapshot (I-f080dca5) e as leituras sem orçamento do Durable Object
(I-5102f4e9).

## 2. O que o banco de estado precisa ter

| Requisito | Por quê | Meta a 1 PR/s |
|---|---|---|
| escrita condicional (compare-and-set) | leases, claims e transições de estado sem corrida | toda transição é condicional |
| leitura por chave e por índice | o leitor paga o que precisa, nunca uma janela inteira (a lição de I-5102f4e9) | p99 ≤ 20 ms |
| stream de mudanças | o evento sai do banco para o barramento sem um segundo escritor (outbox) | atraso p99 ≤ 1 s |
| expiração automática (TTL) | eventos e heartbeats velhos saem sem trabalho manual | sim |
| durabilidade e réplica gerenciadas | nenhuma máquina de estimação (R0-11) | backup contínuo a 1 PR/min; réplica em outra zona a partir de 0,1 PR/s |
| volume | ~20 eventos e ~30 escritas por PR | a 1 PR/min, ~0,5 escrita/s e 43.200 PRs por mês; a 1 PR/s, ~30 escritas/s, ~75 leituras/s e ~2,6 milhões de PRs por mês |
| consulta analítica | a medida de vazão, guardas e custo por PR | exportação para consulta (SQL sobre o armazém de objetos, ou réplica relacional) |

## 3. O banco de estado, comparado

Custo mensal a 1 PR/s para a carga de referência (por PR: 20 escritas de até 1 KB, 50 leituras), com os preços de
nov/2026 [C39, C41, C45, C49] e as contas da pesquisa [I]:

| Opção | Escrita condicional e transação | Consulta | Stream de mudanças | Gerenciado | Custo a 1 PR/s | Franquia grátis | Encaixe no motor |
|---|---|---|---|---|---|---|---|
| **RDS PostgreSQL Multi-AZ** (db.t4g.medium, 100 GB) | sim | SQL completo | replicação lógica, `LISTEN/NOTIFY`, outbox | sim | ~US$ 116 | — | **alto**: os testes do motor já rodam em PostgreSQL 18; o mesmo banco serve de fila e de workflow (seção 4) |
| Aurora Serverless v2 (PostgreSQL) | sim | SQL | idem | sim, escala sozinho, pode pausar | ~US$ 133 (1 ACU em média) | — | alto |
| DynamoDB sob demanda | sim (condicional, transações) | chave e índices secundários | DynamoDB Streams | sem servidor | ~US$ 49 + armazenamento | 25 GB; a capacidade provisionada grátis (25 escritas/s) quase cobre 1 PR/s | médio: modelo de dados novo, métricas por exportação |
| Aurora DSQL | sim | SQL compatível com PostgreSQL, com restrições | — | sem servidor | dezenas de dólares (0,05 DPU por escrita de 1 KB) | 100 mil DPU e 1 GB | médio: a verificar com a biblioteca de workflow |
| Firestore (Google) | transações | índices | gatilhos por Eventarc | sem servidor | ~US$ 85 | 20 mil escritas/dia (1,2 % de 1 PR/s) | médio |
| Durable Objects e D1 no Workers Paid | sim, objeto de uma thread | SQLite por objeto | — | sem servidor | ~US$ 60–100 | o plano grátis é o que falhou (I-5102f4e9) | o motor de hoje |
| Postgres numa caixa própria | sim | SQL | idem | não (máquina de estimação) | o preço da caixa | — | rápido de montar, viola R0-11 |

## 4. A orquestração durável, comparada

| Opção | Onde o estado do workflow mora | Custo a 1 PR/s (15 passos por PR) | Observação |
|---|---|---|---|
| **DBOS** (biblioteca Python) | no mesmo Postgres | US$ 0 além do banco | "sem servidor de orquestração separado"; ~1.000 passos/s por vCPU do Postgres [C44]; a 1 PR/s são 15 passos/s |
| Temporal autogerido | Postgres e OpenSearch próprios | ~US$ 90 a mais (2 hosts e OpenSearch) | o padrão mais usado; mais peças para operar [C43] |
| Temporal Cloud | no serviço | ~US$ 2.039 | 41 milhões de ações por mês [C43] |
| AWS Step Functions Standard | no serviço | ~US$ 972 | espera por token só no Standard [C35] |
| AWS Lambda com funções duráveis | no serviço | ~US$ 321 + computação | lançado em dez/2025; espera até 1 ano sem cobrar computação [C37] |
| Google Workflows | no serviço | ~US$ 389 | [C49] |
| Cloudflare Workflows | no serviço | ~US$ 307 | [C45] |

## 5. A escolha

**PostgreSQL gerenciado (RDS: db.t4g.micro numa zona a 1 PR/min, Multi-AZ a partir de 0,1 PR/s) como banco de
estado, com os workflows e as filas em Python pela biblioteca DBOS no mesmo banco, e o S3 para artefatos e cache.**
Por quê:

1. **O mesmo que o motor já usa.** O toolchain fixado do motor já sobe PostgreSQL 18.6 para os testes; o banco de
   produção é o mesmo tipo de banco, e o que roda no teste roda na nuvem, como o motor exige ([AGENTS.md](../../AGENTS.md),
   D-069 item 12).
2. **Uma peça a menos.** O workflow e a fila moram no banco; não há servidor de orquestração para manter (seção 4) e a
   1 PR/s a carga é ~1,5 % do que uma vCPU de Postgres processa, pelo número do próprio fornecedor [C44].
3. **SQL para medir.** Vazão, latência por estágio, vermelho, flake e custo por PR viram consultas e visões, a
   generalização direta de `scripts/flow-metrics`.
4. **Portável pela porta.** Qualquer Postgres serve: RDS, Aurora, Cloud SQL, um local; a troca é de adaptador.
5. **Barato.** ~US$ 14/mês a 1 PR/min e ~US$ 116 a 1 PR/s para o banco; o orquestrador não custa à parte.
6. **Aguenta o modelo mudar.** Num banco relacional o modelo é criado agora e estendido depois; no DynamoDB, o esquema
   não deve ser desenhado antes de se conhecerem as perguntas [C53]. O modelo de domínio está sendo refinado
   ([16](16-modelo-de-dominio.md)), e cada refino é uma migração versionada.

**A alternativa sem servidor** é DynamoDB com Lambda de funções duráveis ou Step Functions; custa mais no orquestrador
(US$ 321 a 972/mês só nele) e pede um modelo de dados novo, mas não tem nem o banco para dimensionar. Fica como opção A2
em [10](10-arquitetura-10-0.md).

**O que fica na porta.** O motor já fala com o estado por portas (a porta de eventos `forge_events`, o armazém de
configuração, o armazenamento do cache). A migração ([14](14-custos-e-migracao.md)) acrescenta um adaptador de banco a
cada uma, roda em sombra e só então desliga o adaptador de arquivo e de git-ref.

## 6. As tabelas derivam do modelo de domínio

As tabelas, os eventos e os workflows não são desenhados aqui: derivam do modelo refinado de
[16](16-modelo-de-dominio.md), um esquema do PostgreSQL por contexto (direção, trabalho, execução, integração,
verificação, conhecimento e eventos) e uma tabela por agregado, com o núcleo já rodado no PostgreSQL 18.6 do toolchain
([16 §7.1](16-modelo-de-dominio.md#71-tabelas)). A divisão desta página continua valendo: o que é desejado e precisa de
revisão fica em git; o estado de cada agregado, os leases e os eventos ficam no banco.
