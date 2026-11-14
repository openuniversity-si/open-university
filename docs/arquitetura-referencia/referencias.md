# Referências

Entregável 7. Fontes primárias citadas nos documentos desta pasta, por identificador estável: **Q** filas e fluxo,
**S** fonte de verdade, monorepos, filas de merge e forges, **V** verificação, build, testes e transformações em massa,
**C** coordenação, mensageria e estado, **A** IA, inferência e custo, **X** segurança, observabilidade, limites físicos
e economia, **W** modelos de domínio, workflows e eventos, **B** plantas de sistemas e padronização na AWS, **L**
agentes de autonomia longa e aprendizado, **N** direção (objetivos, apostas e planejadores), **K** núcleos, camadas e a
separação entre mecanismo e política, **T** documentos do próprio repositório.

**Como ler o estado de cada fonte.** O egress desta sessão bloqueia a maior parte dos sites primários (arxiv.org,
research.google, dl.acm.org, usenix.org, engineering.fb.com, aws.amazon.com, cursor.com e outros; medido com `curl` em
04/11/2026). Por isso cada entrada diz como o número foi conferido:

- **(página)**: lido na própria fonte. Quando o site estava bloqueado, a fonte foi lida no repositório oficial dela no
  GitHub (por exemplo os docs da Cloudflare em `cloudflare/cloudflare-docs`, os do GitHub em `github/docs`, o livro
  *Software Engineering at Google* no repositório do abseil.io) e o link aponta para lá.
- **(trecho)**: o número foi visto só no trecho que a busca devolveu, sem abrir a página. Vale como indício forte, não
  como leitura; a verificação em [08](08-verificacao.md) conta quantos números dependem só de trecho.

## Q. Filas e fluxo

- **[Q1]** Little, J. D. C. (1961). *A Proof for the Queuing Formula: L = λW*. Operations Research 9(3):383–387.
  https://doi.org/10.1287/opre.9.3.383
- **[Q2]** Kingman, J. F. C. (1961). *The single server queue in heavy traffic*. Mathematical Proceedings of the
  Cambridge Philosophical Society 57(4):902–904. https://doi.org/10.1017/S0305004100036094

## S. Fonte de verdade, monorepos, filas de merge e forges

- **[S1]** Potvin, R.; Levenberg, J. (2016). *Why Google Stores Billions of Lines of Code in a Single Repository*.
  CACM 59(7). 16 mil commits humanos e 24 mil automatizados por dia útil (jan/2015); ~800 mil QPS de leitura no pico;
  Bigtable e depois Spanner, 10 datacenters, Paxos. (trecho)
  https://cacm.acm.org/research/why-google-stores-billions-of-lines-of-code-in-a-single-repository/
- **[S2]** Winters, Manshreck, Wright (2020). *Software Engineering at Google*, cap. 16. 60 a 70 mil commits por dia
  útil; ~50 mil engenheiros. (página)
  https://raw.githubusercontent.com/abseil/abseil.github.io/master/resources/swe-book/html/ch16.html
- **[S3]** Idem, cap. 22 (*Large-Scale Changes*). O Rosie divide uma mudança por dono, cada pedaço segue o próprio
  ciclo de teste, revisão e submissão; "milhares de mudanças por dia". (página)
  https://raw.githubusercontent.com/abseil/abseil.github.io/master/resources/swe-book/html/ch22.html
- **[S4]** Idem, cap. 23 (*Continuous Integration*). O TAP: mais de 50 mil mudanças por dia, mais de 4 bilhões de
  testes por dia, mudanças agrupadas em lote. (página)
  https://raw.githubusercontent.com/abseil/abseil.github.io/master/resources/swe-book/html/ch23.html
- **[S5]** Meta, Mononoke README: servidor desenhado para "milhares de commits por hora em milhões de arquivos";
  pushrebase faz o rebase no servidor e um compare-and-swap no bookmark, com até 100 tentativas. (página)
  https://raw.githubusercontent.com/facebook/sapling/main/eden/mononoke/README.md e
  https://raw.githubusercontent.com/facebook/sapling/main/eden/mononoke/features/pushrebase/src/lib.rs
- **[S6]** Meta Engineering (2021, 2022). Em 2016 a taxa de mudanças chegava perto do máximo de commits do Mercurial; o
  Sapling lida com dezenas de milhões de arquivos, commits e branches. (trecho)
  https://engineering.fb.com/2021/04/29/developer-tools/rust/ e
  https://engineering.fb.com/2022/11/15/open-source/sapling-source-control-scalable/
- **[S7]** Harry, B. (2017). *The largest Git repo on the planet*. Windows: 3,5 milhões de arquivos, ~300 GB, ~4 mil
  engenheiros, 8.421 pushes por dia. (trecho) https://devblogs.microsoft.com/bharry/the-largest-git-repo-on-the-planet/
- **[S8]** Ananthanarayanan et al. (2019). *Keeping Master Green at Scale* (SubmitQueue), EuroSys; e Uber Blog,
  *Bypassing large diffs in SubmitQueue*: espera para entrar −74 %, recursos de CI −53 %. (trecho)
  https://uber.com/blog/bypassing-large-diffs-in-submitqueue
- **[S9]** bors-ng README (lote com bisseção, O(E log N) contra O(N); descontinuado); rust-lang/bors (um build
  automático por vez); graydon/bors (a regra "not rocket science"). (página)
  https://raw.githubusercontent.com/bors-ng/bors-ng/master/README.md ;
  https://raw.githubusercontent.com/rust-lang/bors/main/docs/design.md ;
  https://raw.githubusercontent.com/graydon/bors/master/README.md
- **[S10]** Zuul 14.3.0, documentação do pipeline dependente: especulativo, janela 20, piso 3, +1 por merge, metade em
  falha. O glossário e `zuul/model.py`: a change é "a specific state of a Git repository"; o item da fila é "the
  position of a Change in a ChangeQueue"; o buildset reúne os builds de "one specific potential future repository
  state". (página, lida no pacote publicado)
  https://files.pythonhosted.org/packages/8d/bb/8ec6d708d48bbe05f74e6072fd5797de4e6c9cde13853f006e79cbd0164c/zuul-14.3.0.tar.gz
- **[S11]** GitHub Docs, *Managing a merge queue*: 1 a 100 builds simultâneos; 1 a 100 PRs por merge. (página)
  https://raw.githubusercontent.com/github/docs/main/content/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue.md
- **[S12]** GitLab Docs, *Merge trains*: 20 pipelines em paralelo por padrão. (página)
  https://gitlab.com/gitlab-org/gitlab/-/raw/master/doc/ci/pipelines/merge_trains.md
- **[S13]** Chromium, *CQ*: cada mudança testada sozinha; builds verdes reaproveitados por até 800 commits ou 24 h.
  (página) https://raw.githubusercontent.com/chromium/chromium/main/docs/infra/cq.md
- **[S14]** GitHub Docs, *Repository limits*: recomendado no máximo 6 pushes por minuto, 1 PR mergeada por minuto e 15
  leituras de git por segundo por repositório. (página)
  https://raw.githubusercontent.com/github/docs/main/content/repositories/creating-and-managing-repositories/repository-limits.md
- **[S15]** GitHub Blog (06/10/2026). *Building Git infrastructure for agent-scale development*: pushes de 0,69 para
  3,35 bilhões por mês em um ano (4,9×). (trecho)
  https://github.blog/engineering/architecture-optimization/building-git-infrastructure-for-agent-scale-development/
- **[S16]** GitHub Blog (21/10/2026). *The bridge to agent-scale Git infrastructure*: quórum por ref em vez de por
  repositório, 3 a 4× em escritas a refs diferentes; "o quórum continua sendo o fator limitante". (trecho)
  https://github.blog/engineering/architecture-optimization/the-bridge-to-agent-scale-git-infrastructure/
- **[S17]** GitHub, Octoverse 2026: 1,3 bilhão de PRs mergeadas por ano (~41/s), 17,9 bilhões de pushes, 34,3 bilhões
  de commits; mais de 40 % das PRs iniciadas por um agente em set/2026 (~110 milhões no mês). (trecho)
  https://github.blog/news-insights/octoverse/octoverse-commits-pushes-reach-new-highs-in-2026-as-developers-build-with-agents/
- **[S18]** Git, *reftable*: um arquivo de trava; "o repositório é single-threaded para escritores". (página)
  https://raw.githubusercontent.com/git/git/master/Documentation/technical/reftable.adoc
- **[S19]** Git, *git-push*: `--atomic` (todas as refs ou nenhuma) e `--force-with-lease=<ref>:<esperado>` como
  compare-and-swap. (página) https://raw.githubusercontent.com/git/git/master/Documentation/git-push.adoc
- **[S20]** GitHub Docs, limites da API REST: 5.000/h por usuário; 15.000/h no Enterprise Cloud; limites secundários
  de 900 pontos/min (REST), 80 requisições que criam conteúdo por minuto e 500 por hora, 100 simultâneas; GET 1 ponto,
  escrita 5. (página)
  https://raw.githubusercontent.com/github/docs/main/data/reusables/rest-api/secondary-rate-limit-rest-graphql.md
- **[S21]** Cursor, documentação da API do Origin e changelog: 600 pontos/min por usuário, 3.000 por token de
  instalação, 6.000 por JWT de app (subiu de 600 em 19/08/2026); leitura 1, escrita 5, merge 10; HTTP 429 com
  `Retry-After`; git por HTTPS com orçamento próprio desde 16/09/2026, sem valor publicado. (trecho; os valores 600, 1
  e 5 foram medidos nesta sessão, ver [02](02-estado-atual.md))
  https://cursor.com/docs/api/origin e https://cursor.com/docs/api/origin/changelog
- **[S22]** FoundationDB, *Performance* e *Known limitations*: commit em 1,5–2,5 ms; "dezenas de milhares de commits
  por segundo"; 8,2 milhões de operações/s em 384 processos; transação ≤ 10 MB e ≤ 5 s. (página)
  https://raw.githubusercontent.com/apple/foundationdb/main/documentation/sphinx/source/performance.rst e
  https://raw.githubusercontent.com/apple/foundationdb/main/documentation/sphinx/source/known-limitations.rst
- **[S23]** Google, API do Spanner: `max_commit_delay` de 0 a 500 ms troca latência por vazão de commit. (página)
  https://raw.githubusercontent.com/googleapis/googleapis/master/google/spanner/v1/spanner.proto
- **[S24]** GitLab Docs, Gitaly Cluster (Praefect): consistência forte, escrita síncrona em todas as réplicas
  saudáveis. (página) https://gitlab.com/gitlab-org/gitlab/-/raw/master/doc/administration/gitaly/praefect/_index.md

- **[S25]** GitHub Docs, *Pull request merges* (merges indiretos): a PR é marcada mergeada quando os commits do head
  ficam alcançáveis a partir da base fora da PR, inclusive por push direto, mesmo sem as regras de proteção satisfeitas.
  (página) https://docs.github.com/en/pull-requests/reference/pull-request-merges
- **[S26]** Prow Tide (kubernetes-sigs/prow): pools por repositório e branch, lotes, uma chamada de merge por PR com 5 s de
  pausa e retentativas, não atômico. (página, fonte e documentação no repositório)
  https://github.com/kubernetes-sigs/prow (`pkg/tide/github.go`, `site/content/en/docs/components/core/tide/`)
- **[S27]** Uber SubmitQueue, implementação aberta e RFCs: Runway serializa "no máximo uma operação de merge em voo por
  branch"; o Stovepipe valida depois do pouso e promove `verified/main` só por fast-forward; o Tango acha conflitos por
  alvo mudado. (página) https://github.com/uber/submitqueue (`doc/rfc/runway/workflow.md`, `doc/rfc/stovepipe/workflow.md`)
- **[S28]** Documentação de fornecedores de fila de merge, vista só por trecho de busca: Mergify (lotes de 1 a 128,
  bisseção, partições), Aviator (modo paralelo por alvos afetados, validação otimista até profundidade 3), Trunk (filas
  paralelas por alvos impactados, merge otimista, lotes), Graphite (ciente de pilhas, fast-forward da base). (trecho)
  https://docs.mergify.com/merge-queue/batches ; https://docs.aviator.co/mergequeue/concepts/parallel-mode ;
  https://docs.trunk.io/merge-queue/optimizations/parallel-queues ; https://graphite.dev/docs/merge-queue-optimizations

## V. Verificação, build, testes e transformações em massa

Todas (trecho), salvo indicação.

- **[V1]** Memon et al. (2017). *Taming Google-Scale Continuous Testing*, ICSE-SEIP.
  https://research.google/pubs/pub45861/ (cópia: https://web.eecs.umich.edu/~xwangsd/courses/w23/readings/googletest.pdf)
- **[V2]** Leong et al. (2019). *Assessing Transition-based Test Selection Algorithms at Google*, ICSE-SEIP: ~1 commit/s,
  mais de 150 milhões de execuções de teste por dia. https://research.google/pubs/pub48335/
