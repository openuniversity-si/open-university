# 04. Componentes: estado da arte, comprar, construir e teto

> **Referência.** A arquitetura de 10^9 PRs/s é o horizonte; a fonte da verdade da fase 1 é a
> [arquitetura-alvo](ARQUITETURA-ALVO.md), e o plano para implementá-la, o [plano de implementação](PLANO-DE-IMPLEMENTACAO.md).

Entregável 3. Para cada componente de [03](03-arquitetura.md): o estado da arte que já resolve (com fonte), o que se
compra ou se usa pronto, o que a Torre teria que construir, o teto real (por unidade e o maior já demonstrado) e quantas
unidades a meta de [01 §6](01-requisitos.md#6-padrões-de-performance-por-componente-109) exige a 10^9 PRs/s. As
unidades são conta [I] sobre a fonte citada, com ρ = 0,75 já embutido nas metas. "Núcleo" é vCPU de nuvem.

## 1. S1 Decidir

| Componente | Estado da arte que já resolve | Comprar ou usar pronto | Construir | Teto real | Meta a 10^9 e unidades |
|---|---|---|---|---|---|
| C01 Registro de intenções | qualquer banco transacional; o motor usa a fila em arquivo ([fila](../programs/vazao/fila.md)) | FoundationDB, Spanner, Postgres | o esquema de intenção com orçamento | FoundationDB: dezenas de milhares de commits/s por cluster [S22] | ≤ 10^2/s: uma fração de um cluster, o mesmo de C19 |
| C02 Planejador (contrato) | o Rosie do Google divide mudanças em larga escala por dono e faz "milhares de mudanças por dia" [S3]; migrações com LLM no Google: 595 mudanças em 12 meses, 74 % das edições pela IA [V28], 80 % na migração de int32 para int64 [V29]; a busca de programas do AlphaEvolve [A24] | nada que gere decisões amplificadas | **tudo** (é a inovação da Torre; contrato em [06](06-contrato-planejador.md)) | nenhum sistema publicado gera decisões com A ≥ 10^6 a mais de 1 por segundo | 1,33 × 10^3 decisões/s; as unidades são as de C06 |
| C03 Instruções da IA (contrato) | instruções versionadas no repositório, como o AGENTS.md e o padrão do motor ([padrao](../padrao/README.md)); prefixo compartilhado barato por cache de prompt: leitura de cache a 1/20 do preço de entrada no Sonnet e no Opus 5.5 [A5] | o cache de prompt dos provedores | **o conteúdo** (inovação da Torre) e o versionamento por conteúdo | sem teto relevante; ~94 % dos tokens de uma sessão de agente já são leitura de cache [A9] | uma versão endereçada por conteúdo por decisão; leitura p99 ≤ 10 ms |
| C04 Índice de código | Zoekt: menos de 50 ms sobre ~2 GB de texto numa máquina, RAM de ~1,2× o corpus [V37]; Glean guarda fatos sobre o código em escala [V38] | Zoekt e Glean (código aberto); Sourcegraph (comercial) | índice particionado por célula, frescor ≤ 10 s, predicados semânticos (tipos, referências) | uma máquina por ~2 GB a 50 ms por consulta; a frota cresce com o tamanho do corpus, não com a vazão | ≈ corpus × 1,2 ÷ RAM por máquina: ~240 máquinas de 512 GB para 100 TB de código [I] |
| C05 Admissão e orçamento | balde de tokens contra retries do gRPC [C31]; o controle de admissão do Envoy, com a fórmula do capítulo de sobrecarga do livro de SRE [C32]; a prioridade e justiça da API do Kubernetes por shuffle sharding [C33] | Envoy, gRPC, APF do Kubernetes | o razão de orçamento em tokens, núcleo·s e dinheiro por intenção e decisão | µs por decisão de admissão | ≥ 10^5 admissões/s: alguns núcleos |

## 2. S2 Gerar

| Componente | Estado da arte que já resolve | Comprar ou usar pronto | Construir | Teto real | Meta a 10^9 e unidades |
|---|---|---|---|---|---|
| C06 Malha de inferência | a frota da DeepSeek serviu 776 bilhões de tokens/dia (~9 × 10^6/s) em 226,75 nós H800 em média, ~4.950 tokens/s por GPU [A1, I]; SGLang: 52,3 mil tokens/s de entrada e 22,3 mil de saída por nó H100 [A2]; GB200: 26 mil e 13 mil por GPU [A3]; contexto de 128K cai ~60× [A4]; lote com 50 % de desconto [A5, A6] | APIs (Anthropic, Google, OpenAI) e modelos abertos em vLLM ou SGLang sobre GPUs alugadas (US$ 4,95–6,6 por GPU·h spot [A8]) | roteamento entre provedores, lote, cache, cotas e medição por decisão | o maior volume publicado de um provedor: o Google, ~1,2 × 10^9 tokens/s no total [A14]; o estoque mundial é ~29,1 milhões de H100-equivalentes [A16] | 1,5 × 10^8 tokens/s ≈ 3 × 10^4 H100-equivalentes à taxa da DeepSeek (0,1 % do estoque mundial) [I], ou ~12 % do volume do Google de mai/2026 por API |
| C07 Runtime de agentes em sandbox | Firecracker: ≤ 125 ms de boot, ≤ 5 MiB por VM [X1], 150 microVMs/s por host [X2]; gVisor [X7]; Daytona cria sandbox em menos de 90 ms (fornecedor) [X6]; o Lambda fez 1,7 trilhão de invocações num dia [X3] | Firecracker e gVisor (código aberto); serviços de sandbox | pool por região com restauração de snapshot, saída por lista, identidade por sessão | 150 criações/s por host | 1,33 × 10^3 sessões novas/s ≈ 9 hosts de criação; 4 × 10^5 sessões simultâneas de ~2 GB [E] ≈ 800 TB de RAM ≈ 1,6 × 10^3 hosts de 512 GB [I] |
| C08 Motor de transformação | o Rosie e o ClangMR aplicam uma mudança no monorepo inteiro do Google [S3]; árvores semânticas sem perda do OpenRewrite [V33]; Piranha: 65 % dos diffs entraram sem mudança [V31]; PolyglotPiranha: 1.611 PRs [V32]; uma busca estrutural do ast-grep custa ~86 µs por arquivo (benchmark do autor) [V36] | OpenRewrite/Moderne, Semgrep, Comby, ast-grep, Piranha | o executor paralelo de dados por célula sobre árvores já em memória, determinístico, e a linguagem da transformação com semântica verificável | ~86 µs por arquivo com parse [V36]: ~1,2 × 10^4 arquivos/s por núcleo [I] | ≤ 10 µs·núcleo por instância com a árvore em memória → 1,5 × 10^4 núcleos; a 86 µs seriam 1,3 × 10^5 [I] |
| C09 Cache de derivação | Action Cache e CAS da API de execução remota [V6]; NativeLink: mais de 10^9 requisições por mês (fornecedor) [V7]; eRPC: ~10^7 RPCs/s por núcleo [X23] | servidores da API de execução remota (Buildbarn, BuildBuddy, EngFlow, NativeLink) | o cache local da célula com chave H(programa, lugar, base, toolchain) | ~10^7 consultas/s por núcleo no piso de RPC [X23] | 1,5 × 10^9 consultas/s ≈ 150 núcleos no piso, ~1,5 × 10^3 a 10^6 consultas/s por núcleo [I] |

## 3. S3 Verificar

| Componente | Estado da arte que já resolve | Comprar ou usar pronto | Construir | Teto real | Meta a 10^9 e unidades |
|---|---|---|---|---|---|
| C10 Certificador de decisões | o Alive prova cada reescrita do LLVM uma vez para todos os tipos e larguras [V19]; o Alive2 valida traduções e achou 47 bugs [V20]; o Zelkova da AWS roda ~10^9 consultas SMT por dia, de 0,2 s a dezenas de segundos cada [V15]; o Cedar combina modelo em Lean com testes diferenciais [V17]; o s2n reexecuta provas em todo push [V18]; o seL4 custou ~12 pessoas-ano para 8.700 linhas [V22] | solucionadores SMT, Lean e Dafny, Alive2, testes de propriedade | o formato do certificado, a ponte da prova para as classes de lugar e as provas escritas pela IA | ~1,2 × 10^4 consultas SMT/s no Zelkova [I sobre V15]; **ninguém certifica transformações gerais de código a 10^3/s** | 1,33 × 10^3 decisões/s × ≤ 500 núcleo·s ≈ 6,7 × 10^5 núcleos; classe **pesquisa** |
| C11 Gate V0 | a conferência é em memória: chamada de sistema ~100 ns, troca de contexto ~1 µs [X22], leitura de L1 ~0,5 ns e de memória ~100 ns [X21] | nada; é código da célula | o verificador: pré-condição, conjunto de escrita, tamanho, padrões proibidos, classe do certificado | físico: 10^3 a 10^4 instruções por conferência são 0,3 a 3 µs a 3,9–4,5 GHz [X25, I] | 1 µs → 1,5 × 10^3 núcleos [I] |
| C12 Verificação incremental V1 | build incremental com cache por conteúdo (Bazel, Buck2 com execução remota primeiro [V5], a API de execução remota [V6]); o motor já chega a 0,99 s por PR com resultados compartilhados [M] | Bazel, Buck2, Pants | a ligação de V1 com a classe de certificado e com a amostra | o custo por arquivo de uma checagem de tipos incremental não foi verificado nesta sessão (lacuna) | 1 ms·núcleo em 1 % das instâncias → 1,5 × 10^4 núcleos [I] |
| C13 Execução remota V2 | o serviço de build do Google faz mais de 15 milhões de builds por dia [V4]; o TAP roda mais de 4 bilhões de testes por dia [S4]; a seleção preditiva da Meta corta metade do custo e ainda aponta mais de 99,9 % das mudanças com defeito [V8]; 1,5 % das execuções de teste são instáveis no Google [V13] | Bazel/Buck2/Pants com a API de execução remota; BuildBuddy, EngFlow | o modelo de seleção treinado no próprio histórico [V8, V3] e a política de amostragem | ~174 builds/s e ~4,6 × 10^4 testes/s no Google [I sobre V4, S4] | 6,7 × 10^4 instâncias amostradas/s × ≤ 10 núcleo·s ≈ 6,7 × 10^5 núcleos: uma frota da ordem do TAP [I] |
| C14 Verificação contínua V3 e rollback | o TAP agrupa mais de 50 mil mudanças por dia em lotes [S4]; achar o culpado com testes instáveis [V11]; teste especulativo: 25 % dos alvos dão 85 % da detecção, p50 de 107 para 37 min [V3]; lote de 4 corta até 75 % das execuções [V9]; o ótimo de Dorfman, lote ≈ 1/√p [V12]; o CQ do Chromium reaproveita builds verdes por até 800 commits [S13] | nada como produto; os algoritmos são publicados | **o que testar** quando entram 10^9 mudanças por segundo; a bisseção por decisão | ~0,6 mudança/s com teste contínuo no Google [I sobre S4] | ≤ 4,5 × 10^5 núcleos; detecção p50 ≤ 10 min (o melhor publicado é 37 min [V3]); classe **pesquisa** |
| C15 Política e análise estática | Infer: 70 % das falhas apontadas no diff são corrigidas, contra ~0 % em lote [V23]; Tricorder [V24]; o Zelkova avalia políticas por SMT [V15]; o Cedar é uma linguagem de política verificada [V17] | Cedar, OPA, Infer, CodeQL, Semgrep | as políticas da fábrica | 10^9 checagens por dia no Zelkova [V15] | ≥ 10^5 avaliações/s; ≤ 100 núcleo·s de análise por decisão, dentro dos 500 da certificação de C10 [I] |

## 4. S4 Gravar

| Componente | Estado da arte que já resolve | Comprar ou usar pronto | Construir | Teto real | Meta a 10^9 e unidades |
|---|---|---|---|---|---|
| C16 Ledger particionado | Kafka no LinkedIn: mais de 7 × 10^12 mensagens/dia, mais de 4 mil brokers, 7 milhões de partições [C7]; 2 milhões de escritas/s em 3 brokers [C8]; 2 milhões de partições testadas com KRaft [C9]; exatamente uma vez custa 3–5 % [C10]; o Scribe da Meta ingere mais de 15 TB/s [C11] | Kafka/Confluent, Redpanda, Pulsar, Kinesis | o esquema do registro, a integração com o sequenciador e a idempotência pela identidade da instância | ~6,7 × 10^5 escritas/s por broker em benchmark e ~2 × 10^4 na média do LinkedIn [I sobre C7, C8]; 15 TB/s no agregado [C11] | 1,33 × 10^9 anexos/s × 128 B = 170 GB/s, ~1,1 % do Scribe; com lotes de 100 ms o broker move bytes: supondo ~300 MB/s por broker [E], ~600 brokers sem contar a réplica e ~2.000 com 3 réplicas; 10^4 partições, muito abaixo dos 2 milhões testados [I] |
| C17 Armazém por conteúdo | S3: mais de 500 × 10^12 objetos, mais de 2 × 10^8 requisições/s, ao menos 3.500 escritas/s por prefixo [C19]; US$ 0,021–0,023 por GB·mês [X27] | S3, GCS, R2; Ceph ou MinIO próprios | empacotar os blobs de cada snapshot (como os packfiles do git), coleta de lixo e compactação | 2 × 10^8 requisições/s no S3 [C19] | 200 B quentes por PR = 200 GB/s ≈ 17 PB/dia; 7 dias quentes ≈ 120 PB ≈ US$ 2,5 milhões/mês [I] |
| C18 Materializador de snapshots | o modelo de objetos do git; o pushrebase do Mononoke [S5]; o reftable tem um escritor por vez por repositório [S18]; o Google faz 60–70 mil commits por dia útil num repositório [S2] | bibliotecas de git; Mononoke (código disponível) | o construtor de snapshot por partição e o corte global | um escritor por repositório [S18] | 10^4 commits/s espalhados em 10^4 partições: 1 por partição por segundo, dentro do limite serial de cada uma [I] |
| C19 Metadados consistentes | FoundationDB: 8,2 milhões de operações/s em 384 processos, commit em 1,5–2,5 ms [S22], escala quase linear de 4 para 24 máquinas [C21]; Spanner: mais de 6 × 10^9 consultas/s no pico [C16], com `max_commit_delay` para trocar latência por vazão [S23]; DynamoDB: 1,92 × 10^8 requisições/s no Prime Day 2026 [C18], 1.000 unidades de escrita por partição [C17]; Calvin: ~500 mil transações/s em ~100 nós [C22] | FoundationDB, Spanner, DynamoDB, CockroachDB | o esquema de cabeças, estados de decisão e claims | dezenas de milhares de commits/s por cluster FoundationDB [S22] | 10^6 transações/s ≈ 40 a 100 clusters FoundationDB, ou ~0,5 % do pico do DynamoDB [I] |
| C20 Espelho de forge | Origin: 600, 3.000 ou 6.000 pontos/min, merge a 10 pontos [S21, M]; o GitHub recomenda ≤ 1 PR mergeada/min por repositório [S14] e limita a 80 requisições que criam conteúdo por minuto [S20] | o Origin, o GitHub | as PRs-resumo por intenção e as amostras | < 1 PR/s com folga ([02](02-estado-atual.md)) | ≤ 50 % da cota em todo degrau; a 10^9 só resumos e amostras |

## 5. S5 Coordenar

| Componente | Estado da arte que já resolve | Comprar ou usar pronto | Construir | Teto real | Meta a 10^9 e unidades |
|---|---|---|---|---|---|
| C21 Barramento de eventos | Kafka [C7, C8]; SQS de alta vazão até 70 mil TPS por ação [C12]; Kinesis 1.000 registros/s por shard [C13]; Cloudflare Queues 5.000 mensagens/s por fila [C6] | Kafka, SQS, Kinesis, Pub/Sub | o envelope do motor de hoje ([contracts/events/envelope.v1.json](../../contracts/events/envelope.v1.json)) | ~6,7 × 10^5 mensagens/s por broker em benchmark [I sobre C8] | 1,33 × 10^6 eventos/s: 2 a 70 brokers [I] |
| C22 Orquestrador durável | Temporal Cloud: 500 ações/s por namespace por padrão, até 6.000 [C23]; o Cadence da Uber: ~10^5 atualizações de workflow/s em ~30 clusters [C24]; Step Functions Express lançado para até 10^5/s [C25] | Temporal, Cadence | os workflows de decisão (ondas, parada, rollback) | ~10^5 transições/s no maior parque publicado [C24] | 6,7 × 10^4 transições/s ≈ 12 a 134 namespaces do Temporal, ~0,7 do parque da Uber [I] |
| C23 Escalonador de lotes | Kubernetes: 5.000 nós e 150 mil pods por cluster [C26], 680–1.100 pods/s no escalonador [C27]; uma célula Borg de 12,5 mil máquinas [C28]; Ray: mais de 10^6 tarefas na fila de um nó [C29]; Spark ordenou 100 TB em 23 min em 206 máquinas [C30] | Kubernetes, Ray | despacho por **puxada**: trabalhadores de vida longa por célula tiram lotes do log, e o escalonador só posiciona trabalhadores | ~1.100 posicionamentos/s por cluster [C27] | 1,33 × 10^5 tiradas de lote/s pelos grupos de consumo do log (C16) + ≤ 10^3 posicionamentos/s; ≥ 7 clusters de 5.000 nós de 64 vCPU [E] para 2 × 10^6 núcleos, mais por isolamento de célula [I] |
| C24 Conflitos e claims | o pushrebase do Mononoke valida e repete até 100 vezes [S5]; o compare-and-swap de ref do git [S19]; posse de unidade por lane no motor (P-13) | sobre C19 | a tabela de claims por partição e faixa com lease | uma chave quente aguenta ~10^5 leituras/s no FoundationDB [S22] | 1,33 × 10^6 operações/s; com os claims locais de cada célula, ~10^3/s por célula [I] |
| C25 Sequenciador de partição | a janela especulativa do Zuul (20, piso 3) [S10]; a fila de merge do GitHub (até 100 builds e 100 PRs por merge) [S11]; os trens do GitLab (20 pipelines) [S12]; a ordem determinística do Calvin [C22] | nada faz validação otimista por conjunto de escrita para código nessa taxa | o sequenciador sobre o log, com lote de 100 ms | nenhuma fila de merge publica teto em PRs/s; todas limitam paralelismo | 1,33 × 10^5 PRs/s por partição a ≤ 1 µs·núcleo: 0,13 núcleo por partição, ~1,3 × 10^3 no total [I] |
| C26 Plano de controle | o registro de configuração do motor (um arquivo por chave, agregados gerados); shuffle sharding [C33]; células [X20] | etcd, FoundationDB ou Spanner para configuração; Envoy | o mapa de partições e a gestão de células | dezenas de milhares de commits/s por cluster FoundationDB [S22], muito acima da necessidade | ≤ 10 escritas/s |

## 6. S6 Transversais

| Componente | Estado da arte que já resolve | Comprar ou usar pronto | Construir | Teto real | Meta a 10^9 e unidades |
|---|---|---|---|---|---|
| C27 Observabilidade e custo | o Monarch ingere terabytes por segundo [C15]; o Dapper: span de ~200 ns, amostragem de 1/1024 com −0,20 % de latência [X16]; OpenTelemetry v1.62 com traços, logs e API de métricas estáveis [X17]; orçamento de erro = 100 % − SLO [X18] | coletores OpenTelemetry e um banco de séries temporais | a medida de vazão, guardas e custo por PR lida do ledger (a generalização de `scripts/flow-metrics`) | terabytes/s no Monarch [C15] | 10^7 pontos/s e 10^3 traços/s: pequeno perto do Monarch |
| C28 Segurança e proveniência | SLSA v1.0 com build L0–L3 e v1.2 com fonte L1–L4 [X8]; in-toto graduado na CNCF [X9]; o Rekor com mais de 101 milhões de entradas [X10]; Binary Authorization for Borg [X11]; OWASP para LLMs [X12]; CaMeL [X13]; padrões de desenho contra injeção [X14]; a tríade letal [X15] | Sigstore, in-toto, Firecracker, gVisor | a separação entre controle e dados dos agentes e a assinatura por snapshot e por decisão | o Rekor inteiro (~1,01 × 10^8 entradas) equivale a 0,1 s da fábrica a 10^9 [I]: log por PR é impossível | assinar e registrar 10^4 snapshots/s e 1,33 × 10^3 decisões/s; cada PR entra pela prova de inclusão Merkle no snapshot assinado [I] |
| C29 Confiabilidade | células da AWS [X20]; shuffle sharding: o Route 53 usa 2.048 servidores virtuais em grupos de 4, ~7,3 × 10^11 combinações [C33]; o FoundationDB simulou ~1 trilhão de horas de CPU [X19]; chaves de idempotência [C34] | Envoy, gRPC, Infima | a simulação determinística da própria fábrica e o teste de caos por célula | o maior uso publicado: ~7,3 × 10^11 combinações de shuffle sharding no Route 53 [C33] e ~10^12 horas de CPU simuladas no FoundationDB [X19] | ≥ 10^3 células; falha de uma célula custa ≤ 1/N da vazão |

## 7. A frota a 10^9

A soma das metas de unidade acima, para mostrar o tamanho do que se compra [I]:

| Recurso | Quantidade a 10^9 | Maior parte em | Comparação com o maior já demonstrado |
|---|---|---|---|
| Núcleos (vCPU) | ~2,1 × 10^6 | C10 com C15 6,7 × 10^5; C13 6,7 × 10^5; C14 4,5 × 10^5; C07 ~10^5; o resto (C04, C08, C09, C11, C12, C16, C19, C21–C25, C27) ~2 × 10^5 | a amostra V2 sozinha tem a ordem do TAP do Google [S4] |
| GPUs | ~3 × 10^4 H100-equivalentes | C06 | 0,1 % do estoque mundial [A16]; a frota inteira da DeepSeek tinha ~1.800 GPUs [A1] |
| Ledger | 170 GB/s, ~10^3 brokers | C16 | ~1,1 % da ingestão do Scribe [C11] |
| Armazenamento quente | ~120 PB (7 dias) | C17 | — |
| Transações de metadados | 10^6/s | C19, C24 | ~0,5 % do pico do DynamoDB [C18] |
| Workflows | 6,7 × 10^4 transições/s | C22 | ~0,7 do parque do Cadence na Uber [C24] |

## 8. Comprar e construir

- **Compra-se ou usa-se pronto** a maior parte da máquina: inferência (API ou modelo aberto em GPU alugada), sandboxes,
  motores de reescrita, execução remota de build, ledger, armazenamento, metadados, barramento, workflow, escalonador,
  política, observabilidade, assinatura e proveniência. São os passos 2, 4 e 5 e o passo 3 como mecanismo.
- **Constrói-se a cola específica da fábrica**, que o estado da arte deixa de fora: o certificado e a ligação dele com
  as classes de lugar, o gate V0, o sequenciador por partição com validação otimista, o despacho por puxada por célula, o
  razão de orçamento, a medida de fluxo lida do ledger e a separação entre controle e dados dos agentes.
- **É inovação da Torre** e não se compra: o planejador (C02) e o conteúdo das instruções (C03).
- **É pesquisa** porque ninguém publicou: certificar transformações gerais de código a 10^3 por segundo (C10) e decidir
  o que testar depois do merge quando entram 10^9 mudanças por segundo (C14), além do planejador.

## 9. O que não foi verificado nesta sessão

- O custo por arquivo de uma checagem de tipos incremental (C12) e a latência de consulta a um cache por conteúdo além do
  piso de RPC (C09): a pesquisa acabou antes desses itens (limite de 200 buscas por turno).
- Os números internos do SubmitQueue da Uber (grafo de especulação, analisador de conflitos) e o teto do Spanner por
  divisão.
- As regras de cada fila de merge comercial (Mergify, Aviator, Graphite, Trunk) e a taxa de commits de pico, por
  segundo, de qualquer monorepo.
- A RAM por sessão de agente em C07 é estimativa [E].
