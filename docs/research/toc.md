# Teoria das Restrições e fluxo aplicados a um motor de entrega com agentes de IA em paralelo

Pesquisa independente para o motor d'A Torre. Data: 2026-11-03.

**Como ler as marcas.**
- **[E]** é evidência estabelecida: fonte primária, livro canônico ou resultado matemático.
- **[S]** é fonte secundária ou relato de praticante, ainda não verificado no texto primário.
- **[I]** é inferência minha, um cálculo ou uma regra proposta.

Os números do motor vêm do briefing de 2026-11-03. **Nota do coordenador:** a taxa de vermelho p ≈ 0,33 e n_r ≈ 3
vêm das 3 primeiras PRs daquele dia, não de uma medida; a fila F24 mede o valor real sobre os merges, e as contas
da seção 6 se refazem com ele.

---

## 1. Resumo

1. A TOC diz que a vazão de um sistema é limitada por uma única restrição. Melhorar qualquer outro ponto não aumenta a vazão. Os cinco passos são identificar, explorar, subordinar, elevar e repetir [E].
2. Hoje o motor não está limitado pelo gate. A ocupação de CPU do gate é ρ ≈ 0,3. Os limites que sobram são três [I]:
   - o suprimento de unidades prontas e independentes, que secou;
   - a cota de tokens, que impõe o teto político de 2 lanes;
   - o retrabalho por gate vermelho (2 de 3 PRs), que queima cota e CPU.
3. Na meta de 1.000 PRs/dia (41,7/h) a restrição passa a ser a CPU do gate [I]. Uma caixa de 4 CPUs faz cerca de 31 rodadas completas por hora. O motor precisaria de ≥ 54 rodadas/h.
4. Rodar o gate em paralelo na mesma caixa não ganha nada. Três execuções simultâneas levam 346 s cada, contra 113 s de uma sozinha, e testes falham sob carga. O gate é um recurso serial por caixa: ele é o "tambor" [I].
5. Lotear no gate (batching) só compensa quando a taxa de vermelho p é baixa. O custo é ≈ 1/b + p·b rodadas por PR, com tamanho ótimo b* ≈ 1/√p. Com p = 0,33, como hoje, não há ganho. Com p = 0,05 o ganho é 2,2× [I, a partir de E].
6. A Lei de Little e o "WIP crítico" de Hopp & Spearman dão o WIP útil: cerca de 6 PRs em voo. Acima disso, mais lanes só criam fila [I].
7. Kingman mostra que a espera explode quando a utilização passa de 70–80%. A regra é manter o gate abaixo de 0,7 [E/I].
8. As evidências da era da IA são consistentes [E/S]:
   - mais PRs aumentam a carga a jusante: revisão +91% e estabilidade −7,2% segundo o DORA 2024;
   - agentes concorrentes geram conflitos de merge em 20% a 42% dos pares coativos;
   - paralelismo exige trabalho independente.
9. Onde a TOC quebra [I]:
   - o "trabalhador" é barato e elástico, e o recurso escasso passa a ser a cota de tokens, que reabastece em janelas;
   - o WIP custa tokens e probabilidade de conflito, não capital;
   - a decomposição em unidades independentes vira a liberação de matéria-prima.
10. O guia da seção 6 propõe métricas, limites de WIP como funções, buffers com zonas e o gatilho para ligar o trem com lotes.

---

## 2. Teoria das Restrições (TOC)

### 2.1 O que é
Goldratt apresentou a TOC no romance *The Goal* (1984). A tese é que todo sistema orientado a uma meta tem pelo menos uma restrição que limita seu desempenho. Ela pode ser física (uma máquina), de mercado ou de política (uma regra) [E: Goldratt 1984; Wikipedia TOC]. Uma hora perdida na restrição é uma hora perdida no sistema inteiro. Uma hora ganha fora dela é uma miragem. Ótimos locais, como a eficiência de cada estação, pioram o todo porque inflam o estoque.

### 2.2 Os cinco passos de focalização [E]
1. **Identificar** a restrição.
2. **Explorar** a restrição: tirar dela o máximo sem gastar. Ela nunca para e nunca processa sucata.
3. **Subordinar** todo o resto à decisão anterior. Os não-gargalos andam no ritmo da restrição, mesmo que fiquem ociosos.
4. **Elevar** a restrição, isto é, comprar ou adicionar capacidade.
5. **Repetir** sem deixar a inércia virar a nova restrição. Quando a restrição se move, volta-se ao passo 1.

A ordem importa. Elevar antes de explorar e subordinar é desperdício caro.

### 2.3 Drum-Buffer-Rope (DBR) e gestão de buffers [E]
- **Tambor (drum):** a restrição dita o ritmo de todo o sistema.
- **Buffer:** proteção medida em *tempo*, colocada antes da restrição para que ela nunca fique faminta.
- **Corda (rope):** a liberação de material na entrada fica amarrada ao consumo do tambor. Assim o WIP não cresce além do buffer.

A gestão de buffers divide o buffer em três terços. Verde é penetração abaixo de 1/3: não fazer nada. Amarelo é entre 1/3 e 2/3: preparar ação. Vermelho é acima de 2/3: expedir. A frequência de entradas no vermelho indica onde melhorar o processo [E: Schragenheim & Dettmer; PMI 2001; CCPM usa o mesmo "fever chart"].

