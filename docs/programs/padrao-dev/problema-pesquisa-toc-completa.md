# Teoria das Restrições completa: corpo, estado da arte e encaixe no modelo da Torre

Complementa `research-toc-thinking-processes.md` (TP: CRT, EC, FRT, PRT, TT, Goal Tree, CLR) e
`research-before-requirements.md`, e julga o desenho `docs/programs/padrao-dev/problema-desenho.md` (v2).
Escopo: o corpo inteiro da TOC (5FS/POOGI, TA, DBR/S-DBR/BM, CCPM, TP refinados, S&T, buy-in) e o uso em software,
DevOps e agentes. Critério de encaixe: padrão de elite, solução completa; o custo não decide. Cada adiado diz por quê.

## 0. Resposta curta

1. A TOC não é só os TP. O desenho v2 cobre o que mudar e para o que mudar (Goal Tree, CRT, nuvem, FRT), mas
   **não tem o objeto central da TOC: a restrição**, nem o laço de controle que a governa (DBR + gerenciamento de
   pulmão). Para um sistema cuja intenção é vazão (PR/s), isso é a lacuna maior. Proposta: `CONSTRAINT` como objeto,
   com o estado do passo de foco (5FS) e a evidência que a localiza.
2. **Throughput Accounting deve entrar, revertendo o adiamento do v2.** T, I e OE não exigem dinheiro: são vazão,
   dinheiro/esforço preso no sistema e custo de operar. A Torre já tem os três (PR/s mesclados, WIP e tokens não
   mesclados, quota/tokens por janela). A regra de decisão da TOC (ΔT, ΔI, ΔOE de cada injeção) é exatamente o
   juízo de capacidade x eficiência dos três domínios do AGENTS.md.
3. **DBR/S-DBR e Buffer Management são o laço de controle operacional** que falta: tambor = a restrição (hoje o
   gate/fila de merge ou a quota), corda = a regra que libera claims/unidades, pulmão = a fila pronta antes da
   restrição; as cores do pulmão priorizam e o Pareto das causas de vermelho alimenta UDEs (POOGI com dados).
4. **CCPM** dá o nível de programa: estimativas sem gordura, pulmão de programa agregado, fever chart, full kit
   antes de começar, escalonamento de programas pelo tambor. Hoje cada PR tem limites locais; a CCPM diz que a
   proteção é agregada, no fim da cadeia.
5. **S&T deve entrar como tipo próprio** (revertendo o v2): a Torre tem exatamente o caso para o qual Goldratt a
   criou (transformação em níveis com donos distintos: gerente, coordenadores de domínio, lanes; escada 1k→10k→100k).
   O nó S&T (strategy, tactic, NA, PA, SA) reusa NC, INJ e P; a árvore é o plano de "como causar a mudança".
6. **CLR e NBR como objetos** (revertendo o v2): com agentes, o escrutínio adversarial é barato e pode ser sempre
   ligado; um objeto de reserva por categoria é o registro auditável que o padrão exige.
7. As **camadas de resistência** e a **matriz de mudança** não viram objetos: viram uma checagem de completude do
   memorando a Daniel (as camadas mapeiam 1:1 nas seções do modelo) e um campo da D.
8. **Necessary but Not Sufficient** (as perguntas da tecnologia) é a lente mais direta para agentes de IA: o poder
   da tecnologia, a limitação que ela remove, as regras que acomodavam a limitação e as regras novas. Proposta:
   toda INJ de tecnologia aponta a regra antiga que substitui.
9. TOC com IA: há prática (software de TP como Flying Logic, sem IA; blogs sobre revisão de código como nova
   restrição; uma aula de Stanford 2026), mas **nenhuma fonte revisada por pares sobre CRT/nuvem construídos por LLM**
   foi encontrada. A Torre estaria além do estado publicado; o modelo deve prever validação (EXP) dessa construção.

## 1. Fontes