- **[V3]** *Speculative Testing at Google with Transition Prediction*, ICST 2025: 25 % dos alvos dão 85 % da detecção
  de quebras; detecção p50 de 107 para 37 min.
  https://research.google/pubs/speculative-testing-at-google-with-transition-prediction/
- **[V4]** Wang et al. (2020). *Scalable Build Service System with Smart Scheduling Service*, ISSTA: mais de 15 milhões de
  builds por dia. https://kaiyuanw.github.io/papers/paper24-issta20.pdf
- **[V5]** Meta (2023). *Build faster with Buck2*: 2× mais rápido que o Buck1, execução remota primeiro, a mesma API de
  execução remota do Bazel. https://engineering.fb.com/2023/04/06/open-source/buck2-open-source-large-scale-build-system/
- **[V6]** Bazel, *Remote Execution API* (Action Cache por digest da ação; CAS por digest do conteúdo).
  https://pkg.go.dev/github.com/bazelbuild/remote-apis/build/bazel/remote/execution/v2
- **[V7]** Trace Machina, NativeLink README (fornecedor): mais de 1 bilhão de requisições por mês.
  https://github.com/TraceMachina/nativelink/blob/3117a333f5e4df97068e91c4bb38e95d549045ca/README.md
- **[V8]** Machalica et al. (2019). *Predictive Test Selection*, ICSE-SEIP (Meta): metade do custo de testes, mais de 95 %
  das falhas e mais de 99,9 % das mudanças com defeito ainda apontadas. https://arxiv.org/pdf/1810.05286.pdf
- **[V9]** *Accelerating Continuous Integration with Parallel Batch Testing*, FSE 2023: lote de 4 com até 75 % menos
  execuções (276 milhões de resultados do Chrome). https://arxiv.org/pdf/2308.13129
- **[V10]** Beheshtian, Bavand, Rigby (2021). *Software Batch Testing to Save Build Test Resources and to Reduce
  Feedback Time*, TSE: ~48–50 % menos execuções; compensa abaixo de 40 % de builds com falha.
  https://conf.researchr.org/details/icse-2022/icse-2022-journal-first-papers/61/Software-Batch-Testing-to-Save-Build-Test-Resources-and-to-Reduce-Feedback-Time
- **[V11]** Henderson et al. (2023). *Flake Aware Culprit Finding*, ICST (Google): mais de 13 mil quebras estudadas.
  https://research.google/pubs/flake-aware-culprit-finding/
- **[V12]** Dorfman, R. (1943). *The Detection of Defective Members of Large Populations*: E = 1/k + 1 − (1−p)^k testes por
  item, ótimo em k ≈ 1/√p. https://pmc.ncbi.nlm.nih.gov/articles/PMC5193172
- **[V13]** Google Testing Blog (2016). *Flaky Tests at Google and How We Mitigate Them*: 1,5 % das execuções, ~16 % dos
  testes, 84 % das transições de verde para vermelho envolvem teste instável. https://testing.googleblog.com/2016/05/
- **[V14]** Luo et al. (2014). *An Empirical Analysis of Flaky Tests*, FSE. https://huang.isis.vanderbilt.edu/cs8395/paper/flakytest.pdf
- **[V15]** Rungta, N. (2022). *A Billion SMT Queries a Day*, CAV (AWS Zelkova): ~10^9 consultas SMT por dia, 0,2 s a
  dezenas de segundos cada. https://amazon.science/blog/a-billion-smt-queries-a-day
- **[V16]** Newcombe et al. (2015). *How Amazon Web Services Uses Formal Methods*, CACM.
  https://cacm.acm.org/magazines/2015/4/184701-how-amazon-web-services-uses-formal-methods/fulltext
- **[V17]** Cutler et al. (2024). *How We Built Cedar*: modelo em Lean e testes diferenciais, milhões de casos por noite.
  https://arxiv.org/pdf/2407.01688
- **[V18]** Chudnov et al. (2018). *Continuous Formal Verification of Amazon s2n*, CAV: provas reexecutadas em todo push.
  https://link.springer.com/chapter/10.1007/978-3-319-96142-2_26
- **[V19]** Lopes et al. (2015). *Provably Correct Peephole Optimizations with Alive*, PLDI: 334 reescritas do
  InstCombine, 8 erradas; cada reescrita provada uma vez para todos os tipos e larguras e emitida como C++ que roda em
  cada ocorrência sem prova por lugar. https://users.cs.utah.edu/~regehr/papers/pldi15.pdf
- **[V20]** Lopes et al. (2021). *Alive2: Bounded Translation Validation for LLVM*, PLDI: 47 bugs novos no LLVM.
  https://www-old.cs.utah.edu/~regehr/alive2-pldi21.pdf
- **[V21]** Yang et al. (2011). *Finding and Understanding Bugs in C Compilers*, PLDI: nenhum bug de código errado no
  meio do CompCert depois de ~6 anos-CPU de Csmith. https://www-old.cs.utah.edu/~regehr/papers/pldi11-preprint.pdf
- **[V22]** seL4, números do l4.verified: 8.700 linhas de C, 200 mil linhas de prova, ~12 pessoas-ano.
  https://trustworthy.systems/projects/OLD/l4.verified/numbers
- **[V23]** Distefano et al. (2019). *Scaling Static Analyses at Facebook*, CACM: 70 % de correção no diff contra ~0 % em
  lote. https://cacm.acm.org/magazines/2019/8/238344-scaling-static-analyses-at-facebook/pdf
- **[V24]** Sadowski et al. (2018). *Lessons from Building Static Analysis Tools at Google*, CACM.
  https://research.google/pubs/pub46576/
- **[V25]** Butler, R.; Finelli, G. (1993). *The Infeasibility of Quantifying the Reliability of Life-Critical
  Real-Time Software*, TSE: provar 10^-9 falhas/hora por teste exigiria ~114 mil anos.
  https://ntrs.nasa.gov/api/citations/20040139817/downloads/20040139817.pdf
- **[V26]** Hanley, J. A.; Lippman-Hand, A. (1983). *If nothing goes wrong, is everything all right?*, JAMA: zero eventos
  em N dá limite superior de 95 % ≈ 3/N (a regra de três). https://jamanetwork.com/journals/jama/article-abstract/389714
- **[V27]** Necula, G. (1997). *Proof-Carrying Code*, POPL: conferir uma prova é barato mesmo quando achá-la é caro.
  https://courses.grainger.illinois.edu/cs421/fa2010/papers/necula-pcc.pdf
- **[V28]** Ziftci et al. (2025). *Migrating Code At Scale With LLMs At Google*, FSE: 74,45 % de 595 mudanças (93.574
  edições) feitas pelo LLM; ~50 % de tempo poupado (estimativa). https://arxiv.org/html/2504.09691v1
- **[V29]** Nikolov et al. (2025). *How is Google using AI for internal code migrations?*: 80 % das modificações
  escritas pela IA na migração de IDs de int32 para int64. https://arxiv.org/pdf/2501.06972
- **[V30]** Bader et al. (2019). *Getafix: Learning to Fix Bugs Automatically*, OOPSLA. https://arxiv.org/abs/1902.06111
- **[V31]** Ramanathan et al. (2020). *Piranha: Reducing Feature Flag Debt at Uber*, ICSE-SEIP: 1.381 flags; 65 % dos
  diffs entraram sem mudança.
  https://2020.icse-conferences.org/details/icse-2020-Software-Engineering-in-Practice/16/Piranha-Reducing-Feature-Flag-Debt-at-Uber
- **[V32]** Ketkar et al. (2024). *A Lightweight Polyglot Code Transformation Language* (PolyglotPiranha), PLDI: 210 mil
  linhas apagadas, 1.611 PRs. https://danieltrt.github.io/papers/pldi24.pdf
- **[V33]** OpenRewrite, *Lossless Semantic Trees*. https://docs.openrewrite.org/concepts-explanations/lossless-semantic-trees
- **[V34]** Airbnb (2025). *Accelerating Large-Scale Test Migration with LLMs*: ~3.500 arquivos de teste em ~6 semanas
  (a estimativa era 1,5 ano). https://airbnb.tech/?p=366
- **[V35]** AWS DevOps Blog (2024). Amazon Q Developer: mais de 30 mil aplicações migradas de versão de Java, 4.500
  desenvolvedores-ano poupados.
  https://aws.amazon.com/blogs/devops/amazon-q-developer-just-reached-a-260-million-dollar-milestone
- **[V36]** Benchmark de cinco ferramentas de AST (2026, feito pelo autor do ast-grep): 500 arquivos em 43 ms
  (~86 µs/arquivo). https://dev.to/herrington_darkholme/how-fast-is-your-code-search-tool-a-benchmark-of-five-ast-tools-590j

- **[V37]** Zoekt, documento de desenho: resultados em menos de 50 ms em bases grandes como o Android (~2 GB de texto),
  numa máquina Linux comum; com trigramas posicionais a busca precisa de RAM de ~1,2× o tamanho do corpus. (página)
  https://raw.githubusercontent.com/sourcegraph/zoekt/main/doc/design.md
- **[V38]** Glean (Meta), README: um sistema para guardar e consultar fatos sobre código-fonte em escala. (página)
  https://raw.githubusercontent.com/facebookincubator/Glean/main/README.md
- **[V39]** Git, *git-merge-tree*: "Perform merge without touching index or working tree"; o modo `--write-tree` grava a
  árvore do merge e devolve o id dela, o que permite mesclar no servidor sem cópia de trabalho. (página)
  https://raw.githubusercontent.com/git/git/master/Documentation/git-merge-tree.adoc

## C. Coordenação, mensageria e estado

Os docs da Cloudflare (C1 a C6) foram lidos no repositório `cloudflare/cloudflare-docs` (commit 41323a9, 04/11/2026),
porque o site estava bloqueado.

- **[C1]** Cloudflare Workers, limites: plano grátis com 100.000 requisições/dia. (página)
  https://github.com/cloudflare/cloudflare-docs (src/content/docs/workers/platform/limits)
- **[C2]** Cloudflare Durable Objects, preços: plano grátis com 5.000.000 linhas SQLite lidas/dia, 100.000 escritas/dia,
  100.000 requisições/dia, 5 GB; passada a cota, a operação falha até 00:00 UTC. (página)
  https://developers.cloudflare.com/durable-objects/platform/pricing/
- **[C3]** Cloudflare Durable Objects, limites: ~1.000 requisições/s por objeto (limite brando), objeto de uma thread só.
  (página) https://developers.cloudflare.com/durable-objects/platform/limits/
- **[C4]** Cloudflare D1, perguntas de preço: linha lida é linha varrida (as taxas dos Durable Objects seguem as do D1).
  (página) https://developers.cloudflare.com/d1/platform/pricing/
- **[C5]** Cloudflare Workflows, limites: grátis com 3.000 passos/dia e 100 simultâneos. (página)
  https://developers.cloudflare.com/workflows/reference/limits/
- **[C6]** Cloudflare Queues e KV, limites: 5.000 mensagens/s por fila. (página)
  https://developers.cloudflare.com/queues/platform/limits/
- **[C7]** LinkedIn Engineering (2019). Kafka: mais de 7 × 10^12 mensagens/dia, mais de 4 mil brokers, 7 milhões de
  partições. (trecho) https://engineering.linkedin.com/blog/2019/apache-kafka-trillion-messages
- **[C8]** Kreps, J. (2014). *Benchmarking Apache Kafka: 2 Million Writes Per Second (On Three Cheap Machines)*. (trecho)
  https://engineering.linkedin.com/kafka/benchmarking-apache-kafka-2-million-writes-second-three-cheap-machines
- **[C9]** Confluent (2018, 2021): 200 mil partições por cluster com ZooKeeper; 2 milhões em teste com KRaft. (trecho)
  https://www.confluent.io/blog/kafka-without-zookeeper-a-sneak-peek/
- **[C10]** Confluent (2017). Exatamente uma vez no Kafka: 3 a 5 % de custo com transações de 100 ms. (trecho)
  https://www.slideshare.net/slideshow/exactlyonce-semantics-in-apache-kafka/77382203
- **[C11]** Karpathiotakis et al. (2025). Scribe na Meta, PVLDB 18(12): mais de 15 TB/s de ingestão. (trecho)
  https://www.vldb.org/pvldb/vol18/p4817-karpathiotakis.pdf
- **[C12]** Amazon SQS, cotas: fila padrão "quase ilimitada"; FIFO de alta vazão até 70 mil TPS por ação. (trecho)
  https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html
- **[C13]** Amazon Kinesis, cotas: 1.000 registros/s ou 1 MB/s de escrita por shard. (trecho)
  https://docs.aws.amazon.com/streams/latest/dev/service-sizes-and-limits.html
- **[C14]** Bronson et al. (2013). *TAO: Facebook's Distributed Data Store for the Social Graph*, USENIX ATC: ~10^9
  leituras/s e milhões de escritas/s. (trecho) https://www.usenix.org/system/files/conference/atc13/atc13-bronson.pdf