### 2.4 Corrente Crítica (CCPM) [E]
*Critical Chain* (Goldratt, 1997) leva a TOC a projetos.
- Os prazos de tarefa embutem segurança, que se perde em dois comportamentos. A síndrome do estudante é começar tarde. A Lei de Parkinson é o trabalho que se expande até preencher o prazo.
- A CCPM corta as estimativas para cerca de 50% e agrega a segurança num **buffer de projeto** no fim da cadeia crítica. A cadeia crítica é o caminho mais longo considerando dependências *e* recursos.
- Põe **buffers de alimentação** onde ramos não críticos entram na cadeia.
- Acompanha o projeto pelo consumo de buffer contra o progresso da cadeia, com zonas verde, amarelo e vermelho.

Relevância: uma cadeia de dependências entre unidades é exatamente o caso em que a CCPM se aplica, e o último lote do motor foi uma cadeia.

### 2.5 Contabilidade de ganhos (Throughput Accounting) [E]
- **T (ganho, throughput):** vendas menos custos totalmente variáveis.
- **I (investimento/inventário):** dinheiro preso no sistema.
- **OE (despesa operacional):** todo o resto do gasto para operar.
- Lucro líquido = T − OE. ROI = (T − OE)/I.

A prioridade da TOC é aumentar T, depois reduzir I, depois reduzir OE. Para escolher o mix, o critério é o **ganho por unidade de tempo da restrição**, não a margem por produto. Anderson (2003) traduziu isso para software:
- T é a funcionalidade entregue;
- I são as ideias e requisitos ainda não entregues;
- OE é o custo do time.

### 2.6 Processos de pensamento [E]
Respondem a três perguntas: o que mudar, para o que mudar e como causar a mudança.

| Ferramenta | Pergunta | Uso |
|---|---|---|
| Árvore da Realidade Atual (CRT) | o que mudar | Liga os efeitos indesejáveis (UDEs) a poucas causas-raiz, muitas vezes um conflito central. |
| Nuvem de Evaporação (EC) | para o que mudar | Diagrama de conflito: objetivo, duas necessidades, duas ações opostas. Expõe a premissa falsa que "evapora" o conflito. |
| Árvore da Realidade Futura (FRT) | para o que mudar | Testa se as injeções eliminam os UDEs sem efeitos colaterais. |
| Árvore de Pré-requisitos (PRT) | como causar a mudança | Ordena obstáculos e objetivos intermediários. |
| Árvore de Transição (TT) | como causar a mudança | Sequencia as ações. |

Relevância: a CRT é estruturalmente a mesma "cadeia de porquês" que o D-081 exige. A EC serve aos conflitos do tipo "contract" do gate.

---

## 3. Filas e fluxo

### 3.1 Lei de Little [E]
**L = λ·W.** WIP médio = taxa de chegada × tempo médio no sistema.

Vale para qualquer sistema estável, sem hipótese de distribuição (Little 1961; Little 2011). Consequência prática: para uma vazão fixa, o lead time só cai se o WIP cair. Aumentar o WIP sem aumentar a vazão da restrição só aumenta W.

**Limites de vazão** (Hopp & Spearman, *Factory Physics*) [E]:
- **WIP crítico:** W₀ = r_b·T₀, em que r_b é a taxa do gargalo e T₀ é o tempo bruto de processo.
- **Melhor caso:** TH(w) = min(w/T₀, r_b).
- Acima de W₀, mais WIP não aumenta a vazão, só a espera.

### 3.2 Fórmula de Kingman (VUT) [E]
Para uma fila G/G/1:

**E[Wq] ≈ ((c_a² + c_s²)/2) · (ρ/(1−ρ)) · τ**

- c_a e c_s são os coeficientes de variação das chegadas e do serviço.
- ρ é a utilização.
- τ é o tempo médio de serviço.

O termo ρ/(1−ρ) é a não linearidade. Ele vale 1 em ρ = 0,5, 2,3 em 0,7, 4 em 0,8 e 9 em 0,9. A variabilidade multiplica esse efeito. A aproximação é exata para M/M/1 e melhora em tráfego pesado (Kingman 1961; Hopp & Spearman). Para c servidores existe a extensão de Allen-Cunneen.

### 3.3 Tamanho de lote [E]
- Lotes menores reduzem tempo de ciclo, variabilidade do fluxo e risco, e aceleram o feedback.
- O lote ótimo minimiza um custo total em U: custo de transação dividido pelo lote, mais custo de manter/atrasar, que cresce com o lote.
- Reduzir o custo de transação, como CI barato e merge automático, desloca o ótimo para lotes menores (Reinertsen 2009, princípios de lote).
- Lotes grandes alimentam a "espiral da morte": quanto maior o lote, mais demora, e mais escopo se agrega a ele.

### 3.4 Limites de WIP [E]
Pela Lei de Little, limitar o WIP limita o lead time. O kanban e o CONWIP são cordas genéricas: puxar só quando algo sai. Reinertsen recomenda limites de WIP e "purgar" a fila quando ela passa do limite, em vez de deixar o lead time crescer.