| # | Fonte | Uso |
|---|---|---|
| G1 | Goldratt & Cox, *The Goal* (North River, 1984; 3ª ed. 2004) | 5FS, restrição, T/I/OE, Herbie (DBR em semente) |
| G2 | Goldratt, *The Haystack Syndrome* (North River, 1990) | TA formal, T/CU, dado x informação, agendamento |
| G3 | Goldratt, *What Is This Thing Called Theory of Constraints* (1990) | 5FS formais, restrição de política |
| G4 | Goldratt, *It's Not Luck* (1994) | TP completos; restrição de mercado; |
| G5 | Goldratt, *Critical Chain* (1997) | CCPM |
| G6 | Goldratt, Schragenheim, Ptak, *Necessary but Not Sufficient* (2000) | As perguntas da tecnologia |
| G7 | Goldratt, *The Choice* (2008) | Pilares: simplicidade inerente, todo conflito pode ser removido, "nunca diga eu sei" |
| G8 | Goldratt, Goldratt-Ashlag, *Isn't It Obvious?* (2009) | Reposição, Dynamic Buffer Management (DBM) |
| G9 | Goldratt, "Standing on the Shoulders of Giants" (2006; *Gestão & Produção* 16(3):333–343, 2009, doi:10.1590/S0104-530X2009000300002) ([SciELO](https://www.scielo.br/j/gp/a/nw43nPSMWtFFqr4x5jhJkJn/?lang=en), [PDF](https://businesswales.gov.wales/sites/main/files/documents/Standing-on-the-Shoulders-of-Giants.pdf)) | Os 4 conceitos de fluxo (Ford, Ohno); limites do DBR; S-DBR |
| G10 | Goldratt, R. Goldratt, Abramov, "Strategy and Tactics" ([cópia WSU](https://public.wsu.edu/~engrmgmt/holt/em534/Goldratt/Strategic-Tactic.html); [toc-goldratt](https://toc-goldratt.com/en/product/strategy-and-tactics)) | S&T: nó com 5 elementos, níveis, regras |
| D1 | Dettmer, *Goldratt's TOC: A Systems Approach* (ASQ, 1997); *The Logical Thinking Process* (ASQ, 2007) | CLR, NBR, Goal Tree |
| D2 | Schragenheim & Dettmer, *Manufacturing at Warp Speed* (St. Lucie, 2000) | S-DBR, buffer management |
| H | Cox & Schleier (eds.), *Theory of Constraints Handbook* (McGraw-Hill, 2010): cap. 7 (Blackstone, revisão DBR/BM, [link](https://www.toc-goldratt.com/en/product/a-review-of-literature-on-drum-buffer-rope-buffer-management-and-distribution-chapter-7-of-the-theory-of-constraints-handbook)), 8 (DBR, BM e VATI, [link](https://www.toc-goldratt.com/en/product/dbr-buffer-management-and-vati-flow-classification-chapter-8-of-the-theory-of-constraints-handbook)), 9 (Schragenheim, S-DBR, [link](https://www.toc-goldratt.com/en/product/from-dbr-to-simplified-dbr-for-make-to-order-chapter-9-of-the-theory-of-constraints-handbook)), 20 (Goldratt-Ashlag, camadas de resistência, [link](https://www.toc-goldratt.com/en/product/the-layers-of-resistance-the-buy-in-process-according-to-toc-chapter-20-of-the-theory-of-constraints-handbook)), 23 (TP), 34 (S&T em organizações, [link](https://www.toc-goldratt.com/en/product/applications-of-strategy-and-tactics-trees-in-organizations-chapter-34-of-the-theory-of-constraints-handbook)) | Corpo de conhecimento consolidado |
| T | TOCICO: dicionário (Cox et al., 2ª ed. 2012; espelho de verbetes [S&T](https://bipulse.ru/app/dictionary/docs/strategy%20and%20tactics%20tree), [layers](https://bipulse.ru/app/dictionary/docs/layers%20of%20resistance)); glossário CCPM ([pdf](https://www.tocico.org/_files/ugd/af4d5f_d4914b5dc3664c94888503caa0de960a.pdf)); learning center ([S&T pt.1](https://learningcenter.tocico.org/courses/strategy-and-tactics-trees-part-1), [pt.2](https://learningcenter.tocico.org/courses/strategy-and-tactics-trees-part-2), [Viable Vision S&T](https://learningcenter.tocico.org/courses/anatomy-of-a-viable-vision-s-t-tree), [layers](https://learningcenter.tocico.org/courses/the-systemic-cloud-and-the-layers-of-resistance-hiding-in-plain-sight)) | Definições oficiais e prática |
| A1 | Watson, Blackstone & Gardiner, "The evolution of a management philosophy: The theory of constraints", *JOM* 25(2):387–402, 2007, doi:10.1016/j.jom.2006.04.004 | Revisão histórica das 5 eras da TOC |
| A2 | Mabin & Balderstone, *The World of the Theory of Constraints* (St. Lucie, 2000); "The performance of the TOC methodology", *IJOPM* 23(6), 2003 | Meta-análise de ~400 aplicações |
| A3 | Rahman, "Theory of constraints: a review of the philosophy and its applications", *IJOPM* 18(4):336–355, 1998 | Revisão |
| A4 | Kim, Mabin & Davies, *IJOPM* 28(2), 2008 (TP); Mabin et al., *System Dynamics Review* 2024 ([Wiley](https://onlinelibrary.wiley.com/doi/full/10.1002/sdr.1768)) | TP x dinâmica de sistemas |
| S1 | Anderson, *Agile Management for Software Engineering: Applying the TOC for Business Results* (Prentice Hall, 2003) ([InformIT](https://www.informit.com/store/agile-management-for-software-engineering-applying-the-9780131424609), [resenha ACCU](https://accu.org/bookreviews/2004/white_1359)) | TA e 5FS em software |
| S2 | Anderson, *Kanban* (Blue Hole, 2010); Reinertsen, *The Principles of Product Development Flow* (Celeritas, 2009) | WIP, filas, custo do atraso; crítica ao foco único no gargalo |
| S3 | Kim, Behr, Spafford, *The Phoenix Project* (IT Revolution, 2013); Kim et al., *The DevOps Handbook* (2016); Forsgren, Humble, Kim, *Accelerate* (2018) | The Goal reescrito para TI; Three Ways; métricas DORA |
| S4 | Flying Logic, documentação ([S&T](https://docs.flyinglogic.com/thinking-with-flying-logic/strategy-and-tactics-tree), [CRT](https://docs.flyinglogic.com/thinking-with-flying-logic/current-reality-tree)) | Software de TP (grafo com lógica AND/OR), sem IA |
| S5 | Prática sobre IA: [Swizec, "Theory of constraints, AI, and code review"](https://swizec.com/blog/theory-of-constraints-ai-and-code-review); [Scrum.org/Yeret](https://www.scrum.org/resources/blog/ai-coding-made-code-review-bottleneck-now-what); [Stanford CS224G 2026, aula 9](https://web.stanford.edu/class/cs224g/lectures/CS%20224G%202026%20Lecture%209%20-%20Building%20Good%20LLM%20Products%20with%20the%20Theory%20of%20Constraints.pdf); Kıcıman et al., "Causal Reasoning and LLMs", arXiv:2305.00050 (2023) | Opinião de praticantes; adjacente acadêmico (grafos causais por LLM) |

Limites: livros não relidos nesta sessão (pagos; resumos de conhecimento dos livros); public.wsu.edu fora da rede
desta sessão; verbetes TOCICO por espelho. Antes de citar formalmente, conferir no dicionário oficial e no Handbook.

## 2. Os cinco passos de foco (5FS), o POOGI e a restrição

**O que é.** G1/G3: (0) dizer a meta e as medidas (passo zero, TOCICO); (1) **identificar** a restrição;
(2) **explorar** (exploit: tirar o máximo dela sem gasto, nada de capacidade dela desperdiçada); (3) **subordinar**
tudo o mais à decisão do passo 2 (os não-restrição trabalham no ritmo dela, mesmo ociosos); (4) **elevar** (comprar
capacidade); (5) se a restrição quebrou, voltar ao passo 1 **sem deixar a inércia virar a restrição**. O POOGI
(Process Of OnGoing Improvement) é esse laço repetido.

**Tipos de restrição** (G3, G4, TOCICO): **física/recurso** (capacidade: uma máquina, o gate, a quota de tokens);
**de mercado** (demanda menor que capacidade: na Torre, unidades prontas na fila); **de política** (regras, medidas,
hábitos: Goldratt sustenta que a maioria das restrições reais é de política, e que atrás de toda restrição física
há uma política que a mantém). Distinção útil: gargalo (capacidade < demanda) x CCR (recurso com capacidade
restrita que, mal gerido, vira restrição). VATI (Handbook cap. 8) classifica o fluxo pela forma (V, A, T, I) e diz
onde a restrição tende a aparecer.

**Como se identifica e mede num fluxo.** (a) onde o trabalho espera (fila antes da etapa; Little: L = λ·W);
(b) a etapa mais ocupada (utilização perto de 100%, ociosidade das vizinhas); (c) **a origem dos buracos no pulmão**
(BM: a etapa onde as ordens vermelhas estão paradas; é o método preferido da TOC, porque mede o efeito no tambor e
não a utilização local); (d) para restrição de política: a regra que obriga o comportamento que causa (a) ou (b)
(vem da CRT). Na Torre: `scripts/flow-metrics --constraint` já nomeia a restrição (AGENTS.md, três domínios).

**G9, os 4 conceitos de fluxo** (Ford/Ohno → TOC): (1) melhorar o fluxo (lead time) é o objetivo primário de
operações; (2) isso se traduz num mecanismo que diz **quando não produzir** (sem superprodução: corda, limite de
WIP); (3) eficiências locais devem ser abolidas; (4) um processo de foco para equilibrar o fluxo (BM). Para agentes:
medir lanes por utilização ou tokens próprios é eficiência local; a medida é o PR/s do sistema.

**Encaixe.** Falta no v2. Novo objeto **CONSTRAINT**: `kind` (physical, market, policy), `locus` (etapa: intake,
claim, coding, gate, merge queue, deploy, quota, atenção do dono), `step` (identified, exploited, subordinated,
elevated, broken), `evidence` [leituras de fila, utilização, origem do vermelho], `since`, `until`. Ligações:
`limits` → NC de vazão; `held-by` → D ou chave do registro (a política que a mantém, quando `kind: policy`);
`exploited-by`/`subordinated-by`/`elevated-by` → INJ/WORK; `succeeded-by` → CONSTRAINT (a história do POOGI).
Regras: existe exatamente uma CONSTRAINT ativa por NC de vazão; INJ de eficiência local sem efeito na restrição ativa
é sinalizada (G9 conceito 3). **Quem/quando**: a ferramenta propõe (flow-metrics), a sessão (coordenador de
capacidade) confirma e escreve o passo; Daniel só é informado. Antes do programa (escolhe o programa de capacidade) e
contínuo; a quebra (step: broken) abre a próxima volta.

## 3. Throughput Accounting (T, I, OE; T/CU)

**O que é** (G1, G2). T = taxa com que o sistema gera dinheiro por vendas (preço − custos totalmente variáveis);
I = dinheiro investido em coisas que se pretende vender (inclui WIP); OE = dinheiro gasto para converter I em T.
Derivados: NP = T − OE; ROI = (T − OE)/I; produtividade = T/OE; giro = T/I. **T/CU** (throughput por unidade da
restrição) ordena o mix: priorizar o que dá mais T por minuto da restrição (G2). **Regra de decisão**: toda
decisão é julgada por ΔT, ΔI, ΔOE, na ordem de importância T > I > OE (G1, Anderson S1). Anderson (S1) traduz para
software: T = valor entregue (funcionalidades em produção), I = ideias/requisitos em processo, OE = custo do time;
a resenha (ACCU) nota que o foco real é lead time.

**Análogos para a Torre (não financeiros).**

| TA | Torre | Fonte |
|---|---|---|
| T | PRs mesclados por segundo que passam pelos guardas de qualidade (retrabalho, reverts) | `flow-metrics --prs`, `--guards` |
| I | WIP: unidades com claim, PRs abertos, ramos não mesclados; e os tokens já gastos neles (investimento preso) | fila, ledger, git |
| OE | tokens/quota/compute por janela (o guarda de custo da SEMENTE) | quota, `scripts/model measure` |
| T/OE | PRs mesclados por token (custo por PR mesclado, domínio eficiência) | derivado |
| T/I | giro do WIP; com Little, lead time = I/T | derivado |
| T/CU | PRs mesclados por unidade da restrição ativa (por segundo de gate, por % da quota) | derivado da CONSTRAINT |

**Encaixe.** Reverte o adiamento do v2 ("domínio financeiro"): a razão não se sustenta, porque T/I/OE são
definidos sobre a meta, e a meta da Torre é vazão com guardas. Entram como **MEAS** de nível CSF (três NC: vazão,
investimento preso, custo de operar), e a INJ ganha `effects_on {T, I, OE}` (previsto pela sessão no desenho;
medido pela ferramenta depois, no benefício). A ordem T > I > OE é o critério de desempate da D. **Quem**: a
ferramenta lê; a sessão prevê Δ; Daniel aceita os alvos (são alvos de CSF). **Quando**: antes (baseline), desenho
(Δ previsto), depois (Δ medido). Fica de fora só o valor monetário de T (não há venda); T/CU monetário é substituído
por T/CU em PRs.

## 4. Drum-Buffer-Rope, S-DBR e Buffer Management como laço de controle

**DBR** (G1 "Herbie", formalizado em Goldratt & Fox, *The Race*, 1986; Handbook cap. 7–8). **Tambor**: o plano da
restrição (ela dita o ritmo). **Pulmão**: tempo (não estoque) de proteção antes da restrição (pulmão da restrição),
antes da expedição e nas montagens. **Corda**: a liberação de material amarrada ao consumo do tambor; nada entra
antes do tempo (conceito 2 de G9). **S-DBR** (D2; Handbook cap. 9; G9): quando o mercado é a restrição, um único
pulmão de expedição; a carga planejada da CCR decide datas prometidas; a corda vai da data devida à liberação.
Tornou-se o padrão das aplicações recentes (Souza/Pires, *G&P* 2010, [SciELO](https://www.scielo.br/j/gp/a/CYW8dy7nQLyxBvMjm6VQRcL/?format=pdf)).

**Buffer Management (BM).** Estado do pulmão = consumido/total, em terços: **verde** (nada a fazer), **amarelo**
(planejar ação), **vermelho** (agir), **preto** (atrasado). Prioridade de execução = cor (não FIFO, não urgência
política). **Análise de penetração**: registrar por que cada ordem entrou no vermelho e onde estava; o Pareto das
causas é o foco do POOGI (BM localiza a restrição e alimenta a melhoria). **DBM** (G8): muito vermelho → aumentar o
pulmão em 1/3; muito verde → reduzir em 1/3; isto é, o pulmão se dimensiona sozinho por feedback.

**Como laço de controle.** Referência (pulmão alvo) → sensor (estado do pulmão por item) → controlador (cor →
prioridade; DBM → tamanho) → atuador (corda: liberar ou segurar claims) → perturbação (variação, falhas) →
aprendizado (Pareto → UDE → CRT). É um controlador de realimentação com dois tempos: rápido (prioridade) e lento
(dimensionamento e POOGI).

**Encaixe na Torre.**
- Tambor = CONSTRAINT ativa (hoje gate/merge queue ou quota). Corda = regra de admissão de claims e de fronts
  ("no máximo sete fronts; mais quando a caixa < 70% ocupada": já é uma corda escrita à mão em AGENTS.md; deve virar
  POLICY derivada do tambor). Pulmão = a fila de unidades/PRs prontos antes do tambor, medido em tempo.
- **Pulmão por WORK** (derivado, ferramenta): idade do item contra o tempo de ciclo alvo → cor. A prioridade de
  claim e de fila segue a cor.
- **Penetração**: cada vermelho registra causa; o friction log já é esse registro. A ferramenta gera o Pareto e
  propõe UDEs (ligação `evidence` do UDE → Pareto). Fecha o laço BM → UDE → CRT → INJ, que o v2 não tem.
- **DBM**: a ferramenta propõe o novo tamanho de pulmão/limite de WIP; a mudança é uma D reversível (D-294).
- Objetos: **BUFFER** (config: protege → CONSTRAINT ou programa; tamanho em tempo; zonas; histórico DBM) e
  **POLICY/rope** (chave do registro com `derived-from` → CONSTRAINT). Estado do pulmão e cor: derivados.
- **Quem/quando**: a sessão de capacidade desenha a corda e o pulmão (desenho); a ferramenta mede e colore
  (entrega, contínuo); DBM é ferramenta + D (depois); Daniel não entra.

## 5. Critical Chain (CCPM) e a entrega de unidades/PRs

**O que é** (G5; Handbook; [glossário TOCICO](https://www.tocico.org/_files/ugd/af4d5f_d4914b5dc3664c94888503caa0de960a.pdf)).
Corrente crítica = a cadeia mais longa considerando dependências **e recursos**. Estimativas sem segurança
(≈ mediana); a segurança removida é **agregada** no fim: **pulmão de projeto** (≈ 50% da cadeia, ou raiz da soma dos
quadrados), **pulmões de alimentação** onde cadeias não críticas entram na crítica, **pulmões de recurso** (aviso
antecipado). Comportamentos: corredor de revezamento (começar ao receber, entregar ao terminar; sem datas por
tarefa), sem multitarefa ruim, Lei de Parkinson e síndrome do estudante como alvos. **Fever chart**: % da corrente
completada (x) contra % do pulmão consumido (y), com zonas verde/amarela/vermelha e tendência. **Multiprojeto**:
escolher o recurso tambor (virtual) e **escalonar** a entrada de projetos pela sua capacidade, com pulmão de
capacidade; prioridade entre projetos pelo vermelho. **Full kit** (Goldratt, depois de 2000): não começar sem tudo
o necessário.

**Encaixe.**
- Programa = projeto; unidade/PR = tarefa; lane = recurso; gate = recurso compartilhado (tambor virtual).
- **Pulmão de programa** agregado (não limites por PR); **fever chart por programa** (ferramenta, derivado da fila e
  dos merges); cor de programa decide prioridade de alocação de fronts (gerente).
- **Full kit** como regra de claim: uma unidade só é liberada com NEED/REQ ligados, premissas, critério de VER e
  dependências mescladas (checagem de grafo, ferramenta). Reduz retrabalho (o "yield em uma rodada" do AGENTS.md).
- **Escalonamento**: programas entram pela capacidade do tambor; a lane exclusiva por unidades (D-065) já é a regra
  anti-multitarefa.
- Objetos: o PLAN do programa ganha `chain` (ordem das unidades), `estimate` por unidade (mediana),
  `buffer` (BUFFER do tipo program) e `feeding` nas junções. **Quem/quando**: sessão no desenho (cadeia, estimativas,
  pulmão), ferramenta na entrega (fever chart), sessão no depois (lição: o pulmão foi consumido por quê).

## 6. Thinking Processes: refinamentos além da pesquisa anterior

### 6.1 Three-cloud e conflito central
Goldratt (programa Jonah/Satélite; Handbook cap. 23; T11 da pesquisa anterior): escolher três UDEs diversos,
escrever uma nuvem por UDE (A objetivo, B e C necessidades, D e D′ ações em conflito), generalizar as três numa
**nuvem central** (core conflict); o CRT então liga a nuvem central aos UDEs (communication CRT). É mais rápido que o
CRT de baixo para cima, mas precisa do CRT para provar cobertura. **Encaixe**: CONFLICT já existe; adicionar
`kind` (ude-cloud, core) e `generalizes` → CONFLICT; regra: o core cobre os UDEs pelo CRT (ferramenta mede a
cobertura). Sessão / desenho; Daniel aceita o core.

### 6.2 Goal Tree (IO Map)
Dettmer 2007: meta → 3–5 CSF → NC, lógica de necessidade ("para ter X preciso de Y"); é o padrão de comparação para
os UDEs. Já está no v2 (NC). Acréscimo: os três CSF de TA (§3) e o CSF de qualidade (guardas) entram como CSF
canônicos de um sistema de fluxo.

### 6.3 Strategy & Tactics (S&T) em detalhe
**Origem**: Goldratt, 1985, engavetada por não conseguir ensinar; retomada na Goldratt Group em meados dos 2000 para
o **Viable Vision** (meta: em ~4 anos, lucro igual ao faturamento de hoje) (T, [TOCICO](https://learningcenter.tocico.org/courses/strategy-and-tactics-trees-part-1)).
**Nó** (G10, S4): cinco elementos por passo:
- **Strategy**: o objetivo do passo ("para quê"), o estado que ele deve atingir, sempre mensurável;
- **Tactic**: como ("o quê fazer") para atingir a estratégia;
- **Necessary Assumption (NA)**: por que esta estratégia é necessária para a tática do nível de cima (fatos da
  realidade atual que tornam o passo necessário);
- **Parallel Assumption (PA)**: por que esta tática atinge esta estratégia, e por que esta e não outra; responde
  objeções que não são de necessidade nem de suficiência (S4 nota variação entre autores);
- **Sufficiency Assumption (SA)**: por que os filhos, juntos e na ordem, bastam para a tática do pai.
**Leitura**: "Para atingir [estratégia do pai] eu preciso de [estratégia do filho], porque [NA]; para isso farei
[tática], porque [PA]; e estes passos bastam, porque [SA]". **Construção**: de cima para baixo, uma camada por
nível hierárquico (nível 1 = meta da organização, nível 2 = vantagem competitiva decisiva (DCE) + explorá-la +
sustentá-la, níveis 3–5 por função), em geral 4–5 níveis, até ações de uma ou duas semanas; os passos baixos viram o
plano de projeto CCPM (§5). Cada nível tem dono (o gerente desse nível). **Árvores genéricas**: Goldratt publicou
S&Ts por ambiente: Reliable Rapid Response (make-to-order), make-to-availability, inventory turns em bens de consumo,
gestão de projetos ([CPG](https://www.toc-goldratt.com/en/product/s-and-t-tree-consumer-goods-inventory-turns),
[PM](https://toc-goldratt.com/en/product/s-and-t-tree-project-management)); elas embutem os 5FS em sequência
(explorar, subordinar, elevar) e os pilares de buy-in. **Uso**: plano, comunicação, alinhamento e controle (cada
nó tem medida; a revisão verifica as premissas quando um nó não entrega).

**Encaixe (reverte o adiamento do v2).** A razão do v2 ("entra quando houver mais de dois níveis com donos
distintos") **já está cumprida**: SEMENTE (intenção) → três domínios (capacidade, eficiência, administração) →
programas → unidades/lanes, com gerente, coordenadores e lanes como donos. Objeto **ST**: `level`, `strategy`
(ref → NC ou texto mensurável com MEAS), `tactic` (ref → INJ escolhida), `assumptions` [P com `role`: necessary,
parallel, sufficiency], `owner_role` (manager, domain-coordinator, lane), `child-of` → ST. O nível mais baixo
`decomposes-into` → WORK. Regras: todo ST tem NA e SA; uma P refutada sob um ST reabre o nó; um ST sem MEAS é não
conforme. **Quem/quando**: níveis 1–2 sessão redige, Daniel valida (é desdobramento da intenção, e a trava de
intenção é dele); níveis 3+ coordenador de domínio (sessão de vida curta) no desenho; lanes no último nível;
ferramenta mede os nós na entrega; lição revisa premissas no depois. Relação com o v2: Goal Tree = o quê (estado
desejado), CRT/nuvem = por quê, S&T = como, e substitui PRT/TT no nível de programa (OBST continua como fonte das
NA: um obstáculo é a realidade que torna um passo necessário).

### 6.4 NBR e CLR
**NBR** (D1; [Wikipedia](https://en.wikipedia.org/wiki/Negative_branch_reservations)): injeção → cadeia causal →
efeito negativo; a resposta é uma injeção de poda (trimming) ou o aceite do risco. **CLR** (D1), oito categorias:
clareza; existência da entidade; existência da causalidade; insuficiência da causa; causa adicional;
inversão causa-efeito; existência do efeito previsto; tautologia.
**Encaixe (reverte o adiamento).** Objeto **RESERVATION**: `category` (8 CLR + negative-branch), `target`
(entidade ou seta), `raised_by`, `chain` (para NBR: CAUSE encadeadas), `resolution` (amended, trimmed-by INJ,
accepted-by D, rejected com razão), `state`. A razão do v2 ("só com revisão adversarial frequente") é cumprida por
desenho: uma sessão escrutinadora distinta da autora roda em toda CRT/FRT/S&T (custo marginal baixo com agentes, e o
padrão de elite exige o registro). A ferramenta levanta as formais (tautologia: efeito citado como evidência da
causa; entidade sem evidência; ciclo; insuficiência quando uma seta única carrega um `and_group` incompleto).
**Quem/quando**: escrutinador (sessão) e ferramenta / desenho; Daniel só nas aceitas com risco residual.

### 6.5 Camadas de resistência e matriz de mudança
**Camadas** (Goldratt; Handbook cap. 20, Goldratt-Ashlag; TOCICO): seis na forma clássica: (1) desacordo sobre o
problema; (2) sobre a direção da solução; (3) a solução não resolve o problema; (4) "sim, mas" (efeitos negativos);
(5) "não dá, por causa de" (obstáculos); (6) medos não verbalizados (dúvida sobre os outros). Variantes de 5 a 9
camadas (acrescentam "não há problema", "está fora do meu controle"); Goldratt-Ashlag agrupam em três classes:
problema, solução, implementação. Mapa nos TP: 1 → CRT/nuvem; 2 → injeção; 3 → FRT; 4 → NBR; 5 → PRT/OBST;
6 → TT/S&T e o primeiro passo. **Matriz de mudança** ("4 visões do buy-in", "jacaré e sereia"): ganhos de mudar,
perdas de mudar, ganhos de não mudar, perdas de não mudar.
**Encaixe**: sem objeto novo. (a) **checagem de completude** do memorando de desenho a Daniel: cada camada exige a
seção do modelo correspondente (UDE+CAUSE+CONFLICT; INJ; FRT/effects; RESERVATION fechadas; OBST; ST/primeiro
WORK) — a ferramenta acusa a camada que falta; (b) a D ganha `change_matrix` {gain_change, loss_change,
gain_no_change, loss_no_change}, que generaliza a alternativa "não fazer" já exigida. Razão de não virar objeto: os
agentes não resistem; o único buy-in é de Daniel, e as camadas já são as seções do modelo. Sessão / desenho.

### 6.6 As perguntas da tecnologia (Necessary but Not Sufficient)
G6: tecnologia só traz benefício se remove uma limitação **e** as regras que acomodavam a limitação mudam:
(1) qual o poder da tecnologia; (2) que limitação ela diminui; (3) que regras nos ajudavam a conviver com a
limitação; (4) que regras usar agora; (Goldratt, *Beyond the Goal*, 2005, acrescenta (5) que mudança a tecnologia
precisa e (6) como causar a mudança). Para a Torre, a tecnologia é o agente de IA; a limitação removida é a
capacidade humana de escrever e revisar; as regras antigas (revisão humana, lote grande, cadência por relógio, horário
comercial) são restrições de política. **Encaixe**: INJ `kind: technology` exige `replaces` → a política antiga
(D/registro) e `new_rule`; CONSTRAINT `kind: policy` é o alvo típico. Sessão / desenho.

### 6.7 Pilares de The Choice
Simplicidade inerente; todo conflito pode ser removido; pessoas são boas (o problema é o sistema); "nunca diga eu
sei". **Encaixe**: axiomas do metamodelo, já presentes: todo UDE tem causa, todo CONFLICT procura injeção (não
compromisso), toda P tem estado (to-validate, confirmed, refuted) e pode ser reaberta.

## 7. TOC em engenharia de software, DevOps e agentes

- **Anderson (S1, 2003)**: 5FS e TA em processos ágeis (FDD, XP, Scrum); T = valor entregue; I = requisitos em
  processo; lead time como alavanca. **Kanban (S2, 2010)**: limite de WIP como corda; Anderson apresenta o Kanban como
  derivado do DBR. **Reinertsen (S2, 2009)**: filas e custo do atraso; critica a ideia de uma só restrição em
  desenvolvimento (variabilidade alta, gargalos que migram) e prefere controle de fila e lotes pequenos; para a
  Torre, isso reforça BM/WIP e o passo 5 (a restrição migra rápido).
- **Phoenix Project / DevOps Handbook / Accelerate (S3)**: The Goal reescrito para TI; Three Ways (fluxo,
  realimentação, aprendizado); "melhoria fora da restrição é ilusão"; DORA (lead time, frequência de deploy, taxa de
  falha de mudança, tempo de recuperação) como os guardas de qualidade de um fluxo de entrega. Encaixe: as quatro
  DORA entram como MEAS sob as NC de vazão e qualidade.
- **Agentes de IA (S5)**: praticantes de 2025–2026 relatam que, com geração de código barata, a restrição migra para
  revisão e integração (PRs maiores, revisão mais lenta), e aplicam os 5FS (preparar pacotes de revisão, lotes
  menores, subordinar a geração à revisão). São opiniões, não estudos. A aula de Stanford (2026) aplica TOC à qualidade
  de produtos com LLM ("o LLM quase nunca é a restrição"). **Flying Logic** é a ferramenta de TP mais usada (grafo
  com operadores AND/OR, S&T, CRT), sem IA. Kıcıman et al. (2023) mostram LLMs gerando grafos causais com boa
  acurácia em benchmarks, com falhas imprevisíveis: base adjacente, não TOC.
- **Conclusão**: **não há fonte credível (revisada por pares ou TOCICO) sobre CRT, nuvem, FRT ou S&T construídos por
  LLM, nem sobre DBR/BM governando agentes.** A Torre estaria além do publicado. Consequência no modelo: a construção
  por sessão é uma P de alto raio ("uma sessão constrói CRT/S&T que sobrevivem às CLR") com EXP: amostra de árvores
  escrutinadas, taxa de reservas aceitas, e o benefício previsto contra o medido (LESSON).

## 8. Quadro de encaixe: elemento → objeto/ligação/medida, quem, quando

| Elemento TOC | No modelo | Quem | Quando |
|---|---|---|---|
| Passo 0 (meta e medidas) | INT + NC (CSF de T, I, OE, qualidade) + MEAS | Daniel aceita; sessão redige | antes |
| Restrição (física, mercado, política) | **CONSTRAINT** novo; `limits` → NC; `held-by` → D/registro | ferramenta propõe; sessão confirma | antes, contínuo |
| 5FS / POOGI | CONSTRAINT.`step` + `exploited/subordinated/elevated-by` → INJ/WORK; `succeeded-by` | sessão de capacidade | desenho, entrega, depois |
| T, I, OE, T/OE, T/I, T/CU | MEAS (T = PR/s com guardas; I = WIP+tokens presos; OE = tokens/quota); derivados | ferramenta | contínuo |
| Regra de decisão ΔT/ΔI/ΔOE | INJ.`effects_on`; D usa T > I > OE | sessão prevê; ferramenta mede | desenho; depois |
| Tambor | = CONSTRAINT ativa | ferramenta | contínuo |
| Corda | **POLICY** (chave de registro) `derived-from` → CONSTRAINT | sessão desenha; D | desenho |
| Pulmão, zonas, DBM | **BUFFER** (config + histórico); cor por WORK derivada | sessão desenha; ferramenta mede e propõe DBM | desenho; entrega; depois |
| Análise de penetração | Pareto do friction log → `evidence` de UDE | ferramenta; sessão escreve UDE | entrega, depois |
| CCPM (cadeia, pulmão de programa, alimentação) | PLAN.`chain`, `estimate`, BUFFER(program), `feeding` | sessão | desenho |
| Fever chart | derivado por programa | ferramenta | entrega |
| Full kit | checagem de grafo antes do claim | ferramenta | entrega |
| Escalonamento multiprojeto | admissão de programas pela capacidade do tambor | gerente (sessão) | antes de cada programa |
| Goal Tree | NC (já no v2) | sessão; Daniel aceita CSF | antes |
| UDE, CRT, CAUSE | (já no v2) + evidência de BM | sessão; ferramenta | antes, desenho |
| Three-cloud / core conflict | CONFLICT.`kind`, `generalizes`; cobertura pelo CRT | sessão; Daniel aceita core | desenho |
| INJ, FRT | (já no v2) + `kind: technology` com `replaces` | sessão | desenho |
| NBR, CLR | **RESERVATION** novo | escrutinador + ferramenta | desenho |
| S&T | **ST** novo (strategy, tactic, P com role NA/PA/SA, owner_role) | n1–2 sessão + Daniel; n3+ coordenador; folhas lanes | desenho |
| PRT / TT | OBST (fonte de NA) + ST folhas → WORK | sessão | desenho |
| Camadas de resistência | checagem de completude do memorando | ferramenta | desenho, antes de levar a Daniel |
| Matriz de mudança | D.`change_matrix` | sessão | desenho |
| Perguntas da tecnologia | INJ technology `replaces`/`new_rule` | sessão | desenho |
| Benefício / POOGI | NC lida; UDE state; CONSTRAINT broken → nova volta; LESSON | ferramenta; sessão; Daniel no veredito que muda a intenção | depois |

Regras novas de grafo (somar às 10 do v2): (11) há uma CONSTRAINT ativa por NC de vazão, com evidência atual;
(12) toda INJ escolhida declara ΔT/ΔI/ΔOE; (13) a corda de admissão deriva da CONSTRAINT ativa; (14) WORK em
vermelho tem causa registrada; (15) todo ST tem NA e SA e MEAS; folha de ST tem WORK; (16) RESERVATION aberta
bloqueia D; (17) INJ technology aponta a regra que substitui; (18) WORK só recebe claim com full kit.

## 9. Adiado, e por que não falta (critério: padrão de elite)

- **Valor monetário de T e NP/ROI**: a Torre não vende; o T não monetário é a própria meta. Entra se houver receita.
- **Reposição/distribuição de Isn't It Obvious além do DBM**: não há estoque distribuído; o DBM, que é a parte
  geral, entra (§4).
- **Marketing/"mafia offer" e a DCE de mercado do Viable Vision**: a Torre não compete por clientes; a estrutura
  S&T entra sem essa camada.
- **Camadas de resistência e matriz como objetos**: ver §6.5; o buy-in é de uma pessoa e as camadas já são seções.
- **Agendamento detalhado do tambor (DBR clássico com plano da restrição por slot)**: a restrição é fila de eventos,
  não máquina agendável; S-DBR + BM é o estado da arte para esse caso (G9, Handbook cap. 9).