- **[C15]** Adams et al. (2020). *Monarch: Google's Planet-Scale In-Memory Time Series Database*, PVLDB 13: ingere
  terabytes por segundo. (trecho) https://www.vldb.org/pvldb/vol13/p3181-adams.pdf
- **[C16]** Google Cloud Blog (2025). Spanner: mais de 6 × 10^9 consultas/s no pico, mais de 17 EB. (trecho)
  https://cloud.google.com/blog/products/databases/spanner-in-2025
- **[C17]** Elhemali et al. (2022). *Amazon DynamoDB*, USENIX ATC: 89,2 milhões de requisições/s no pico de 2021; limite
  de 1.000 unidades de escrita por partição. (trecho) https://www.usenix.org/system/files/atc22-elhemali.pdf
- **[C18]** AWS News Blog (06/10/2026). Prime Day 2026: DynamoDB com pico de 192 milhões de requisições/s. (trecho)
  https://aws.amazon.com/blogs/aws/all-the-numbers-amazon-prime-day-2026-powered-by-aws/
- **[C19]** AWS News Blog (2026). S3: mais de 500 × 10^12 objetos, mais de 200 milhões de requisições/s; ao menos 3.500
  escritas/s por prefixo. (trecho) https://aws.amazon.com/blogs/aws/twenty-years-of-amazon-s3-and-building-whats-next
- **[C20]** Cloudflare Radar, *Year in Review 2025*: 81 milhões de requisições HTTP/s em média, 129 milhões no pico.
  (trecho) https://blog.cloudflare.com/radar-2025-year-in-review
- **[C21]** Zhou et al. (2021). *FoundationDB: A Distributed Unbundled Transactional Key Value Store*, SIGMOD: de 593
  mil para 2,78 milhões de operações/s de 4 para 24 máquinas; teste por simulação em toda funcionalidade nova. (trecho)
  https://www.foundationdb.org/files/fdb-paper.pdf
- **[C22]** Thomson et al. (2012). *Calvin: Fast Distributed Transactions for Partitioned Database Systems*, SIGMOD:
  ~500 mil transações TPC-C/s em ~100 nós. (trecho) https://www.cs.princeton.edu/courses/archive/fall19/cos418/papers/calvin.pdf
- **[C23]** Temporal Cloud, limites e modos de capacidade: 500 ações/s por namespace por padrão, até 6.000. (página)
  https://docs.temporal.io/cloud/limits
- **[C24]** Cadence (2024). *Yearly roadmap update*: ~100 mil atualizações de workflow por segundo na Uber, ~30
  clusters. (página) https://cadenceworkflow.io/blog/2024/07/11/yearly-roadmap-update
- **[C25]** AWS Step Functions, cotas: Standard com 5.000 transições/s; Express lançado para até 100 mil por segundo.
  (trecho) https://docs.aws.amazon.com/step-functions/latest/dg/limits.html
- **[C26]** Kubernetes, *Considerations for large clusters*: até 5.000 nós, 150 mil pods, 110 pods por nó. (página)
  https://kubernetes.io/docs/setup/best-practices/cluster-large/
- **[C27]** Kubernetes, `scheduler_perf`: pisos de CI de 680 pods/s (5.000 nós) e 1.100 pods/s (15.000 nós). (página)
  https://github.com/kubernetes/kubernetes/blob/master/test/integration/scheduler_perf/misc/performance-config.yaml
- **[C28]** Google, `cluster-data`: traço de uma célula Borg de 12,5 mil máquinas (2011) e de 8 células (2019). (página)
  https://github.com/google/cluster-data
- **[C29]** Ray, envelope de escala: 2 mil+ nós, 40 mil+ atores, 1 milhão+ de tarefas na fila de um nó. (página)
  https://github.com/ray-project/ray/blob/master/release/benchmarks/README.md
- **[C30]** Spark (2014): 100 TB ordenados em 23 min em 206 máquinas. (página)
  https://spark.apache.org/news/spark-wins-daytona-gray-sort-100tb-benchmark.html
- **[C31]** gRPC, proposta A6 (retries): balde de tokens que corta retries sob falha. (página)
  https://github.com/grpc/proposal/blob/master/A6-client-retries.md
- **[C32]** Envoy, filtro de controle de admissão (a fórmula do capítulo *Handling Overload* do livro de SRE do Google).
  (página) https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/admission_control_filter
- **[C33]** Kubernetes, *API Priority and Fairness* (shuffle sharding) e AWS Labs Infima (raio de explosão 1/C(N,K)).
  (página) https://kubernetes.io/docs/concepts/cluster-administration/flow-control/ e https://github.com/awslabs/route53-infima
- **[C34]** Stripe, SDK oficial: chaves de idempotência automáticas para retries seguros. (página)
  https://github.com/stripe/stripe-python

- **[C35]** AWS Price List (us-east-1), Step Functions: Standard US$ 0,000025 por transição (4.000 grátis por mês),
  até 1 ano, espera por token só no Standard; Express US$ 1 por milhão + GB·s, até 5 min. (página)
  https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json (AmazonStates)
- **[C36]** AWS Price List, Lambda: US$ 0,20 por milhão de requisições; US$ 0,0000133334 por GB·s em ARM; 1 milhão de
  requisições e 400 mil GB·s grátis por mês. (página) (AWSLambda)
- **[C37]** AWS Lambda, funções duráveis: US$ 8 por milhão de operações duráveis, US$ 0,25 por GB gravado (Price List);
  lançadas em dez/2025, execução de até 1 ano sem cobrança de computação enquanto suspensa (trecho). (página e trecho)
  https://aws.amazon.com/about-aws/whats-new/2025/12/lambda-durable-multi-step-applications-ai-workflows/
- **[C38]** AWS Price List, EventBridge (US$ 1 por milhão de eventos; Scheduler 14 milhões grátis) e SQS (US$ 0,40 por
  milhão; 1 milhão grátis). (página) (AWSEvents, AWSQueueService)
- **[C39]** AWS Price List, DynamoDB sob demanda: US$ 0,625 por milhão de escritas e US$ 0,125 por milhão de leituras
  (01/11/2026); 25 GB grátis; streams lidos por Lambda sem custo. (página) (AmazonDynamoDB)
- **[C40]** AWS Price List, API Gateway HTTP API: US$ 1 por milhão de requisições. (página) (AmazonApiGateway)
- **[C41]** AWS Price List, RDS e Aurora: RDS PostgreSQL db.t4g.micro US$ 0,016/h (Multi-AZ 0,032), db.t4g.small
  US$ 0,032/h (Multi-AZ 0,065), db.t4g.medium US$ 0,065/h (Multi-AZ 0,129), gp3 US$ 0,115/GB·mês
  (Multi-AZ 0,23); Aurora Serverless v2 US$ 0,12 por ACU·h; Aurora DSQL US$ 8 por milhão de DPU. (página) (AmazonRDS,
  AuroraDSQL)
- **[C42]** AWS Price List, CloudWatch (logs US$ 0,50/GB, 5 GB grátis), Secrets Manager (US$ 0,40 por segredo) e S3.
  (página) (AmazonCloudWatch, AWSSecretsManager, AmazonS3)