### 3.5 Reinertsen, *The Principles of Product Development Flow* (2009) [E]
O livro reúne 175 princípios em 9 seções. Os pontos centrais:
1. **Quantifique o custo de atraso (CoD).** Priorize por CoD dividido pela duração (CD3, a base do WSJF), não por FIFO.
2. **Filas são o custo oculto.** São invisíveis no inventário de P&D, e o tamanho da fila é indicador *antecedente* (o lead time é *consequente*).
3. **Utilização alta é cara** (ver Kingman). Em P&D, que tem alta variabilidade, opere abaixo de 100% de propósito.
4. **Lotes pequenos.**
5. **Limites de WIP.**
6. **Cadência e sincronização.** A cadência, um evento em intervalo fixo, limita o acúmulo de variância e torna a espera previsível. A sincronização junta itens para processá-los juntos, que é o que um trem com lotes faz.
7. **Feedback rápido.**
8. **Controle descentralizado** com regras econômicas claras.

---

## 4. Evidência de entrega de software

### 4.1 DORA / Accelerate [E]
*Accelerate* (Forsgren, Humble & Kim, 2018) e os relatórios anuais DORA definem quatro métricas:
- frequência de deploy;
- lead time de mudança;
- taxa de falha de mudança;
- tempo de recuperação.

Os achados centrais:
- Vazão e estabilidade **andam juntas**: os melhores times são mais rápidos *e* mais estáveis.
- O que move as métricas são capacidades técnicas: CI, testes automatizados, trunk-based development, arquitetura de baixo acoplamento, lotes pequenos e o fluxo de trabalho visível com limites de WIP.
- Os critérios de trunk-based development no DORA são ≤ 3 branches ativas, merge no tronco ao menos 1×/dia e nenhum congelamento de código ou fase de integração.

Desde 2024, vazão e estabilidade são analisadas separadamente, e o tempo de recuperação passou para o grupo de vazão.

**DORA 2024** [E, anúncio Google Cloud]: cada +25% de adoção de IA correlacionou com −1,5% de vazão de entrega e −7,2% de estabilidade. A hipótese dos autores e de comentaristas é que lotes maiores (change lists maiores) causam o efeito, o que bate com a teoria de lotes.

**DORA 2025** [E/S]: a relação entre IA e vazão ficou positiva, mas a instabilidade persiste. A IA é "amplificadora": magnifica as forças e as disfunções do sistema. O relatório nomeia 7 capacidades que condicionam o ganho, entre elas controle de versão maduro, trabalho em lotes pequenos e plataforma interna.

### 4.2 Merge queues: mecanismo e números

| Sistema | Mecanismo | Número/regra publicada |
|---|---|---|
| bors / "Not Rocket Science Rule" (Hoare; Rust) | Manter automaticamente um repositório cujo tronco sempre passa nos testes: testar a mudança mergeada sobre o tronco *antes* de avançá-lo, serialmente. | Vazão máxima = 1 merge por duração de CI. É o limite que motiva lotes e especulação. [E/S] |
| Zuul (OpenStack) | Pipeline *dependente* com **execução especulativa**: cada mudança é testada sobre as mudanças à sua frente, supondo que elas passarão. Se uma falha, as de trás são abortadas e retestadas sem ela. | Testa em paralelo e mesmo assim garante que cada commit é testado exatamente como será mergeado. [E: docs opendev] |
| Prow/Tide (Kubernetes) | **Lote**: testa N PRs aprovados juntos. Se o lote passa, mergeia todos. Se falha, cai para PR individual. Um merge no pool devolve os demais para reteste. | Pools disjuntos por org/repo:branch. [E: docs Tide] |
| GitHub merge queue | Branches temporárias; *build concurrency* (1–100) limita CI simultâneo; *maximum group size* e *merge limits*. | Ajustes de 1 a 100. [E: docs GitHub] |
| Mergify / Trunk | Lotes com bisseção na falha. | Regra prática: lote de 5–10 se falha < 2%, 3–5 se 2–5%, 2–3 se > 5%. Taxa de sucesso de lote > 80% indica que o lote compensa. Trunk usa padrão de 4 PRs e espera máxima de 5 min. [S: docs de fornecedores] |
| Uber SubmitQueue (EuroSys 2019) | Árvore de especulação com probabilidade de sucesso de cada build; analisador de conflitos permite builds independentes em paralelo. | Mantém o tronco verde com milhares de commits/dia em monorepos gigantes. [E] |
| Uber, "CI at Scale: Lean, Green, and Fast" (ICSE-SEIP 2025) | Modelo probabilístico, prioriza mudanças curtas, limiar de especulação, previsão de tempo de build por ML. | −53% recursos de CI, −44% CPU, −37% espera P95. [E] |
| Google TAP (Memon et al., ICSE-SEIP 2017) | Mesmo com recursos enormes, não é viável testar cada mudança individualmente. Usa "milestones": snapshots que integram vários commits, mais seleção de testes por grafo de dependências. | Poucos testes falham alguma vez. Os que falham estão "perto" do código. Arquivos alterados por > 3 devs quebram mais. [E] |

**Matemática de lotes** [I, derivada de E]. Seja p a probabilidade de um PR, sozinho, deixar o gate vermelho, de forma independente. Usa-se um lote de b com fallback individual na falha, como no Tide. Então:
- P(lote verde) = (1−p)^b;
- rodadas por PR ≈ 1/b + (1 − (1−p)^b), que é ≈ 1/b + p·b para p pequeno;
- o mínimo fica em **b\* ≈ 1/√p**, com custo ≈ 2√p rodadas por PR.

| p | b* | Rodadas/PR | Ganho de capacidade vs. b = 1 |
|---|---|---|---|
| 0,01 | 10 | ≈ 0,2 | 5× |
| 0,05 | ≈ 4–5 | ≈ 0,45 | 2,2× |
| 0,10 | 3 | ≈ 0,6 | 1,6× |
| 0,33 | ≈ 1–2 | ≈ 1,05–1,15 | nenhum |

Esses números batem com a regra prática da Mergify.

O custo em latência: esperar o lote encher acrescenta cerca de (b−1)/(2λ), por isso existe o timeout. A especulação no estilo Zuul multiplica a vazão por k pipelines **só se a CI for elástica**. Em CPU fixa ela reparte a mesma CPU.

---

## 5. Era da IA: agentes em paralelo

### 5.1 Medições publicadas
- **Anthropic, C compiler (Carlini, fev. 2026)** [E]:
  - 16 agentes Opus 4.6 em contêineres, sem orquestrador, sobre um repositório git bare compartilhado;
  - "lock" de tarefa por arquivo em `current_tasks/`;
  - cerca de 2.000 sessões em 2 semanas, ~2 bilhões de tokens de entrada e 140 milhões de saída, pouco menos de US$ 20 mil;
  - resultado: compilador C em Rust de 100 mil linhas que compila o Linux 6.9;
  - os conflitos de merge foram frequentes, e o Claude os resolveu;
  - o paralelismo funcionou para testes falhos independentes e colapsou numa tarefa monolítica ("todo agente achava o mesmo bug, corrigia e sobrescrevia o outro"). A solução foi um oráculo (GCC) para dividir o trabalho;
  - perto do fim, os agentes quebravam funcionalidades existentes, e foi preciso CI bloqueando regressões;
  - lição explícita: o verificador é o volante, e o harness precisa ser desenhado para o modelo (pouca saída, logs em arquivo, amostra `--fast` de 1–10% determinística por agente).
- **Anthropic, sistema multiagente de pesquisa (jun. 2025)** [E]:
  - agentes usam ~4× os tokens de um chat, e sistemas multiagente ~15×;
  - o ganho de desempenho vem principalmente de gastar mais tokens;
  - só compensa quando o valor da tarefa paga o custo.
- **AIDev (Li, Zhang & Hassan, 2025)** [E/S]:
  - cerca de 456 mil PRs de 5 agentes (Codex, Devin, Copilot, Cursor, Claude Code) em 61 mil repositórios;
  - PRs de agente são aceitos significativamente menos que PRs humanos;
  - taxas por agente variam muito entre resumos, então use só a direção do resultado.
- **Xu, Subramanian & Karthik (arXiv 2607.04697, jul. 2026)** [E/S]:
  - 33.596 PRs de agentes em 2.807 repositórios;
  - 40,2% dos repositórios têm pares de PRs de agentes coativos, e esses pares somam 79,4% dos PRs de agentes;
  - o replay de merges de três vias deu conflito textual em **19,8%** dos pares do mesmo agente e **41,7%** dos pares de agentes diferentes;
  - a maioria dos arquivos em conflito é código-fonte.
- **Faros AI, AI Productivity Paradox (2025)** [S, telemetria de fornecedor]:
  - mais de 10 mil devs: times com alta adoção completam +21% tarefas e mergeiam **+98% PRs**;
  - em contrapartida, o tempo de revisão subiu **+91%**, os PRs ficaram ~154% maiores e os bugs por dev subiram ~9%;
  - nenhuma melhora mensurável nas métricas DORA da empresa. É o caso clássico da TOC: aumentar um não-gargalo transfere a fila.
- **METR (RCT, fev.–jun. 2025)** [E]:
  - 16 devs experientes e 246 tarefas reais: com IA levaram **19% mais tempo**, embora acreditassem estar 20% mais rápidos;
  - o tempo migrou para promptar, revisar e esperar;
  - os próprios autores alertam contra generalizar o resultado.

### 5.2 O que limita, na prática [E/S, síntese]
1. **Trabalho independente.** O paralelismo só rende quando as tarefas não se sobrepõem (Carlini; conflitos de 20–42%).
2. **Pontos de convergência.** Arquivos compartilhados, registros e índices geram conflitos (relatos de praticantes com worktrees).
3. **Verificação e CI.** É o volante de qualidade e o recurso compartilhado de CPU (TAP, SubmitQueue, Carlini).
4. **Revisão e integração humanas** (Faros, DORA). O motor eliminou a revisão (D-055), e a fila foi para o gate.
5. **Tokens e limites de taxa.** O custo cresce com o paralelismo (4×/15×), e assinaturas têm janela de 5 h e teto semanal [S: guias de terceiros; ver `/usage`].
6. **Tamanho de lote.** Agentes inflam o tamanho das mudanças, e isso reduz estabilidade (DORA 2024).