- **[C43]** Temporal Cloud, preços: a partir de US$ 50 por milhão de ações; plano Business a US$ 500/mês ou 10 % do
  uso; 500 ações/s por namespace por padrão. (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/evaluate/cloud/pricing.mdx
- **[C44]** DBOS, arquitetura: biblioteca que grava workflows e passos no Postgres, "sem servidor de orquestração
  separado"; ~1.000 workflows ou passos por segundo por vCPU do Postgres (afirmação do fornecedor). (página)
  https://raw.githubusercontent.com/dbos-inc/dbos-docs/main/docs/architecture.md
- **[C45]** Cloudflare, plano Workers Paid (US$ 5/mês com 10 milhões de requisições), Durable Objects (1 milhão de
  requisições; 50 milhões de linhas escritas incluídas, depois US$ 1 por milhão), D1, Queues, Workflows e Containers.
  (página) https://github.com/cloudflare/cloudflare-docs (src/content/docs/workers/platform/pricing)
- **[C46]** AWS Price List, Fargate: x86 US$ 0,04048 por vCPU·h + 0,004445 por GB·h; ARM US$ 0,03238 + 0,00356;
  Fargate Spot ~US$ 0,01254 + 0,001377 (trecho, guia de 2026). (página e trecho) (AmazonECS)
- **[C47]** AWS Price List, CodeBuild: arm1.small US$ 0,0034 por minuto; computação Lambda ARM de 2 GB US$ 0,00002 por
  segundo; 100 minutos grátis. (página) (CodeBuild)
- **[C48]** AWS Price List, EC2 Graviton sob demanda: c8g.large US$ 0,07976/h, m8g.large US$ 0,08976/h; spot ~0,034 e
  ~0,043 (trecho, Holori). (página e trecho) (AmazonEC2) ; https://calculator.holori.com/aws/ec2/c8g.large/us-east-1
- **[C49]** Google Cloud, páginas de preço: Cloud Run, Pub/Sub, Firestore (20 mil escritas e 50 mil leituras grátis por
  dia), Workflows (US$ 0,01 por mil passos internos), Cloud Build (e2-standard-2 US$ 0,006/min; 2.500 min grátis),
  Cloud SQL, GKE Autopilot. (página) https://cloud.google.com/run/pricing ; https://cloud.google.com/workflows/pricing ;
  https://cloud.google.com/firestore/pricing ; https://cloud.google.com/build/pricing
- **[C50]** AWS, mudança da camada gratuita de 15/07/2025: US$ 100 de crédito na abertura + até US$ 100 por atividades,
  plano grátis de até 6 meses; mais de 30 serviços seguem com franquia sempre grátis. (trecho)
  https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/

- **[C52]** AWS Price List (us-east-1, 04/11/2026): endereço IPv4 público US$ 0,005 por hora; NAT Gateway US$ 0,045 por
  hora e US$ 0,045 por GB processado; alarme do CloudWatch US$ 0,10 por métrica de alarme por mês. (página)
  https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/us-east-1/index.csv (e as ofertas AmazonEC2 e
  AmazonCloudWatch)
- **[C53]** AWS, *DynamoDB Developer Guide*, "NoSQL design": num banco relacional dá para criar o modelo normalizado
  sem pensar nos padrões de acesso e estendê-lo depois, quando surgem perguntas novas; "you shouldn't start designing
  your schema for DynamoDB until you know the questions it will need to answer". (página, no repositório awsdocs)
  https://raw.githubusercontent.com/awsdocs/amazon-dynamodb-developer-guide/master/doc_source/bp-general-nosql-design.md
- **[C54]** AWS CloudFormation, `AWS::Budgets::Budget` `CostTypes`: "Specifies whether a budget includes credits. The
  default value is true", e o mesmo para reembolsos; um orçamento sem filtro de tipo de cobrança mede o custo líquido
  dos créditos. (página, no repositório awsdocs)
  https://raw.githubusercontent.com/awsdocs/aws-cloudformation-user-guide/main/doc_source/aws-properties-budgets-budget-costtypes.md

## A. IA, inferência e custo

- **[A1]** DeepSeek (2025). *DeepSeek-V3/R1 Inference System Overview*: em 24 h, pico de 278 e média de 226,75 nós de 8
  H800; 608 bilhões de tokens de entrada (56,3 % acertos no cache em disco) e 168 bilhões de saída; ~73,7 mil tokens/s
  de entrada (prefill) ou ~14,8 mil de saída (decode) por nó; US$ 87.072 por dia a US$ 2/GPU·h; receita teórica de US$
  562.027 por dia. (página)
  https://github.com/deepseek-ai/open-infra-index/blob/main/202502OpenSourceWeek/day_6_one_more_thing_deepseekV3R1_inference_system_overview.md
- **[A2]** LMSYS (2025). *Deploying DeepSeek with PD Disaggregation and Large-Scale Expert Parallelism on 96 H100 GPUs*
  (SGLang): 52,3 mil tokens/s de entrada e 22,3 mil de saída por nó; ~US$ 0,20 por milhão de tokens de saída. (página)
  https://raw.githubusercontent.com/lm-sys/lm-sys.github.io/main/blog/2025-05-05-large-scale-ep.md
- **[A3]** LMSYS (2025). SGLang em GB200 NVL72: 26.156 tokens/s de entrada e 13.386 de saída por GPU; 3,8 a 4,8× o H100.
  (página) https://raw.githubusercontent.com/lm-sys/lm-sys.github.io/main/blog/2025-09-25-gb200-part-2.md
- **[A4]** LMSYS (2026). GB300 com contexto longo (128K de entrada, 8K de saída): 226 tokens/s por GPU, ~60× menos que
  com 2K de entrada. (página) https://raw.githubusercontent.com/lm-sys/lm-sys.github.io/main/blog/2026-02-19-gb300-longctx.md
- **[A5]** Anthropic, preços da API (nov/2026), em US$ por milhão de tokens (entrada / acerto de cache / saída): Haiku 5.5
  0,10 / 0,01 / 0,50; Sonnet 5.5 2 / 0,10 / 10; Opus 5.5 4 / 0,20 / 20; a Batch API dá 50 % de desconto. (página)
  https://platform.claude.com/docs/en/about-claude/pricing
- **[A6]** Google Cloud, preços do Vertex AI (nov/2026): Gemini 4 Argon 4 / 20; Gemini 3.1 Pro 2 / 12; lote com 50 % de
  desconto. (página) https://cloud.google.com/vertex-ai/generative-ai/pricing
- **[A7]** LiteLLM, registro de preços (fonte secundária): GPT-6 Sol 2 / 10; GPT-6 Luna 0,10 / 0,50; DeepSeek V4 Flash
  0,30 / 1,20. (página) https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
- **[A8]** Google Cloud, preços de VMs spot (Iowa, 04/11/2026): 8× B200 a US$ 39,63/h (~US$ 4,95 por GPU·h); 8× H100 a
  US$ 47,86–52,70/h (~US$ 6,0–6,6). (página) https://cloud.google.com/spot-vms/pricing
- **[A9]** Claude Code, *Manage costs effectively*: ~US$ 13 por desenvolvedor por dia ativo; no exemplo de sessão, ~94 %
  dos tokens são leitura de cache e 0,5 % saída. (página) https://code.claude.com/docs/en/costs
- **[A10]** Bai, Pei et al. (2026). *How Do AI Agents Spend Your Money?* (arXiv 2604.22750): tarefas de agente consomem
  1.000× mais tokens que chat de código; execuções da mesma tarefa variam até 30×; média de ~4,17 milhões de tokens por
  tarefa no SWE-bench Verified (a média é trecho). (resumo: página) https://www.microsoft.com/en-us/research/?p=1170556
- **[A11]** METR, `eval-analysis-public`: horizontes de tarefa "dobrando a cada ~7 meses"; nos dados de execução, a
  mediana de tokens das execuções bem-sucedidas vai de 56 mil a 403 mil (tarefas de 1 a 4 h) e de 0,41 a 2,98 milhões
  (4 a 16 h), conta da pesquisa sobre os dados publicados. (página) https://github.com/METR/eval-analysis-public
- **[A12]** Anthropic Engineering (2025). *How we built our multi-agent research system*: agentes usam ~4× os tokens de
  um chat; sistemas multiagente ~15×. (página) https://www.anthropic.com/engineering/multi-agent-research-system
- **[A13]** SWE-bench, dados do placar oficial: topo de 79,2 % no Verified (dez/2025); no placar só-bash, 76,8 % a US$ 0,75
  e 33 chamadas de modelo por tarefa (de 13 a 88). (página)
  https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json
- **[A14]** Google (Pichai, I/O 2026): de 480 trilhões de tokens por mês (mai/2025) a 3,2 quatrilhões (mai/2026), ~1,2 ×
  10^9 tokens/s. (trecho) https://www.shacknews.com/article/149205/google-3-2-quadrillion-monthly-ai-tokens
- **[A15]** Microsoft, teleconferências de resultados: mais de 100 trilhões de tokens no trimestre jan–mar/2025 (5× em um
  ano); em 28/10/2026, PRs feitas por agentes no GitHub cresceram 6× em seis meses e agentes abrem mais de um terço das
  PRs. (página) https://www.microsoft.com/en-us/investor/events/fy-2025/earnings-fy-2025-q3 e
  https://www.microsoft.com/en-us/investor/events/fy-2027/earnings-fy-2027-q1
- **[A16]** Epoch AI, `ai-chip-counts`: ~29,1 milhões de H100-equivalentes acumulados até o 2º tri de 2026 (Nvidia 21,0;
  TPU 4,8; AMD 1,7; Trainium 1,6), ~17,4 GW de potência de chip (soma feita pela pesquisa). (página)
  https://github.com/epoch-research/ai-chip-counts/tree/main/csv_export
- **[A17]** Anthropic (13/10/2026). *Redesigning source control at Anthropic*: de ~2.500 mudanças mergeadas por dia
  (mai/2026) para mais de 30.000 (set/2026); ~25 milhões de checkouts de código por dia. (página)
  https://www.anthropic.com/research/redesigning-source-control
- **[A18]** Anthropic (2026). *When AI builds itself*: mais de 80 % do código mergeado escrito pelo Claude (mai/2026).
  (página) https://www.anthropic.com/institute/recursive-self-improvement
- **[A19]** PR Arena (03/11/2026): PRs públicas mergeadas por agente, acumuladas (Codex 7,66 milhões; Copilot 1,58;
  Cursor 1,32; Devin 0,21) e a fração mergeada das prontas (64,5 % a 99,5 %). (página) https://github.com/aavetis/PRarena
- **[A20]** Li et al. (2025). *The Rise of AI Teammates in Software Engineering 3.0* (AIDev): 456.535 PRs de agentes em
  61.453 repositórios, aceitas menos que as humanas. (trecho) https://arxiv.org/abs/2507.15003
- **[A21]** Stripe (fev/2026). *Minions*: mais de 1.300 PRs mergeadas por semana por agentes de ponta a ponta. (trecho)
  https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents
- **[A22]** Spotify, caso de cliente da Anthropic: mais de 650 PRs mergeadas por mês pelo agente em segundo plano.
  (página) https://claude.com/customers/spotify
- **[A23]** Alshahwan et al. (2024). *Automated Unit Test Improvement using Large Language Models at Meta* (TestGen-LLM),
  FSE: 75 % compilaram, 57 % passaram de forma confiável, 25 % aumentaram a cobertura, 73 % aceitas. (trecho)
  https://arxiv.org/abs/2402.09171
- **[A24]** Google DeepMind (2025). *AlphaEvolve*: "milhares de amostras de LLM bastam"; recupera 0,7 % da computação da
  frota do Google. (página)
  https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/AlphaEvolve.pdf
- **[A25]** Romera-Paredes et al. (2023). *Mathematical discoveries from program search with large language models*
  (FunSearch), Nature: ~10^6 amostras; 15 amostradores alimentando 150 avaliadores em CPU. (página)
  https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/Mathematical-discoveries-from-program-search-with-large-language-models.pdf
- **[A26]** Li et al. (2022). *Competition-Level Code Generation with AlphaCode*: até 10^6 amostras por problema; o filtro
  remove ~99 %; no máximo 10 submissões. (página)
  https://storage.googleapis.com/deepmind-media/AlphaCode/competition_level_code_generation_with_alphacode.pdf
- **[A27]** Google (Pichai, Cloud Next 2026): 75 % do código novo do Google gerado por IA (abr/2026); era mais de 25 % em
  out/2024. (trecho) https://blog.google/innovation-and-ai/infrastructure-and-cloud/google-cloud/cloud-next-2026-sundar-pichai/

- **[A28]** Claude Code, *Claude Code on the web*: sessões em nuvem nos planos Pro, Max, Ultra e Team, lançadas por
  `claude --cloud`; exigem conta claude.ai; dividem os limites da conta; clonar e abrir PR exige GitHub. (página)
  https://code.claude.com/docs/en/claude-code-on-the-web
- **[A29]** Claude Code, *scheduled tasks* e o disparo por API (prévia de pesquisa): 100 disparos por hora por conta, 30
  por tarefa, sem excedente; consomem o plano. (página) https://code.claude.com/docs/en/routines e
  https://platform.claude.com/docs/en/api/claude-code/routines-fire
- **[A30]** Claude Code, modo headless, Agent SDK e hooks: `--bare`, `--output-format stream-json`, `--resume`,
  SIGTERM, `--max-budget-usd`, hooks HTTP de fim de sessão. (página) https://code.claude.com/docs/en/headless ;
  https://code.claude.com/docs/en/agent-sdk/hosting ; https://code.claude.com/docs/en/hooks
- **[A31]** Claude Code, *Legal and compliance*, e os Termos de Consumidor (vigentes desde 08/10/2025): os limites dos
  planos Pro, Max e Ultra "assumem uso individual comum"; produtos devem usar chave de API ou provedor de nuvem; acesso
  automatizado vedado salvo por chave de API ou permissão explícita. (página)
  https://code.claude.com/docs/en/legal-and-compliance ; https://www.anthropic.com/legal/consumer-terms
- **[A32]** Claude Managed Agents (beta): sessões por API, stream SSE e webhooks (até 3 tentativas, sem ordem, depois
  descartados), 300 criações/min e 1.200 leituras/min por organização, tokens + US$ 0,08 por hora de sessão rodando.
  (página) https://platform.claude.com/docs/en/managed-agents/overview ;
  https://platform.claude.com/docs/en/managed-agents/webhooks
- **[A33]** Claude Code no Amazon Bedrock e no Google Cloud: `CLAUDE_CODE_USE_BEDROCK=1` com a cadeia de credenciais da
  AWS; `CLAUDE_CODE_USE_VERTEX=1`. (página) https://code.claude.com/docs/en/amazon-bedrock.md e
  https://code.claude.com/docs/en/google-vertex-ai.md
- **[A34]** AWS Price List, Bedrock (us-east-1, publicação de 12/10/2026): Claude no endpoint global ao preço da
  Anthropic (Haiku 5.5 0,10/0,50; Sonnet 5.5 2/10; Opus 5.5 4/20 por milhão de tokens; leitura de cache Sonnet 5.5
  0,10); endpoints regionais 10 % mais caros. (página) https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json
- **[A35]** Google Cloud, preços de modelos parceiros: Claude no Agent Platform aos mesmos preços. (página)
  https://cloud.google.com/model-garden/partner-models/pricing
- **[A36]** Cursor, pacote oficial `@cursor/sdk` 1.3.1 (03/11/2026): a API v1 de agentes em nuvem (`/v1/agents` com chave
  de idempotência, execuções, cancelamento, arquivo, stream SSE retomável), ambientes em nuvem, pool próprio ou máquina
  própria. O agente tem status `ACTIVE`, `IDLE` ou `ARCHIVED`; a execução, `CREATING`, `RUNNING`, `FINISHED`, `ERROR`,
  `CANCELLED` ou `EXPIRED` (`dist/esm/cloud-api-client.d.ts`). (página, pacote) https://www.npmjs.com/package/@cursor/sdk
- **[A37]** Cursor, webhooks da API de agentes: evento `statusChange`, assinatura HMAC-SHA256. (trecho)
  https://cursor.com/docs/cloud-agent/api/webhooks
- **[A38]** Fórum da Cursor (equipe): 8 agentes em nuvem simultâneos no plano Pro. (trecho)
  https://forum.cursor.com/t/cloud-agents-simultaneous-limit-what-are-the-actual-numbers-per-plan/154013
- **[A39]** Cursor, preços: agentes em nuvem cobrados ao preço de API do modelo; computação da VM "será precificada no
  futuro". (trecho) https://cursor.com/docs/account/pricing
- **[A40]** OpenAI Codex, repositório oficial: `codex exec` com eventos JSONL e `resume`, SDKs em TypeScript e Python,
  `codex cloud exec` sem API pública. Nas tarefas de nuvem, a tarefa (`Pending`, `Ready`, `Applied`, `Error`) é separada
  das tentativas (best-of-N, cada uma `Pending`, `InProgress`, `Completed`, `Failed` ou `Cancelled`), em
  `codex-rs/cloud-tasks-client/src/api.rs`. (página) https://raw.githubusercontent.com/openai/codex/main/README.md ; preços do
  Codex (trecho) https://developers.openai.com/codex/pricing
- **[A41]** AWS Bedrock AgentCore Runtime: uma microVM por sessão, ociosidade de 15 min e vida de 8 h por padrão (até 14
  dias), `StopRuntimeSession`; US$ 0,0895 por vCPU·h e US$ 0,00945 por GB·h (Price List); 25 sessões novas/s e 5.000
  ativas em us-east-1 (trecho). (página e trecho) https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html ;
  https://dev.classmethod.jp/articles/bedrock-agentcore-runtime-default-quota-increase-june-2026/
- **[A42]** Google Jules API, documento de descoberta v1alpha: sessões, atividades por consulta, mensagem e aprovação de
  plano; só GitHub. (página) https://jules.googleapis.com/$discovery/rest?version=v1alpha
- **[A43]** Kiro, agente autônomo: sem API pública; 10 tarefas simultâneas. (trecho)
  https://kiro.dev/docs/autonomous-agent/using-the-agent/
- **[A44]** Gemini CLI, modo headless: `gemini -p -o stream-json`, `-r` para retomar. (página)
  https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/cli/headless.md
- **[A45]** Sandboxes de terceiros: Daytona (US$ 0,0504 por vCPU·h + 0,0162 por GiB·h), Modal (US$ 0,00003942 por
  núcleo·s), E2B (~US$ 0,050 + 0,016). (trecho) https://www.daytona.io/pricing ;
  https://modal.com/docs/guide/sandbox-resources.md

- **[A46]** Claude, preços dos planos (04/11/2026): Pro US$ 20/mês; Max US$ 100/mês, 5× o uso do Pro a cada 5 h e por
  semana, com US$ 100 por mês em crédito de API; Ultra US$ 200/mês, com US$ 200. (página) https://claude.com/pricing
- **[A47]** Claude Code, referência da CLI e autenticação: `claude setup-token` gera "um token OAuth de longa duração
  para CI e scripts" e exige assinatura; `CLAUDE_CODE_OAUTH_TOKEN` para pipelines sem login no navegador. (página)
  https://code.claude.com/docs/en/cli-reference.md e https://code.claude.com/docs/en/authentication.md

## X. Segurança, observabilidade, limites físicos e economia

- **[X1]** Firecracker, `SPECIFICATION.md`: ≤ 125 ms do `InstanceStart` ao `init` do convidado; ≤ 5 MiB de memória do
  gerenciador por VM; 8 ms de CPU para o socket da API ficar pronto. (página)
  https://raw.githubusercontent.com/firecracker-microvm/firecracker/main/SPECIFICATION.md
- **[X2]** Firecracker, site do projeto: 150 microVMs por segundo por host. (página)
  https://raw.githubusercontent.com/firecracker-microvm/firecracker-microvm.github.io/master/index.html
- **[X3]** AWS News Blog (2025). Prime Day 2025: Lambda com 1,7 trilhão de invocações num dia; DynamoDB com pico de 151
  milhões de requisições/s. (trecho)
  https://aws.amazon.com/blogs/aws/aws-services-scale-to-new-heights-for-prime-day-2025-key-metrics-and-milestones
- **[X4]** Cloudflare, descrição dos isolates do Workers: partida "cerca de cem vezes mais rápida que um processo Node";
  2,2 ms de CPU por requisição em média. (página)
  https://raw.githubusercontent.com/cloudflare/cloudflare-docs/production/src/content/partials/workers/isolate-description.mdx
- **[X5]** Bytecode Alliance (2022). *Wasmtime 1.0: A Look at Performance*: instanciação do SpiderMonkey.wasm de 2 ms
  para 5 µs. (trecho) https://bytecodealliance.org/articles/wasmtime-10-performance
- **[X6]** Daytona README: sandbox criado em menos de 90 ms (fornecedor). (página)
  https://raw.githubusercontent.com/daytonaio/daytona/main/README.md
- **[X7]** gVisor, guia de desempenho: chamada de sistema crua de 1,94 µs (runc) a 38,2 µs (gVisor com ptrace) e 0,76 µs
  (gVisor com KVM); dados de ~2019–20. (página)
  https://raw.githubusercontent.com/google/gvisor/master/g3doc/architecture_guide/performance.md
- **[X8]** SLSA: v1.0 (19/04/2023) com os níveis de build L0 a L3; v1.2 (24/11/2025) acrescenta os níveis de fonte L1 a
  L4, em que L4 exige revisão de código. (página)
  https://raw.githubusercontent.com/slsa-framework/slsa/releases/v1.2/spec/source-requirements.md
- **[X9]** CNCF (23/04/2025). Graduação do in-toto. (trecho)
  https://www.cncf.io/announcements/2025/04/23/cncf-announces-graduation-of-in-toto-security-framework-enhancing-software-supply-chain-integrity-across-industries/
- **[X10]** Sigstore, roadmap: o log de transparência Rekor com mais de 101 milhões de entradas de mais de 33 mil
  projetos. (página) https://raw.githubusercontent.com/sigstore/community/main/ROADMAP.md
- **[X11]** Google, *Binary Authorization for Borg*: revisão por ao menos um engenheiro além do autor, proveniência
  assinada, pacote recusado na implantação. (trecho) https://cloud.google.com/docs/security/binary-authorization-for-borg
- **[X12]** OWASP GenAI, Top 10 para aplicações com LLM (2025 e a edição de 04/08/2026): injeção de prompt em primeiro;
  agência excessiva sobe para terceiro em 2026. (página)
  https://raw.githubusercontent.com/GenAI-Security-Project/GenAI-LLM-Top10/main/2026/README.md
- **[X13]** Debenedetti et al. (2025). *Defeating Prompt Injections by Design* (CaMeL): 77 % das tarefas do AgentDojo
  com segurança demonstrável, contra 84 % sem defesa. (trecho) https://arxiv.org/abs/2503.18813
- **[X14]** Beurer-Kellner et al. (2025). *Design Patterns for Securing LLM Agents against Prompt Injections*: seis
  padrões, dez estudos de caso. (trecho) https://arxiv.org/abs/2506.08837
- **[X15]** Willison, S. (16/06/2025). *The lethal trifecta for AI agents*: dado privado, conteúdo não confiável e
  comunicação externa juntos. (trecho) https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- **[X16]** Sigelman et al. (2010). *Dapper, a Large-Scale Distributed Systems Tracing Infrastructure*, Google: span de
  176 a 204 ns; amostragem de 1/1024 custa −0,20 % de latência e −0,06 % de vazão. (página, cópia do relatório)
  https://raw.githubusercontent.com/papers-we-love/papers-we-love/main/distributed_systems/dapper-a-large-scale-distributed-tracing-infrastructure.pdf
- **[X17]** OpenTelemetry: especificação v1.62.0 (21/10/2026); traços, logs e a API de métricas estáveis. (página)
  https://raw.githubusercontent.com/open-telemetry/opentelemetry-proto/main/README.md
- **[X18]** Google Cloud Blog (2020). *SRE error budgets and maintenance windows*: orçamento de erro = 100 % − SLO.
  (página) https://cloud.google.com/blog/products/management-tools/sre-error-budgets-and-maintenance-windows
- **[X19]** FoundationDB, *Testing*: ~1 trilhão de horas de CPU simuladas; dezenas de milhares de execuções por noite.
  (página) https://raw.githubusercontent.com/apple/foundationdb/main/documentation/sphinx/source/testing.rst
- **[X20]** AWS (20/09/2023). *Reducing the Scope of Impact with Cell-Based Architecture*. (trecho)
  https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.html
- **[X21]** Dean, J.; Norvig, P. *Latency numbers every programmer should know* (~2012): L1 0,5 ns; memória 100 ns;
  leitura de 4K em SSD 150 µs; ida e volta no datacenter 500 µs. (página, cópia)
  https://gist.github.com/jboner/2841832
- **[X22]** Eskildsen, S. *napkin-math* (medido em out–nov/2026): chamada de sistema 100 ns; troca de contexto 1 µs;
  criar thread 50 µs; criar processo 300 µs; ida e volta na mesma zona 100 µs; RDMA 5 µs. (página, benchmark de
  praticante) https://raw.githubusercontent.com/sirupsen/napkin-math/master/README.md
- **[X23]** eRPC: ida e volta de 2,3 µs; ~10 milhões de RPCs/s por núcleo. (página)
  https://raw.githubusercontent.com/erpc-io/eRPC/master/README.md
- **[X24]** Malitson (1965), índice de refração da sílica (dados): a luz na fibra leva 4,88 µs/km; o piso de ida e
  volta entre antípodas é 195,5 ms (conta da pesquisa). (página)
  https://raw.githubusercontent.com/polyanskiy/refractiveindex.info-database/master/database/data/main/SiO2/nk/Malitson.yml
- **[X25]** AWS, lista de preços do EC2 (us-east-1, 03/11/2026): m8g.large a US$ 0,08976/h (US$ 0,0449 por vCPU·h);
  instâncias de até 896 vCPU; spot economiza 61–63 %. (página)
  https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv
- **[X26]** Google Cloud, preços spot (Iowa, 04/11/2026): c4d-standard-384 a US$ 18,14/h sob demanda e US$ 7,65/h spot
  (US$ 0,0199 por vCPU·h). (página) https://cloud.google.com/spot-vms/pricing
- **[X27]** Armazenamento de objetos: S3 Standard US$ 0,023 a 0,021 por GB·mês; GCS Standard US$ 0,020 por GiB·mês.
  (página) https://cloud.google.com/storage/pricing
- **[X28]** Rede: saída para a internet de US$ 0,05 a 0,12 por GB; entre regiões US$ 0,02. (página)
  https://cloud.google.com/vpc/network-pricing
- **[X29]** Microsoft, resultados do 1º tri do ano fiscal de 2027: investimento em imóveis e equipamentos de US$ 115,9
  bilhões no ano fiscal de 2026 (até 30/06/2026). (página)
  https://www.microsoft.com/en-us/investor/earnings/FY-2027-Q1/press-release-webcast
- **[X30]** Software Heritage, estatísticas do grafo (export de 04/06/2026): 29,29 × 10^9 arquivos únicos, 5,95 × 10^9
  commits, 4,37 × 10^8 origens. (página)
  https://softwareheritage.s3.amazonaws.com/graph/2026-06-04/compressed/graph.nodes.stats.txt
- **[X31]** GitHub, API de busca (contagem feita pela pesquisa em 04/11/2026): 26.616.096 PRs públicas mergeadas em
  out/2026 (~9,94/s); 57.064.600 em 2025. (página, medição)
  https://api.github.com/search/issues?q=is:pr+is:merged+merged:2026-10-01..2026-10-31
- **[X32]** GitHub Innovation Graph, 2º tri de 2026: 407,6 milhões de pushes públicos, 209,1 milhões de contas de
  desenvolvedor, 453,5 milhões de repositórios públicos. (página)
  https://raw.githubusercontent.com/github/innovationgraph/main/data/git_pushes.csv

## W. Modelos de domínio, workflows e eventos

- **[W1]** Temporal, *Workflow Id and Run Id* e *Workflow Execution*: o Workflow Id é o id de negócio, único entre as
  execuções abertas de um namespace; o Run Id é único na plataforma; retentativa, cron e continue-as-new formam uma
  cadeia com o mesmo Workflow Id. Estados abertos `Running` e `Paused`; fechados `Completed`, `Failed`, `Canceled`,
  `Terminated`, `ContinuedAsNew` e `TimedOut`. (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/workflow/workflow-execution/workflowid-runid.mdx ;
  https://raw.githubusercontent.com/temporalio/api/master/temporal/api/enums/v1/workflow.proto
- **[W2]** Temporal, *Event History*, *Continue-As-New* e *Retry Policies*: "an append-only log of Events"; aviso em
  10.240 eventos e término acima de 51.200; continue-as-new mantém o Workflow Id com histórico novo. (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/workflow/workflow-execution/event.mdx
- **[W3]** Temporal, *Task Queues*, *message passing* e *Child Workflows*: Signal é escrita assíncrona, Update é escrita
  síncrona e rastreada, Query lê sem gravar; um filho por recurso serializa as operações dele. (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/child-workflows/child-workflows.mdx
- **[W4]** Kubernetes, *API Conventions*: `spec` é o estado desejado e `status` a observação mais recente;
  `generation` e `observedGeneration`; condições com `type`, `status`, `reason`, `message` e `lastTransitionTime`,
  "observations and not, themselves, state machines"; `phase` obsoleto porque um enum novo quebra compatibilidade;
  `resourceVersion` para concorrência otimista (409 na divergência). (página)
  https://raw.githubusercontent.com/kubernetes/community/master/contributors/devel/sig-architecture/api-conventions.md
- **[W5]** Kubernetes, *Owners and Dependents*, *Finalizers* e *Controllers*: `ownerReferences` com nome e UID do dono;
  a remoção com finalizers só termina quando cada controlador tira a sua chave; o controlador aproxima o atual do
  desejado. (página)
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/overview/working-with-objects/owners-dependents.md
- **[W6]** CloudEvents 1.0.2: obrigatórios `id`, `source`, `specversion` e `type`; opcionais `datacontenttype`,
  `dataschema`, `subject` e `time`; "Producers MUST ensure that source + id is unique for each distinct event", e o
  consumidor pode tratar a repetição como duplicata; o `type` "SHOULD be prefixed with a reverse-DNS name", e o domínio
  do prefixo diz quem define a semântica do tipo. (página)
  https://raw.githubusercontent.com/cloudevents/spec/v1.0.2/cloudevents/spec.md
- **[W7]** Apache Airflow, `utils/state.py` e `models/taskinstance.py`: estados da tarefa `scheduled`, `queued`,
  `running`, `success`, `failed`, `up_for_retry`, `up_for_reschedule`, `upstream_failed`, `skipped`, `removed`,
  `restarting`, `deferred`, `awaiting_input`; "every try of a task is its own row … only the latest try is live". (página)
  https://raw.githubusercontent.com/apache/airflow/main/airflow-core/src/airflow/utils/state.py
- **[W8]** GitHub, guia de checks: a suíte é "a collection of the check runs created by a single GitHub App for a
  specific commit"; o check run tem status (`queued`, `in_progress`, `completed`…) e conclusão (`success`, `failure`,
  `neutral`, `cancelled`, `skipped`, `timed_out`, `action_required`) separados. (página)
  https://raw.githubusercontent.com/github/docs/main/content/rest/guides/using-the-rest-api-to-interact-with-checks.md
- **[W9]** GitHub, o webhook `merge_group` e a `MergeQueueEntry` do GraphQL: o grupo tem `head_sha`, `head_ref`,
  `base_sha` e `base_ref`; a entrada tem posição, estado (`QUEUED`, `AWAITING_CHECKS`, `MERGEABLE`, `UNMERGEABLE`,
  `LOCKED`) e os commits de base e de head. (página)
  https://raw.githubusercontent.com/github/docs/main/src/graphql/data/fpt/schema.docs.graphql
- **[W10]** Evans, E. (2015). *Domain-Driven Design Reference*: o agregado tem fronteira e raiz, e de fora só se guarda
  referência para a raiz; o contexto delimitado é onde o modelo vale, com fronteiras de equipe, de uso e de
  manifestação física, como código e esquema de banco. (trecho)
  https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf
- **[W11]** Vernon, V. (2011). *Effective Aggregate Design*, partes I a III: "Model True Invariants in Consistency
  Boundaries", "Design Small Aggregates", "Reference Other Aggregates by Identity", "Use Eventual Consistency Outside
  the Boundary". (trecho) https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_1.pdf
- **[W12]** Garcia-Molina, H.; Salem, K. (1987). *Sagas*. SIGMOD, pp. 249–259: a transação longa vira uma sequência de
  transações, e compensações desfazem o parcial. (trecho) https://dl.acm.org/doi/10.1145/38713.38742
- **[W13]** Hohpe, G.; Woolf, B. (2003). *Process Manager*: guarda o estado da sequência e decide o próximo passo pelos
  resultados intermediários. (trecho)
  https://www.enterpriseintegrationpatterns.com/patterns/messaging/ProcessManager.html
- **[W14]** Richardson, C. *Transactional outbox*: a mensagem vai para uma tabela de saída na transação do dado; um relé
  publica e pode repetir, então o consumidor tolera duplicata. (trecho)
  https://microservices.io/patterns/data/transactional-outbox.html
- **[W15]** Confluent Schema Registry, `CompatibilityLevel.java` e `docs/api.rst`: `BACKWARD` (o padrão), `FORWARD`,
  `FULL` e as variantes transitivas, contra todas as versões anteriores; o incompatível volta com 409. (página)
  https://raw.githubusercontent.com/confluentinc/schema-registry/master/client/src/main/java/io/confluent/kafka/schemaregistry/CompatibilityLevel.java
- **[W16]** *Parallel Change* ("expand and contract"): expandir (o velho e o novo convivem), migrar (os clientes passam),
  contrair (o velho sai). Autor e data não conferidos. (trecho) https://martinfowler.com/bliki/ParallelChange.html
- **[W17]** Young, G. *Versioning in an Event Sourced System*: o sumário traz versão por tipo de evento, escrita dupla e
  upcasting; o texto não foi alcançado. (trecho) https://leanpub.com/esversioning
- **[W18]** Claude Agent SDK, *Sessions*: o `session_id` vem no resultado; `resume` retoma um id, `fork` cria uma sessão
  nova com cópia do histórico; "sessions persist the conversation, not the filesystem". (página)
  https://code.claude.com/docs/en/agent-sdk/sessions.md
- **[W19]** OpenHands, eventos (tag 0.59.0 e o SDK V1): o evento é imutável, tem `id`, `source` e a causa (o id do
  evento que o causou); a observação aponta a ação. (página)
  https://raw.githubusercontent.com/OpenHands/OpenHands/0.59.0/openhands/events/event.py
- **[W20]** LangGraph, *checkpointers* e `langgraph_sdk/schema.py`: a thread acumula o estado de uma sequência de
  execuções; o checkpoint é um retrato por passo, com `thread_id` e `checkpoint_id`; execução concorrente na mesma
  thread é recusada, interrompida, desfeita ou enfileirada. (página)
  https://raw.githubusercontent.com/langchain-ai/docs/main/src/oss/langgraph/checkpointers.mdx

- **[W21]** DBOS Transact (Python), *Workflows* e *contexts*: `start_workflow` devolve o handle de um workflow já
  gravado, que roda até o fim; o pai espera com `get_result()`; o id do workflow é chave de idempotência ("executes only
  once"); o filho guarda o `parent_workflow_id`, e o timeout cancela o workflow "and all its children". (página)
  https://raw.githubusercontent.com/dbos-inc/dbos-docs/main/docs/python/tutorials/workflow-tutorial.md
- **[W22]** DBOS Transact (Python), *Queues* e *Steps*: fila com `worker_concurrency` e `global_concurrency`; o fan-out
  enfileira um filho por tarefa e junta os resultados; `deduplication_id` barra um segundo workflow ativo com o mesmo
  id; o passo roda ao menos uma vez e nunca de novo depois de concluído, com repetição opcional. (página)
  https://raw.githubusercontent.com/dbos-inc/dbos-docs/main/docs/python/tutorials/queue-tutorial.md
- **[W23]** Argo Workflows, *DAG* e *Enhanced Depends*: cada tarefa lista as suas `dependencies`; `depends` é uma
  expressão sobre o resultado das anteriores; por padrão, "when one task fails, no new tasks will be scheduled".
  (página) https://raw.githubusercontent.com/argoproj/argo-workflows/main/docs/walk-through/dag.md
- **[W24]** Apache Airflow, *DAGs* e *trigger rules*: o padrão `all_success` espera todos os pais diretos; 13 regras,
  entre elas `one_failed` e `none_failed_min_one_success`, a da junção depois de um ramo. (página)
  https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/core-concepts/dags.rst
- **[W25]** Bazel, perfil e `metrics/criticalpath`: o perfil mostra "one block for each action on the critical path"; o
  build termina com o tempo total e o do caminho crítico; o *drag* é "the amount of time that can potentially be saved
  by removing a particular node". (página)
  https://raw.githubusercontent.com/bazelbuild/bazel/master/docs/advanced/performance/build-performance-metrics.mdx
- **[W26]** GitHub Actions, `needs`: os jobs "run in parallel by default"; `needs` exige que os listados terminem com
  sucesso, e uma falha segue a cadeia "from the point of failure or skip onwards". (página)
  https://raw.githubusercontent.com/github/docs/main/data/reusables/actions/jobs/section-using-jobs-in-a-workflow-needs.md
- **[W27]** Buildkite, `depends_on`: sem dependência, "given enough agents, these steps would run in parallel"; existe
  `allow_dependency_failure`. (página)
  https://raw.githubusercontent.com/buildkite/docs/main/pages/pipelines/configure/depends_on.md
- **[W28]** Kelley, J. E., Jr.; Walker, M. R. (1959). *Critical-Path Planning and Scheduling*. Eastern Joint Computer
  Conference, pp. 160–173; e Kelley (1961), *Operations Research* 9(3):296–320. O caminho crítico é a cadeia mais longa
  de atividades dependentes, fixa a duração mínima e tem folga zero. (trecho)
  https://doi.org/10.1145/1460299.1460318 ; https://doi.org/10.1287/opre.9.3.296
- **[W29]** Malcolm, D. G. et al. (1959). *Application of a Technique for Research and Development Program
  Evaluation* (PERT). *Operations Research* 7(5):646–669: o programa como rede de eventos dependentes, com estimativa de
  tempo por atividade. (trecho) https://doi.org/10.1287/opre.7.5.646
- **[W30]** Gerrit, *Review UI* e a API REST: *Related Changes* lista ancestrais e descendentes; uma mudança só é
  submetível "when all of its ancestors are submitted"; a dependência de um patch set velho "now needs to be rebased".
  (página) https://raw.githubusercontent.com/GerritCodeReview/gerrit/master/Documentation/user-review-ui.txt
- **[W31]** Phabricator, `arc land`: pousa os ancestrais do ref, toda a pilha num push só ou um a um com
  `--incremental`, e depois rebaseia os descendentes locais. (página)
  https://raw.githubusercontent.com/phacility/arcanist/master/src/workflow/ArcanistLandWorkflow.php
- **[W32]** ghstack, README: um PR por commit, ramos base e head "never force pushed"; o custo é que "you have to
  resolve conflicts in *each* PR". (página) https://raw.githubusercontent.com/ezyang/ghstack/master/README.md
- **[W33]** Sapling (Meta), *stacks* e `restack`: `sl pr submit --stack` abre PRs sobrepostos, lidos um commit por
  vez; emendar um commit deixa os descendentes órfãos até o `restack`. (página)
  https://raw.githubusercontent.com/facebook/sapling/main/website/docs/git/sapling-stack.md
- **[W34]** git-branchless: `git restack` conserta os descendentes depois de emendar; `git submit` faz force-push da
  pilha, o que "will overwrite public history". (página)
  https://raw.githubusercontent.com/arxanas/git-branchless/master/README.md
- **[W35]** Graphite: `gt restack` põe cada ramo sobre a versão atual do pai e para no conflito. (trecho)
  https://graphite.com/docs/restack-branches
- **[W36]** Google, *Small CLs*: o tamanho certo é "one self-contained change", com os testes, e o sistema funcionando
  depois; recomenda empilhar o próximo CL sobre o primeiro e nunca quebrar o build entre submissões. (página)
  https://raw.githubusercontent.com/google/eng-practices/master/review/developer/small-cls.md
- **[W37]** Linux, *Submitting patches*: "Separate each logical change into a separate patch"; declarar "this patch
  depends on patch X"; compilar depois de cada patch, porque o `git bisect` pode cortar a série em qualquer ponto.
  (página) https://raw.githubusercontent.com/torvalds/linux/master/Documentation/process/submitting-patches.rst
- **[W38]** Git, *SubmittingPatches*: "Make separate commits for logically separate changes". (página)
  https://raw.githubusercontent.com/git/git/master/Documentation/SubmittingPatches
- **[W39]** Claude Code, *Track todos* e *Agent teams*: tarefas com estado `pending`, `in_progress` e `completed` e
  dependências; numa equipe, a tarefa dependente fica bloqueada e o colega pega "the next unassigned, unblocked task".
  (página) https://code.claude.com/docs/en/agent-sdk/todo-tracking.md ; https://code.claude.com/docs/en/agent-teams.md
- **[W40]** OpenHands SDK, `TaskTrackerTool`: itens com título, notas e estado (`todo`, `in_progress`, `done`); um em
  andamento por vez, e nunca `done` "while tests fail"; a lista persiste em arquivo. (página)
  https://raw.githubusercontent.com/OpenHands/software-agent-sdk/main/openhands-tools/openhands/tools/task_tracker/definition.py
- **[W41]** LangGraph, *Plan-and-Execute*: o estado guarda o plano e os passos feitos, executa o primeiro e replaneja o
  resto; o limite admitido é que "each task is still executed in sequence". (página)
  https://raw.githubusercontent.com/langchain-ai/langgraph/0.3.0/docs/docs/tutorials/plan-and-execute/plan-and-execute.ipynb
- **[W42]** Kim, S. et al. (2023). *An LLM Compiler for Parallel Function Calling*, arXiv 2312.04511: o planejador emite
  um DAG de tarefas, e a unidade de busca "schedules and executes the tasks as soon as they are executable". (página)
  https://raw.githubusercontent.com/SqueezeAILab/LLMCompiler/main/README.md

## B. Plantas de sistemas e padronização na AWS

- **[B1]** Brown, S. *The C4 model*, abstrações: o sistema de software é feito de contêineres (aplicações e bancos), cada
  um com componentes; o contêiner é a fronteira de execução e a unidade implantável. (página)
  https://raw.githubusercontent.com/simonbrowndotje/c4model/master/abstractions/index.md
- **[B2]** C4, diagramas: quatro níveis estáticos, mas "you don't need to use all 4 levels"; apoio de paisagem, dinâmico e
  de implantação (um ambiente por diagrama); cada fila ou tópico é um contêiner. (página)
  https://raw.githubusercontent.com/simonbrowndotje/c4model/master/diagrams/index.md
- **[B3]** Structurizr DSL: `workspace` com `model` e `views`; "all relationships from a source element to a destination
  element must have a unique description"; importa ADRs. (página)
  https://raw.githubusercontent.com/structurizr/structurizr.github.io/main/dsl/71-language.md
- **[B4]** arc42, template 9.1: doze seções, de introdução e metas a glossário, com a visão de blocos obrigatória.
  (página) https://raw.githubusercontent.com/arc42/arc42-template/main/EN/arc42-template.adoc
- **[B5]** arc42, seção 5: a caixa-preta traz propósito, interfaces com qualidades e desempenho e, como opcionais, local,
  requisitos e riscos. (página) https://raw.githubusercontent.com/arc42/arc42-template/main/EN/adoc/05_building_block_view.adoc
- **[B6]** ISO/IEC/IEEE 42010:2022, *Architecture description*: requisitos da descrição, de frameworks, de linguagens e de
  pontos de vista. (trecho) https://www.iso.org/standard/74393.html
- **[B7]** 42010 por fontes secundárias (glossário do iSAQB): interessado, preocupação, ponto de vista, vista e regra de
  correspondência. (página, secundária)
  https://raw.githubusercontent.com/isaqb-org/glossary/main/docs/1-terms/C/term-correspondence.adoc
- **[B8]** Kruchten, P. (1995). *The "4+1" View Model of Software Architecture*. IEEE Software 12(6):42–50: as vistas
  lógica, de processo, de desenvolvimento e física, e os cenários. (página, transcrição de terceiros)
  https://raw.githubusercontent.com/Mosekjaer/prepmeup/main/context/swd/markdown/artikler/SW4SWD-01_4plus1_View_Kruchten_1995.md
- **[B9]** DDD Crew, *Context Mapping*: nove padrões de relação entre contextos. (página)
  https://raw.githubusercontent.com/ddd-crew/context-mapping/main/README.md
- **[B10]** DDD Crew, *Bounded Context Canvas* v5: propósito, classificação, comunicação de entrada e de saída,
  linguagem, decisões, premissas, métricas de verificação. (página)
  https://raw.githubusercontent.com/ddd-crew/bounded-context-canvas/main/README.md
- **[B11]** Backstage, *System Model*: componente, API, recurso, usuário e grupo, sistema e domínio. (página)
  https://raw.githubusercontent.com/backstage/backstage/master/docs/features/software-catalog/system-model.md
- **[B12]** Backstage, *Descriptor Format* e *Well-known Relations*: o envelope do descritor, o dono único e as relações
  aos pares. (página) https://raw.githubusercontent.com/backstage/backstage/master/docs/features/software-catalog/descriptor-format.md
- **[B13]** Nygard, M. (2011). *Documenting Architecture Decisions*: contexto, decisão, estado e consequências; números
  "will not be reused". (página, cópia integral)
  https://raw.githubusercontent.com/dbt-labs/dbt-utils/main/docs/decisions/adr-0000-documenting-architecture-decisions.md
- **[B14]** adr.github.io, adr-tools e MADR 4.0.0: o registro de decisões e a confirmação. (página)
  https://raw.githubusercontent.com/adr/madr/4.0.0/template/adr-template.md
- **[B15]** AWS Organizations, boas práticas da conta de gerenciamento: só o indispensável nela, porque as SCPs "do not
  work to restrict any users or roles in the management account". (página, awsdocs arquivado em 06/2023)
  https://raw.githubusercontent.com/awsdocs/aws-organizations-docs/main/doc_source/orgs_best-practices_mgmt-acct.md
- **[B16]** AWS Organizations, *Tag policies*: padronizam chave e capitalização; recurso sem tag não aparece como fora do
  padrão. (página) https://raw.githubusercontent.com/awsdocs/aws-organizations-docs/main/doc_source/orgs_manage_policies_tag-policies.md
- **[B17]** AWS Billing, *cost allocation tags*: só contam depois de ativadas e não retroagem. (página)
  https://raw.githubusercontent.com/awsdocs/aws-cost-management-user-guide/master/doc_source/allocation-tag-restrictions.md
- **[B18]** AWS Control Tower, estratégia de múltiplas contas: "an AWS account acts as a resource container and resource
  isolation boundary"; cobrança e cotas por conta. (página)
  https://raw.githubusercontent.com/awsdocs/aws-control-tower-guide/main/doc_source/aws-multi-account-landing-zone.md
- **[B19]** AWS, *Organizing Your AWS Environment Using Multiple Accounts*: OUs por função e controles, não pelo
  organograma. (trecho) https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/recommended-ous.html
- **[B20]** AWS, *Best Practices for Tagging AWS Resources*: minúsculas, hífens e prefixo da organização; tags não são
  cifradas, então sem dado pessoal. (trecho)
  https://docs.aws.amazon.com/whitepapers/latest/tagging-best-practices/adopt-a-standardized-approach-for-tag-names.html
- **[B21]** AWS Well-Architected: seis pilares; separar cargas e ambientes em contas (SEC01-BP01); recursos sem tag de
  dono são antipadrão (OPS02-BP01); um esquema de tags (COST03-BP02). (página, cópia em aws-samples)
  https://raw.githubusercontent.com/aws-samples/sample-well-architected-skills-and-steering/main/skills/aws-well-architected-framework-review/references/manifest.md

## L. Agentes de autonomia longa e aprendizado

- **[L1]** METR (2025). *Measuring AI Ability to Complete Long Tasks*: o horizonte de 50 % (a duração humana das tarefas
  que o agente termina metade das vezes) dobrou a cada ~7 meses de 2019 a 2025. (trecho) https://arxiv.org/abs/2503.14499
- **[L2]** METR (29/01/2026). *Time Horizon 1.1*: tarefas revistas; o dobro em ~196 dias no geral e em ~89–109 dias para
  os modelos desde 2024. (trecho) https://metr.org/blog/2026-01-29-time-horizon-1-1/
- **[L3]** METR (19/05/2026). *Frontier Risk Report*: a fronteira pública em ~12 h (5 a 61 h); a medida "can't reliably
  measure time horizons above 16 hours". (trecho) https://metr.org/blog/2026-05-19-frontier-risk-report/
- **[L4]** METR (26/06/2026). Avaliação do GPT-5.6 Sol: ~11,3 h quando trapaça conta como falha. (trecho)
  https://metr.org/blog/2026-06-26-gpt-5-6-sol/
- **[L5]** Anthropic (2024). *Building effective agents*: "find the simplest solution possible"; o agente tira a verdade
  do ambiente a cada passo, pausa em pontos de verificação e tem condição de parada. (página)
  https://www.anthropic.com/research/building-effective-agents
- **[L6]** Anthropic (2025). *How we built our multi-agent research system*: o plano vai para a memória porque o contexto
  passa de 200 mil tokens; fases terminadas viram resumo e subagentes novos assumem; avaliação começa com ~20 casos,
  porque os efeitos são grandes (30 % → 80 %). (página) https://www.anthropic.com/research/multi-agent-research-system
- **[L7]** Anthropic (2025). *Effective context engineering for AI agents*: a compactação guarda decisões, erros abertos
  e detalhes; notas para trabalho com marcos; subagentes devolvem 1 a 2 mil tokens. (página)
  https://www.anthropic.com/research/effective-context-engineering-for-ai-agents
- **[L8]** Anthropic (11/2025). *Effective harnesses for long-running agents*: "compaction isn't sufficient"; um
  inicializador escreve o arquivo de progresso e uma lista de funcionalidades em JSON; cada sessão faz uma, comita e
  marca só o `passes`; falhas: fazer tudo de uma vez, declarar vitória cedo, marcar pronto sem teste de ponta a ponta.
  (página) https://www.anthropic.com/research/effective-harnesses-for-long-running-agents
- **[L9]** Anthropic (03/2026). *Harness design for long-running application development*: planejador, gerador e
  avaliador; reinício de contexto com passagem estruturada; critérios de pronto combinados em arquivo; "Every component
  in a harness encodes an assumption about what the model can't do on its own". (página)
  https://www.anthropic.com/research/harness-design-long-running-apps
- **[L10]** Claude Platform, *Memory tool*: "ASSUME INTERRUPTION"; ler a memória antes de tudo e atualizá-la por último;
  limitar o tamanho dos arquivos e expirar os que ninguém lê. (página)
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- **[L11]** Cognition (2025). *Don't Build Multi-Agents*: compartilhar o rastro inteiro do agente; "actions carry
  implicit decisions, and conflicting decisions carry bad results". (trecho) https://cognition.ai/blog/dont-build-multi-agents
- **[L12]** Cognition (04/2026). *Multi-Agents: What's Actually Working*: funciona a classe em que os agentes contribuem
  inteligência e a escrita fica numa linha só. (trecho) https://cognition.com/blog/multi-agents-working
- **[L13]** OpenAI (2025). *A practical guide to building agents*: uma pessoa entra quando um limite de falhas é passado
  ou antes de ação de alto risco; ferramentas classificadas por acesso, reversibilidade e impacto financeiro. (trecho)
  https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- **[L14]** OpenAI Agents SDK, *Guardrails* e *Human-in-the-loop*: a aprovação pausa a execução, e o estado serializado
  retoma depois, até noutro processo. (página)
  https://raw.githubusercontent.com/openai/openai-agents-python/main/docs/human_in_the_loop.md
- **[L15]** Shinn et al. (2023). *Reflexion*: depois de uma tentativa falha, o agente escreve uma reflexão na memória da
  tarefa, e as últimas voltam no próximo passo. (página) https://raw.githubusercontent.com/noahshinn/reflexion/main/README.md
- **[L16]** Zhao et al. (2024). *ExpeL*: percepções extraídas das trajetórias com AGREE, EDIT, ADD e REMOVE; a regra que
  chega a zero sai; trajetórias parecidas recuperadas por vizinhos próximos. (página)
  https://raw.githubusercontent.com/LeapLabTHU/ExpeL/main/agent/expel.py
- **[L17]** Wang et al. (2023). *Voyager*: a habilidade é código, guardada só quando o crítico confirma o sucesso, e
  recuperada pela descrição; o currículo automático propõe uma tarefa por vez, "not too hard" e nova, sabendo as
  concluídas e as que falharam por difíceis demais, e evita as que pedem informação além do estado visível para verificar.
  (página) https://raw.githubusercontent.com/MineDojo/Voyager/main/voyager/agents/skill.py ;
  https://raw.githubusercontent.com/MineDojo/Voyager/main/voyager/prompts/curriculum.txt
- **[L18]** Wang et al. (2024). *Agent Workflow Memory*: rotinas induzidas dos sucessos, julgados por um avaliador
  automático. (página) https://raw.githubusercontent.com/zorazrw/agent-workflow-memory/main/webarena/pipeline.py
- **[L19]** Zhang et al. (2025). *Darwin Gödel Machine*: um arquivo de versões do agente; toda mudança é validada num
  benchmark antes de entrar; o pai da próxima versão é sorteado com peso sigmoid(10·(nota − 0,5)) × 1/(1 + filhos).
  (página) https://raw.githubusercontent.com/jennyzzt/dgm/main/DGM_outer.py
- **[L20]** Google, *SRE Book*, "Postmortem Culture": "writing a postmortem is not punishment"; gatilhos definidos antes.
  (trecho) https://sre.google/sre-book/postmortem-culture/
- **[L21]** Google, *SRE Workbook*, capítulo 10: cada ação com um dono, uma prioridade e acompanhamento; ação sem
  acompanhamento é esquecida. (trecho) https://sre.google/workbook/postmortem-culture/
- **[L22]** Argyris, C. (1991). *Teaching Smart People How to Learn*, HBR: laço simples corrige a ação; laço duplo
  questiona os objetivos e as normas. (trecho) https://hbr.org/1991/05/teaching-smart-people-how-to-learn
- **[L23]** Rother, M. *Toyota Kata*: condição-alvo medida e com data; cada experimento compara o previsto com o real; um
  obstáculo por vez. (trecho) https://www-personal.umich.edu/~mrother/Handbook/PDCA.pdf
- **[L24]** DORA (01/2026). *Software delivery performance metrics*: vazão e instabilidade em tensão; nunca uma métrica
  como objetivo. (página)
  https://raw.githubusercontent.com/dora-team/dora.dev/main/hugo/content/guides/dora-metrics/_index.md
- **[L25]** Google Cloud (2020). *Four Keys*: eventos classificados em mudanças, implantações e incidentes. (página)
  https://cloud.google.com/blog/products/devops-sre/using-the-four-keys-to-measure-your-devops-performance
- **[L26]** Microsoft ExP (2021). *Patterns of trustworthy experimentation*: guardas que não devem piorar; alarme nelas e
  parada automática do teste que faz mal. (página)
  https://www.microsoft.com/en-us/research/group/experimentation-platform-exp/articles/patterns-of-trustworthy-experimentation-during-experiment-stage/
- **[L27]** Schultzberg et al. (Spotify, 2024): adotar se não pior em toda guarda, numa margem definida antes, e melhor
  em ao menos uma métrica de sucesso. (trecho) https://arxiv.org/abs/2402.11609

## N. Direção: objetivos, apostas e planejadores

Os sites destas fontes estavam bloqueados nesta sessão (04/11/2026), exceto o GitHub; dos livros (Grove, Doerr, Bryar e
Carr, Torres) só se viram citações.

- **[N1]** Google re:Work, *Set goals with OKRs*: objetivos "ambitious and may feel somewhat uncomfortable"; resultados
  medidos e notados de 0 a 1,0 por trimestre, em geral 3 a 5 objetivos com ~3 resultados cada; a faixa boa é 60 a 70 %.
  (trecho) https://rework.withgoogle.com/intl/en/guides/set-goals-with-okrs
- **[N2]** Google, manual de OKRs citado pelo What Matters: o OKR comprometido espera 1,0, e nota menor "requires
  explanation for the miss"; o aspiracional espera em média 0,7 "with high variance" e segue até ser cumprido. (trecho)
  https://www.whatmatters.com/faqs/committed-aspirational-okrs-examples-difference
- **[N3]** Doerr, J. *Measure What Matters*, citado: "an objective is simply WHAT is to be achieved"; os resultados-chave
  "benchmark and monitor HOW", específicos, com prazo, mensuráveis e verificáveis. (trecho)
  https://www.whatmatters.com/faqs/how-many-okrs-to-have
- **[N4]** Grove, A. (Intel), citado: "The Key Result has to be measurable. At the end, you can look and without any
  argument, say, 'Did I do that or did I not do it?'". (trecho)
  https://www.whatmatters.com/okrs-explained/what-is-a-key-result
- **[N5]** Singer, R. *Shape Up* (Basecamp): o apetite é um orçamento de tempo, "as opposed to an estimate", com tempo
  fixo e escopo variável; sem backlog, só propostas recentes ou revividas competem; a aposta compromete um time por um
  ciclo sem interrupção; disjuntor: sem extensão por padrão, a aposta perde no máximo um ciclo. (trecho)
  https://basecamp.com/shapeup/1.2-chapter-03 ; https://basecamp.com/shapeup/2.2-chapter-08
- **[N6]** Kniberg, H. (2016). *Spotify Rhythm*: dos OKRs às apostas defendidas com DIBB (Data, Insight, Belief, Bet),
  ordenadas pelas crenças da empresa e pela métrica-norte, em agora, próximo e depois. (trecho)
  https://blog.crisp.se/2016/06/08/henrikkniberg/spotify-rhythm
- **[N7]** Amplitude, *North Star Playbook*: a métrica-norte é "a single critical rate, count, or ratio that represents
  your product strategy", um resultado (variável dependente), movido por entradas independentes, de 3 a 5. (trecho, de
  cópia) https://info.amplitude.com/rs/138-CDN-550/images/Amplitude-The-North-Star-Playbook.pdf
- **[N8]** Bryar, C.; Carr, B. *Working Backwards*, trecho na About Amazon: começar pela experiência de quem usa e voltar
  até ficar claro o que construir; o comunicado tem "always less than one page", e o FAQ, cinco páginas ou menos. (trecho)
  https://www.aboutamazon.com/news/workplace/an-insider-look-at-amazons-culture-and-processes
- **[N9]** Bryar, C.; Carr, B. *Single-Threaded Leadership*: a pessoa mais sênior em tempo integral numa iniciativa, com
  autoridade e recursos para entregá-la; alinhar objetivos e métricas antes, porque "fire and forget" é arriscado. (trecho)
  https://workingbackwards.com/concepts/amazon-single-threaded-teams/
- **[N10]** Bryar, C.; Carr, B. *S-Team goals*: uma lista plana de metas, quase todas de entrada controlável, porque a
  saída "can't be directly or sustainably manipulated"; cumprida ou não, sem crédito parcial; ~70 % se cumprem. (trecho)
  https://workingbackwards.com/blog/amazon-s-team-execution-focused-goal-review-process/
- **[N11]** Torres, T. *Opportunity Solution Trees*: resultado, oportunidades, soluções e testes de suposição; "Is there
  more than one way to address this opportunity?"; comparar várias soluções e testar primeiro as suposições mais
  arriscadas. (trecho) https://www.producttalk.org/opportunity-solution-trees/
- **[N12]** Adzic, G. *Impact Mapping*: meta, atores, impactos e entregas; as entregas são o "least important level" e
  saem quando não contribuem; as métricas de impacto se revisam com frequência. (trecho)
  https://www.impactmapping.org/drawing.html
- **[N13]** Ahn et al. (2022). *SayCan*: cada habilidade pontuada por `np.exp(llm_scores[option]) *
  affordance_scores[option]`, utilidade vezes viabilidade; `done()` encerra o plano. (página)
  https://raw.githubusercontent.com/google-research/google-research/master/saycan/README.md
- **[N14]** Lu et al. (2024). *The AI Scientist*: cada ideia com notas de "Interestingness", "Feasibility" e "Novelty" de
  1 a 10; custo "typically less than $15 per paper". (página)
  https://raw.githubusercontent.com/SakanaAI/AI-Scientist/main/ai_scientist/generate_ideas.py
- **[N15]** Liu et al. (2025). *Budget-Aware Tool-Use*: orçamento maior sozinho não ajuda, porque falta aos agentes
  "budget awareness"; um rastreador mostra o usado e o restante a cada rodada. (trecho) https://arxiv.org/abs/2511.17006
- **[N16]** Ye, Tan (2026). *Agent Contracts*: o contrato junta especificação de entrada e saída, limites de recurso,
  prazo e critério de sucesso; orçamentos proíbem, critérios obrigam, e o orçamento delegado respeita o do pai. (trecho)
  https://arxiv.org/abs/2601.08815
- **[N17]** Falconi, V. (2009). *O Verdadeiro Poder*: a obtenção de resultados depende de três fatores, liderança,
  conhecimento técnico e método, e o método é estabelecer uma meta e criar as condições para atingi-la. Daniel o resumiu
  em 04/11 11:37 como "liderança, método de gestão e conhecimento técnico"; o livro não foi lido nesta sessão. (trecho,
  de material didático) https://edisciplinas.usp.br/pluginfile.php/5114147/mod_resource/content/1/Aula%202%20-%20Lideran%C3%A7a.pdf

## K. Núcleos, camadas e a separação entre mecanismo e política

- **[K1]** Brinch Hansen, P. (1970). *The Nucleus of a Multiprogramming System*. CACM 13(4):238–242: um sistema que
  "can be extended with a hierarchy of operating systems to suit diverse requirements of program scheduling and resource
  allocation"; o problema central "is not to define functions that satisfy specific operating needs, but rather to supply
  a system nucleus". (trecho) https://www.read.seas.harvard.edu/cs161/2019/pdf/hansen70nucleus.pdf
- **[K2]** Wulf, W. et al. (1974). *HYDRA: The Kernel of a Multiprocessor Operating System*. CACM 17(6):337–345: um
  conjunto de mecanismos "from which an arbitrary set of operating system facilities and policies can be conveniently,
  flexibly, efficiently, and reliably constructed"; a decisão de política fica fora do núcleo. (trecho)
  https://home.cs.colorado.edu/~rhan/CSCI_5573_Fall_2011/Papers/wulf74.pdf
- **[K3]** Levin, R. et al. (1975). *Policy/Mechanism Separation in Hydra*. SOSP 1975: a separação completa é
  impraticável, e uma política do núcleo parametrizada é o meio-termo necessário. (trecho, de resumo de curso)
  https://swift.sites.cs.wisc.edu/classes/cs736-sp07/blog/2007/01/policymechanism_separation_in.html
- **[K4]** Engler, D.; Kaashoek, M. F.; O'Toole, J. (1995). *Exokernel: An Operating System Architecture for
  Application-Level Resource Management*. SOSP 1995: "separate protection from management"; proteger "disks without
  understanding file systems"; um núcleo mínimo multiplexa os recursos, e sistemas operacionais de biblioteca fazem as
  abstrações. (trecho) https://www.read.seas.harvard.edu/~kohler/class/aosref/engler95exokernel.pdf
- **[K5]** Apache Mesos, *Architecture*: o mestre oferece recursos aos frameworks e "decides how many resources to offer
  to each framework according to a given organizational policy, such as fair sharing or strict priority", com módulos de
  alocação plugáveis; cada framework tem o seu escalonador e o seu executor. (página)
  https://raw.githubusercontent.com/apache/mesos/master/docs/architecture.md
- **[K6]** Apache Hadoop, *YARN*: "split up the functionalities of resource management and job scheduling/monitoring into
  separate daemons", um ResourceManager global e um ApplicationMaster por aplicação, "in effect, a framework specific
  library"; "The Scheduler has a pluggable policy which is responsible for partitioning the cluster resources among the
  various queues", e o CapacityScheduler e o FairScheduler são plug-ins dele. (página) https://raw.githubusercontent.com/apache/hadoop/trunk/hadoop-yarn-project/hadoop-yarn/hadoop-yarn-site/src/site/markdown/YARN.md
- **[K7]** Kubernetes, *Annotations* e *Labels*: anotações guardam "arbitrary non-identifying metadata"; rótulos "can be
  used to select objects", e anotações "are not used to identify and select objects". (página)
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/overview/working-with-objects/annotations.md
- **[K8]** Temporal, *Memo* e *Search Attributes*: o Memo é "a non-indexed set of Workflow Execution metadata", devolvido
  ao descrever ou listar; o atributo de busca é "an indexed field used in a List Filter", com chaves "relevant to your
  business needs". (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/workflow/workflow-execution/workflow-execution.mdx ;
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/visibility/search-attributes.mdx
- **[K9]** Buildkite, *Dynamic pipelines*: scripts "generate new pipeline steps at build time, in either YAML or JSON, and
  upload them to the same pipeline". (página)
  https://raw.githubusercontent.com/buildkite/docs/main/pages/pipelines/configure/dynamic_pipelines.md
- **[K10]** PostgreSQL, *Row Security Policies*: tabelas podem ter políticas que restringem, "on a per-user basis, which
  rows can be returned by normal queries or inserted, updated, or deleted". (página)
  https://raw.githubusercontent.com/postgres/postgres/master/doc/src/sgml/ddl.sgml
- **[K11]** Camunda, *BPMN tasks*: tarefas são "atomic units of work"; quando o fluxo chega a uma, o motor "creates a job
  and notifies a registered worker to perform work"; os tipos incluem tarefa de serviço, de script, de usuário ("work that
  needs to be done by a human actor") e manual. (página)
  https://raw.githubusercontent.com/camunda/camunda-docs/main/docs/components/modeler/bpmn/tasks.md ;
  https://raw.githubusercontent.com/camunda/camunda-docs/main/docs/components/modeler/bpmn/user-tasks/user-tasks.md
- **[K12]** Temporal, *Task Queues*: "A Task Queue is a lightweight, dynamically allocated queue that one or more Worker
  Entities poll for Tasks". (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/workers/task-queues.mdx
- **[K13]** Apache Airflow, *Executor*: "Executors are the mechanism by which task instances get run. They have a common
  API and are 'pluggable', meaning you can swap executors based on your installation needs." (página)
  https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/core-concepts/executor/index.rst
- **[K14]** Linux, *Control Group v2*: "cgroup is a mechanism to organize processes hierarchically and distribute system
  resources along the hierarchy in a controlled and configurable manner"; o `memory.max` é "the main mechanism to limit
  memory usage of a cgroup", e o valor é de quem configura. (página)
  https://raw.githubusercontent.com/torvalds/linux/master/Documentation/admin-guide/cgroup-v2.rst
- **[K15]** Temporal, *Retry Policies*: a política padrão "uses exponential backoff with a 2.0 backoff coefficient,
  starting with a 1-second initial interval and capping at a maximum interval of 100 seconds", com o número de tentativas
  e os erros que não se repetem como parâmetros. (página)
  https://raw.githubusercontent.com/temporalio/documentation/main/docs/encyclopedia/retry-policies.mdx
- **[K16]** Kubernetes, *Pod Priority and Preemption*: "A PriorityClass is a non-namespaced object that defines a mapping
  from a priority class name to the integer value of the priority"; quanto maior o valor, maior a prioridade. (página)
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/scheduling-eviction/pod-priority-preemption.md

## T. Documentos do repositório

- **[T1]** [docs/SEMENTE.md](../SEMENTE.md): intenção, metas (PRs por segundo), medidas e guardas, os três limites.
- **[T2]** [docs/padrao/METODO.md](../padrao/METODO.md): programa, projeto, processo e operação.
- **[T3]** [docs/research/toc.md](../research/toc.md): teoria das restrições, Little, Kingman, filas de merge.
- **[T4]** [docs/architecture/PORTS.md](../architecture/PORTS.md): as portas e os adaptadores do motor.
- **[T5]** [docs/programs/vazao/sistema.md](../programs/vazao/sistema.md): o sistema de hoje e as restrições medidas.
- **[T6]** docs/operations/incidents/I-5102f4e9.md: o control plane fora do ar.
- **[T7]** [docs/research/box.md](../research/box.md): a caixa de verificação, o Origin como registro externo, a
  verificação cruzada entre lanes, a computação gratuita e o lote ótimo numa caixa (pesquisa de 03/11/2026).
- **[T8]** docs/operations/train.md: o trem, a admissão por veredito e o lote na caixa (D-297).
- **[T9]** docs/operations/incidents/: os 27 incidentes até 03/11/2026, por tipo.
- **[T10]** [docs/programs/vazao/design-trem.md](../programs/vazao/design-trem.md): o desenho do trem em lote na caixa.
- **[T11]** [docs/units/FORGE-PORT/research.md](../units/FORGE-PORT/research.md): portas de forge, contrato por adaptador e
  merge por push do commit testado (o GitHub marca a PR mergeada quando o head dela está na base).