---

## 6. Guia de aplicação ao motor

Os números abaixo são os medidos em 2026-11-03. As fórmulas valem para qualquer medição futura; troque os números a cada ciclo. Tudo nesta seção é **[I]**, salvo quando citado.

### 6.0 Modelo e símbolos

| Símbolo | Significado | Hoje |
|---|---|---|
| X | vazão de merges | 6,8/h = 0,0019/s |
| L | lanes concorrentes | 1–2 (teto 2) |
| a | tempo de autoria por PR | 10–15 min; média 12,5 |
| r_lane | taxa máxima de uma lane alimentada | 60/12,5 ≈ 4,8 PR/h |
| s | tempo de uma rodada do gate, sozinha na caixa | 85–145 s; uso τ = 113 s |
| C_gate | capacidade do gate por caixa | 3600/113 ≈ 32 rodadas/h; em paralelo cai para 3600/346 × 3 = 31/h, sem ganho |
| p | taxa de gate vermelho por entrega | ≈ 0,67 hoje cedo; uso 0,33 como cenário "bom dia" |
| n_r | rodadas de gate por PR mergeado | 1/(1−p) mais rejulgamentos; com p = 0,67, n_r ≈ 3 |
| c_tok | tokens por entrega | 50k de entrada não cacheada + 14k de saída ≈ 64k; por merge: c_tok·1/(1−p) |
| P_rej | probabilidade de a base mover durante o gate | 1 − e^(−X·s) |

### 6.1 IDENTIFICAR: achar a restrição a cada ciclo
**Regra:** a restrição é o recurso com a maior *utilização de demanda*, calculada pela fórmula abaixo para cada recurso. Recalcule a cada janela de 5 h e a cada 50 merges. Confirme pelo sintoma: a fila está *antes* da restrição, e o que vem depois dela fica ocioso.

**U_k = demanda por hora / capacidade por hora**

| Recurso | Fórmula | Hoje (X = 6,8; p = 0,67) | Em 1.000/dia (X = 41,7; p = 0,05) |
|---|---|---|---|
| Lanes, ou autoria | X·a / L | 6,8·(12,5/60)/2 = **0,71** | precisa de L ≥ 41,7/4,8 ≈ 9 lanes cheias |
| CPU do gate | X·n_r·s / 3600 | 6,8·3·113/3600 = **0,64**, com o retrabalho dominando | 41,7·1,05·113/3600 = **1,37**: inviável |
| Cota | X·c_tok·n_r / B_5h | medir pela `/usage`, em % da janela por merge | idem |
| Suprimento | itens prontos e independentes / consumo L·r_lane | **0**: secou, é a restrição ativa | — |

Leitura de hoje:
- A restrição *ativa* é o **suprimento de unidades independentes**: as lanes ficaram sem trabalho.
- Logo atrás vem a **cota**, porque o teto de 2 lanes é uma restrição de *política* que deriva dela.
- O **gate vermelho** é o que mais desperdiça: triplica o uso de CPU e de cota por merge.
- O gate *ainda* não é a restrição física. Ele vira a restrição antes de 1.000/dia.

**Métricas obrigatórias por ciclo** (todas derivadas do log de eventos, não de um relógio):
- X, ou merges por hora;
- lead time por PR, separado em autoria, espera do gate, gate e rejulgamento;
- fila na frente de cada recurso;
- p, a taxa de vermelho, separada em código, ambiente e flaky sob carga;
- n_r;
- tokens por merge;
- % da janela de 5 h e da semanal consumida por merge;
- tamanho do buffer de unidades prontas;
- taxa de conflito de merge por par de PRs coativos (q);
- taxa de retrabalho, ou PRs reescritos depois.

### 6.2 EXPLORAR: nada se desperdiça na restrição
1. **Gate verde na primeira vez.** O vermelho custa ao mesmo tempo a cota (re-entrega), a CPU (nova rodada) e o lead time. Por isso é a primeira alavanca. Meta: p ≤ 0,10, depois ≤ 0,05.
   - Rode no pre-push a *mesma seleção por covers* do gate: é CPU barata, não cota.
   - Classifique cada vermelho (D-027). Um "flaky sob carga" é defeito de ambiente, não de código.
2. **Nada de gate concorrente na mesma caixa.** Medido: 3× em paralelo dá 0 de ganho e mais falhas. Concorrência do gate = 1 por caixa de 4 CPUs, ou = floor(CPUs/4).
3. **Seleção por covers mais rigorosa.** Reduzir s é o mesmo que elevar a capacidade de graça. TAP mostra que os testes que falham estão "perto" do código. Meta: s̄ ≤ 60 s para PRs pequenos.
4. **Tokens por merge.** O foco não é economizar por PR. É **zero tokens em retrabalho**: re-entrega, rejulgamento e leitura repetida de contexto. A meta é c_tok·n_r → c_tok.
5. **Lanes nunca ociosas por falta de trabalho**, o que é papel do buffer de suprimento (6.4).

### 6.3 SUBORDINAR: o resto anda no ritmo do tambor
- **O tambor atual é a cota.** A corda é a seguinte: uma lane só *inicia* uma unidade se o orçamento restante da janela ≥ 1,5 × o custo esperado por merge (c_tok·n_r). Isso evita trabalho abandonado no meio da janela, que vira inventário morto.
- **Quando o tambor for o gate**, a corda é outra: nenhuma lane abre um PR novo se a fila do gate for ≥ K_gate (ver 6.4). Ela continua autorando localmente até o limite de 1 PR pronto por lane.
- **O planejamento (INTAKE→PLAN) se subordina ao consumo.** A produção de unidades novas é disparada pela zona amarela do buffer de suprimento, não por calendário (D-065: eventos, não relógio).
- **A cadeia de dependências usa CCPM.** Para um lote dependente, planeje a cadeia crítica com estimativas de 50% (tokens e tempo) e um buffer de projeto = 50% da soma da cadeia. Unidades paralelas que entram na cadeia ganham buffer de alimentação. Acompanhe com fever chart: consumo de buffer contra % da cadeia concluída.

### 6.4 Buffers e limites de WIP (fórmulas)

**Buffer de suprimento** (unidades prontas, independentes e com dono disjunto):

B_sup = L × r_lane × T_rep × 1,5

T_rep é o tempo para produzir um lote novo de unidades (uma sessão de PLAN). Com L = 2, r_lane = 4,8/h e T_rep = 1 h: **B_sup ≈ 14 unidades**. Em 9 lanes: ≈ 65.

As zonas seguem 2.3:
- **verde:** > 2/3 de B_sup;
- **amarelo:** entre 1/3 e 2/3, dispara uma sessão de planejamento;
- **vermelho:** < 1/3, prioridade máxima de decomposição e um incidente se zerar.

Independência obrigatória dentro do buffer: conjuntos de arquivos e unidades disjuntos, pela posse por lane (D-065). A justificativa é que pares coativos sem coordenação conflitam em 20–42% (seção 5.1).

**Buffer do gate**, quando ele for o tambor:

K_gate = ceil(C_gate × t_proteção)

t_proteção cobre a variação da chegada. Uma escolha razoável é 2 × s̄ × (1 + c_a). Com 113 s e c_a ≈ 1, dá ~7,5 min de trabalho, ou **K_gate ≈ 4 PRs**.

**Limite de lanes** (o WIP de trabalhadores): L_max = min(L_cota, L_cpu, L_sup, L_conf).

1. **L_cota** = (B_5h / (c_tok·n_r)) / (5 h × r_lane). Exemplo: se um merge consome 2% da janela de 5 h, cabem 50 merges por janela, e 50/(5 × 4,8) ≈ **2,1 lanes**. Isso é coerente com o teto atual. Com n_r reduzido de 3 para 1,1, a mesma cota sustenta ~5,7 lanes. **Corrigir o vermelho é a elevação mais barata da cota.**
2. **L_cpu** = 0,7 × 3600 × caixas / (r_lane × (n_r·s + s_prepush)). Use s_prepush ≈ 4 commits × 10 s = 40 s, se rodar na mesma caixa.
   - Hoje (n_r = 3): 2520 / (4,8 × 379) ≈ **1,4 lanes**. A CPU *já* limita o motor a menos de 2 lanes enquanto o vermelho estiver em 2/3.
   - Com n_r = 1,1: 2520 / (4,8 × 164) ≈ **3,2 lanes**.
   - O fator 0,7 vem de Kingman: com c_a² ≈ 1 e c_s² ≈ 0,04, em ρ = 0,7 a espera é ≈ 0,52 × 2,33 × 113 ≈ 137 s, cerca de 1 rodada. Em ρ = 0,9, chega a ≈ 530 s.
3. **L_sup** = itens no buffer / (r_lane × T_rep). Não abrir lane sem unidade pronta.
4. **L_conf** é o maior L com P(≥1 conflito entre PRs coativos) = 1 − (1−q)^(L(L−1)/2) ≤ 0,25.
   - Com q = 0,05, que é a hipótese com posse disjunta e precisa ser medida: L ≤ 3.
   - Com q = 0,01: L ≤ 8.
   - O que eleva esse limite é a posse disjunta, não a disciplina.

**WIP de PRs em voo** pelo WIP crítico de Hopp & Spearman: W₀ = r_b × T₀.
- T₀ = a + s ≈ 12,5 + 1,9 ≈ 14,4 min = 0,24 h.
- Com o gate como gargalo (r_b = 31/n_r): para n_r = 1,1, W₀ ≈ 28 × 0,24 ≈ **6,8 PRs**. Para n_r = 3, W₀ ≈ 2,5.
- Acima de W₀, mais lanes só aumentam a espera (Little).

### 6.5 ELEVAR, em ordem de custo
1. **Baixar p** (6.2): ganho de até 3× em cota e em CPU por merge, sem gastar nada.
2. **Baixar s** pela seleção, por testes mais rápidos e por cache.
3. **Ligar o trem com lotes**, quando valer pela regra 6.6.
4. **Mais CPU**: mais caixas, ou um runner que se paga com seu orçamento (ADR-41/D-086).
5. **Mais cota**: outra conta, ou API por uso. É dinheiro, então é decisão do dono.

**A escada vista pela restrição:**
- **1.000/dia (41,7/h):** precisa de ~9 lanes cheias e de 41,7 × 64k ≈ 2,7 M tokens/h, ≈ 64 M/dia em tokens novos. Isso provavelmente excede uma única assinatura Max (verificar na `/usage`). No gate, precisa de 41,7·n_r·s ≤ 0,7 × 3600 × caixas: com s = 113 e n_r = 1,05, **2 caixas**, *ou* 1 caixa com lote b ≈ 4 e p ≤ 0,05.
- **10.000/dia (417/h):** o orçamento do gate é ≈ 8,6 s de caixa por PR. Exige ao mesmo tempo lote b ≥ 10 com p ≤ 0,01, seleção com s̄ ~ 30 s e várias caixas. Exige também ~90 lanes, ou lanes muito mais rápidas, e cota da ordem de 0,6 G tokens/dia.
- **100.000/dia:** ≈ 0,86 s de caixa por PR. Só com CI distribuída e especulativa no estilo SubmitQueue, árvore de especulação podada por análise de conflito, e com a geração de unidades como processo próprio.

### 6.6 Quando o trem com lotes compensa (com os números de hoje)
**Gatilho 1, rejulgamento.**
- P_rej = 1 − e^(−X·s).
- Hoje: X·s = (6,8/3600) × 113 = 0,21, P_rej ≈ **19%**.
- Em 41,7/h: X·s = 1,31, P_rej ≈ **73%**. A base move na maioria dos gates, e os 3 rounds estouram.
- **Regra:** ligar o trem (teste sobre a base prevista da fila, sem rejulgar) quando P_rej > 0,25, isto é, X > 0,29/s̄. Com s̄ = 113 s, isso é X > ~9 PRs/h.

**Gatilho 2, lote.**
- Ligar lotes quando (a) o gate é a restrição (U_gate > 0,7) **e** (b) p ≤ 0,10 nas últimas 50 entregas.
- O tamanho do lote é b = clamp(round(1/√p), 2, 8).
- O timeout de enchimento é min(5 min, (b−1)/X).
- Desligar quando a taxa de lote verde ficar < 80% ou p > 0,15.
- Com p = 0,33, como hoje, o lote **não compensa**: ≈ 1,05–1,15 rodada por PR contra 1 rodada.

**Gatilho 3, especulação em paralelo** (Zuul/SubmitQueue): só com CPU elástica (k caixas). Na mesma caixa não há ganho, como já foi medido.

### 6.7 Onde a TOC quebra e o que a substitui
1. **O trabalhador não é a capacidade fixa.** Uma lane nasce em segundos, então a capacidade de mão de obra deixa de ser o recurso escasso. O escasso é um **estoque renovável de cota**, que reabastece a cada 5 h e por semana. A restrição oscila *dentro* da janela: no início não prende, no fim prende. O tambor vira uma *taxa de gasto* (B/5 h), e o buffer é o saldo da janela.
2. **WIP não custa capital, custa tokens e colisão.** O custo marginal de WIP é composto por:
   - recarga de contexto;
   - rejulgamentos, que crescem com X·s;
   - conflitos, que crescem com O(L²) pares.

   O limite de WIP sai de L_conf e de W₀, não de dinheiro preso.
3. **A variação é de qualidade, não só de tempo.** O vermelho é "sucata na restrição". Goldratt manda inspecionar *antes* da restrição, e aqui isso significa pre-push seletivo e gate barato antes do caro.
4. **O suprimento de trabalho independente é a nova matéria-prima.** Decompor em unidades disjuntas, a função de PLAN, é a liberação de material. Quando ela seca, nenhuma elevação de CPU ou de cota ajuda. É uma restrição de política ou de projeto, e se trata com a CRT e a EC, não com capacidade.
5. **A métrica-meta pode ser inflada** quebrando um PR em vários. A contabilidade de ganhos pede T *líquido*: merges sem retrabalho, com gate verde no head exato, e T por unidade da restrição (merges por milhão de tokens, ou por hora de CPU).
6. **Agentes não sofrem de síndrome do estudante**, mas a CCPM continua útil por outra razão: a variância de tokens e de tempo por unidade é alta. Agregar a margem num buffer de projeto, em vez de colocá-la em cada unidade, segue válido.

---

## 7. Fontes

**TOC**
1. Goldratt, E. M.; Cox, J. *The Goal*. North River Press, 1984. Resumo: https://en.wikipedia.org/wiki/Theory_of_constraints
2. Goldratt, E. M. *Critical Chain*. North River Press, 1997. Resumo: https://en.wikipedia.org/wiki/Critical_chain_project_management
3. PMI. "A comparison of drum-buffer-rope (DBR) and critical chain (CC) buffering techniques". https://www.pmi.org/learning/library/drum-buffer-rope-critical-chain-buffering-8526
4. Throughput accounting (T, I, OE, ROI): https://en.wikipedia.org/wiki/Throughput_accounting. Dugdale, D.; Jones, T. C. "Throughput Accounting", *British Accounting Review* (PDF): https://www.unife.it/economia/lm.economia/insegnamenti/management-strategico-dei-costi-dimpresa/casi-studio/ThroughputAccounting.pdf
5. TOC Institute. "TOC Thinking Processes". https://www.tocinstitute.org/toc-thinking-processes.html
6. Anderson, D. J. *Agile Management for Software Engineering: Applying the Theory of Constraints for Business Results*. Prentice Hall, 2003. https://www.informit.com/store/agile-management-for-software-engineering-applying-9780131424609

**Filas e fluxo**
7. Little, J. D. C. "A Proof for the Queuing Formula: L = λW". *Operations Research* 9(3), 1961. https://ideas.repec.org/a/inm/oropre/v9y1961i3p383-387.html
8. Little, J. D. C. "Little's Law as Viewed on Its 50th Anniversary". *Operations Research* 59(3), 2011. https://pubsonline.informs.org/doi/10.1287/opre.1110.0940
9. Kingman, J. F. C. "The single server queue in heavy traffic", 1961. Resumo e fórmula: https://en.wikipedia.org/wiki/Kingman%27s_formula
10. Hopp, W.; Spearman, M. *Factory Physics*, 3ª ed., 2011 (VUT, WIP crítico). Glossário: https://projectproduction.org/glossary/kingmans-equation-vut-equation/
11. Reinertsen, D. G. *The Principles of Product Development Flow*. Celeritas, 2009. Resenhas: https://ardalis.com/principles-of-product-development-flow-book-review/ e https://www.startuplessonslearned.com/2009/07/principles-of-product-development-flow.html

**Entrega de software e merge queues**
12. Forsgren, N.; Humble, J.; Kim, G. *Accelerate*. IT Revolution, 2018. Capacidade de trunk-based development: https://dora.dev/capabilities/trunk-based-development/
13. Google Cloud. "Announcing the 2024 DORA report", 2024. https://cloud.google.com/blog/products/devops-sre/announcing-the-2024-dora-report. InfoQ: https://www.infoq.com/news/2024/11/2024-dora-report/
14. DORA. "2025 State of AI-assisted Software Development". https://research.google/pubs/dora-2025-state-of-ai-assisted-software-development-report/ e https://www.dora.dev/research/ai
15. Zuul / OpenDev, documentação do gate pipeline: https://git.openstack.org/opendev/system-config/src/commit/e59b6cd4a89738997655686ea2583b1887343699/doc/source/zuul.rst
16. Prow/Tide. "Maintainer's Guide to Tide". https://docs.prow.k8s.io/docs/components/core/tide/maintainers/
17. GitHub Docs. "Managing a merge queue". https://docs.github.com/en/enterprise-server@3.17/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
18. Mergify. "Merge queue batching". https://mergify.com/learn/merge-queue/batching. Trunk. "Batching". https://docs.trunk.io/merge-queue/batching
19. Ananthanarayanan, S. et al. "Keeping Master Green at Scale" (SubmitQueue). EuroSys 2019. Uber Engineering.
20. Juloori, D. et al. "CI at Scale: Lean, Green, and Fast". ICSE-SEIP 2025. https://arxiv.org/abs/2501.03440. Uber Blog, "Slashing CI Costs at Uber", 2025: https://www.uber.com/blog/slashing-ci-costs-at-uber/
21. Memon, A. et al. "Taming Google-Scale Continuous Testing". ICSE-SEIP 2017. https://research.google/pubs/taming-google-scale-continuous-testing/
22. Hoare, G. "The Not Rocket Science Rule of Software Engineering" (origem do bors). Não localizei a URL primária nesta pesquisa; a regra é amplamente citada na comunidade Rust.

**Era da IA**
23. Carlini, N. "Building a C compiler with a team of parallel Claudes". Anthropic Engineering, fev. 2026. https://www.anthropic.com/engineering/building-c-compiler
24. Anthropic. "How we built our multi-agent research system", jun. 2025. https://www.anthropic.com/engineering/multi-agent-research-system
25. Li, H.; Zhang, H.; Hassan, A. E. "The Rise of AI Teammates in Software Engineering (SE) 3.0" (AIDev), 2025. https://arxiv.org/abs/2507.15003
26. Xu, G.; Subramanian, A.; Karthik, N. "AI Agent Pull Requests on GitHub: Frequency, Structure, and Merge Conflict Rates", jul. 2026. https://arxiv.org/abs/2607.04697
27. METR. "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity", jul. 2025. https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
28. Faros AI. "The AI Productivity Paradox Report 2025". https://www.faros.ai/blog/ai-productivity-paradox-report-2025
29. Limites de uso Claude (janela de 5 h e teto semanal), guias de terceiros e não oficiais: https://portkey.ai/blog/claude-code-limits. A fonte oficial é a `/usage` da conta.

**Limites desta pesquisa.**
- A busca funcionou, mas o acesso direto a arxiv.org, dora.dev e mergify.com estava bloqueado pela rede da sessão.
- Os números dessas fontes vêm dos trechos devolvidos pela busca e de resumos secundários, marcados [S] onde cabível.
- Para verificar no texto primário, é preciso liberar esses domínios.
