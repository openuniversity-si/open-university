# PADRAO-DEV — o que vem antes dos requisitos: desenho v3

Para Daniel decidir antes de qualquer implementação. A PR #340 fica em rascunho.

**Histórico dos pedidos de Daniel:**

- 19/11 ~13:11 BRT: o pedido.
- ~13:22: retorno sobre o v1. Quis uma solução completa, a separação explícita, quem cria o quê e quando, e a TOC.
- Retorno sobre o v2: quis a pesquisa completa da TOC, a reavaliação do que foi adiado (a árvore de estratégia e
  tática e o "use case"), e uma proposta de implementação completa das partes anteriores aos requisitos.

**Pesquisas:**

- [problema-pesquisa.md](problema-pesquisa.md): ISO/IEC/IEEE 15288 6.4.1–6.4.2, 29148, INCOSE NRM, BABOK, ISO 21502.
- [problema-pesquisa-toc.md](problema-pesquisa-toc.md) e
  [problema-pesquisa-toc-completa.md](problema-pesquisa-toc-completa.md): o corpo inteiro da TOC (cinco passos,
  throughput accounting, DBR e gestão de pulmão, Critical Chain, os processos de pensamento, S&T, camadas de
  resistência, as perguntas da tecnologia) e o uso por agentes.
- [problema-pesquisa-casos.md](problema-pesquisa-casos.md): use case, business case, avaliação de opções e a prática
  de especificação com agentes.

**Critério:** solução completa, no nível de desempenho do padrão. Cada elemento entra porque um padrão de elite o
exige. Cada adiamento diz por que não falta. Nada fica de fora por custo.

## 1. Respostas diretas às perguntas de Daniel

**O que vem antes dos requisitos?** Quatro camadas que o modelo ainda não tem. Todas as fontes concordam nelas.

1. **Estado desejado medido.** A meta, os fatores críticos e as condições necessárias, cada um com medida, baseline
   e alvo.
2. **Estado atual e gap.** As leituras, os efeitos indesejados e a distância até o alvo.
3. **Problemas.** A causa central que explica o gap e o conflito que faz o problema persistir.
4. **Soluções.** As candidatas, a prova lógica e a empírica, o business case, a escolha, os cenários de uso e o
   plano de estratégia e tática.

Só então vêm as necessidades e os requisitos. Depois da entrega, o laço fecha na medida do benefício.

**O ciclo requisitos → conformidade é parte de um sistema maior?** Sim. Na 15288 os processos técnicos são um de
quatro grupos. Na TOC, a engenharia é o "como" de uma injeção escolhida. O sistema maior é o ciclo de melhoria
contínua (POOGI), e o centro dele é a **restrição** do fluxo:

1. identificar a restrição;
2. explorá-la;
3. subordinar o resto a ela;
4. elevá-la;
5. recomeçar quando ela mudar de lugar.

O ciclo termina na intenção da SEMENTE, que só Daniel valida.

**A árvore de estratégia e tática (S&T).** É de Goldratt: criada em 1985 e retomada nos anos 2000 para o Viable
Vision. Cada nó tem cinco elementos:

- a **estratégia**: o para quê, mensurável;
- a **tática**: o como;
- a **premissa necessária**: por que este passo é preciso;
- a **premissa paralela**: por que esta tática e não outra;
- a **premissa de suficiência**: por que os filhos bastam.

Os níveis descem da meta até ações de uma ou duas semanas, e cada nível tem dono. **Faz sentido aqui e entra.** A
Torre já tem os níveis e os donos: a intenção, os três domínios (capacidade, eficiência, administração), os
programas, as unidades e as lanes. Hoje a lógica entre eles vive em texto. No nível de programa, a S&T substitui as
árvores de pré-requisitos e de transição do v2.

**O "use case".** Não vem da TOC. Vem da engenharia de software: Jacobson (1987/1992), Cockburn (2001) e
Use-Case 2.0 com suas fatias (2011). Nos padrões, é o cenário operacional da ConOps/OpsCon (29148 Anexo A; 15288
6.4.2). **Faz sentido e entra** como cenário (SCEN), entre a solução escolhida e as necessidades. Seus passos
numerados, com ator, são a especificação de comportamento mais executável que existe antes do requisito, e um
agente a usa direto. A validação executa o cenário, e cada unidade declara que fatia dele entrega.

**O business case.** Também não vem da TOC, mas a TOC lhe dá a moeda: throughput, investimento e despesa
operacional. O adiamento do v2 ("a Torre não decide por retorno financeiro") estava errado. A ISO 21502, o PRINCE2 e
o Five Case Model do Tesouro britânico exigem a **justificativa contínua com opções e acessibilidade**, não dinheiro.
A Torre gasta cota e AWS e decide entre caminhos (D-327). **Entra** como CASE por programa:

- cinco dimensões: estratégica, econômica, comercial, financeira e de gestão;
- avaliação de opções, sempre com "não fazer" e "fazer o mínimo";
- critérios fixados antes das notas;
- teste de sensibilidade;
- vereditos nos pontos de revisão.

## 2. O modelo, por seções

Quem cria:

- **Daniel**: decide e aceita;
- **sessão**: analisa e propõe; o gerente, os coordenadores de domínio e as lanes são sessões;
- **revisor**: uma sessão independente, que não escreveu o objeto;
- **ferramenta**: deriva das medidas e dos registros, sem mão.

Quando: **antes** do programa; **desenho**; **entrega**; **depois** da entrega; **contínuo**.

### (a) Estado desejado: Goal Tree medida

| Objeto | O que é | Campos principais | Ligações | Quem / quando |
|---|---|---|---|---|
| INT (existe) | A intenção e a meta (SEMENTE) | statement, owner | — | Daniel / antes |
| **NC** | Fator crítico (`level: csf`, 3 a 5) ou condição necessária (`level: nc`) | statement (gramática de resultado: direção + medida + objeto), level, weight (só CSF), `target` {comparator, valor ou chave de registro, by?}, `baseline` {value, date, source} | `necessary-for` → INT ou NC; `measured-by` → MEAS (obrigatória) | a sessão redige; Daniel aceita os CSF, os pesos e os alvos / antes; a sessão fixa o baseline pela leitura |
| MEAS (existe) | A medida (ISO 15939) | (existente) | — | sessão define, ferramenta lê |

Os CSF da Torre cobrem throughput, investimento, despesa operacional (T, I, OE, §2(h)) e qualidade. Uma Goal Tree
sem medida não é falsificável, e uma medida sem Goal Tree não tem lógica de necessidade.

### (b) Estado atual

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| Leitura (derivada) | Valor atual de cada MEAS | value, at | — | ferramenta / contínuo |
| **UDE** | Efeito indesejado, factual e presente | statement, `evidence` [leituras, incidentes, fricções, Pareto das causas de vermelho], magnitude, state (observed, gone, returned) | `violates` → NC (obrigatória) | a ferramenta acusa uma NC fora do alvo sem UDE; a sessão escreve / antes e contínuo |

### (c) Gap (derivado, nunca escrito)

Por NC: o alvo, a leitura atual, o baseline, a distância e a tendência. É calculado pela ferramenta a cada leitura e
aparece no `scripts/model measure` e no `show`.

### (d) Problemas: por que o gap existe e por que persiste

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **CAUSE** | Entidade da árvore da realidade atual (CRT): intermediária, raiz ou central | statement, kind (intermediate, root, core), `and_group` | `causes` → CAUSE ou UDE | a sessão constrói; a ferramenta calcula a cobertura da central (a fração dos UDE que alcança) e acusa ciclos / desenho; Daniel aceita a central |
| **CONFLICT** | A nuvem: objetivo A, necessidades B e C, pré-requisitos D e D′ | a, b, c, d, d_prime, kind (local, core), `generalizes` [CONFLICT] (o método das três nuvens) | `objective-is` → NC; `perpetuates` → CAUSE central; `assumes` → P | sessão / desenho; Daniel aceita o conflito central |
| P (existe) | A premissa sob uma seta | ganha `role` (arrow, necessary, parallel, sufficiency) | — | sessão; um EXP a confirma ou a refuta |
| **RESERVATION** | Reserva: categoria de reserva legítima (CLR) sobre uma entidade ou seta, ou ramo negativo | kind (clarity, entity-existence, causality-existence, cause-insufficiency, additional-cause, predicted-effect, tautology, negative-branch), statement, state (open, answered, accepted) | `on` → qualquer entidade da CRT, nuvem, injeção ou S&T; `answered-by` → INJ ou edição; `accepted-by` → D | o **revisor** (nunca o autor) e a ferramenta (tautologia, entidade sem evidência, ciclo) / desenho |

Uma reserva aberta bloqueia a decisão. É a revisão adversarial que torna a lógica confiável, para pessoas e
principalmente para agentes. A pesquisa não achou nenhuma fonte revisada sobre árvores TOC construídas por LLM.
Por isso o desenho trata "uma sessão constrói árvores que sobrevivem à revisão" como premissa de alto raio, com seu
próprio experimento (§4, fase 6).

### (e) Soluções: candidatas, provas, business case, escolha

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **INJ** | Injeção, a solução candidata (várias por problema, sempre com `do-nothing` e `do-minimum`) | statement, kind (policy, mechanism, measure, technology), `effects` [efeito desejado ↔ UDE invertido], `delta` {T, I, OE} previsto, `appetite` {tokens, wall, prs}, `no_gos`, `rabbit_holes`; se technology: `limitation_removed`, `old_rules`, `new_rules`; state (candidate, chosen, rejected) | `addresses` → CAUSE ou CONFLICT; `invalidates` → P; `inverts` → UDE; `decided-by` → D | sessão / desenho |
| **EXP** | Experimento, protótipo ou prova de conceito | hypothesis, method, `criterion` sobre uma MEAS, result, state (planned, running, confirmed, refuted) | `tests` → P ou INJ; `measured-by` → MEAS | a sessão desenha e roda; a ferramenta lê o resultado / desenho e entrega |
| **CASE** | Business case do programa (Five Case Model adaptado) | `stage` (outline, full, maintained, closed); strategic e economic derivados do grafo; `commercial` (dependências de fornecedor: Anthropic, AWS, GitHub, com limite e risco); `financial` (`budget` {tokens, usd, by}); `management` (`review_points`, `revert_path`); `verdicts` [{point, still_justified, why, D}] | `for` → programa (WORK); `justifies` → D | a sessão monta; a ferramenta deriva o derivável; Daniel aceita `budget`/`appetite` quando há dinheiro ou cota fora do normal / antes (outline), desenho (full), entrega (maintained), depois (closed) |
| D (existe) | A escolha | ganha `level` (business, architecture) e, em business, `appraisal`: critérios vindos das NC, fixados com data antes das notas; opções → INJ; notas com evidência (EXP, MEAS ou P); custo por opção; custo por unidade de gap fechado; sensibilidade; e `change_matrix` (o que se ganha, o que se perde, o que se mantém) | INJ `decided-by` → D | Daniel, ou a sessão pela D-294/D-325 com caminho de volta / desenho |

### (f) Do "como" ao trabalho: cenários, S&T e obstáculos

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **SCEN** | Cenário operacional, o use case | level (summary, user-goal, subfunction), primary_actor (Daniel, session, tool, torre, merge-queue, external), trigger (evento do contrato), preconditions, main_flow [{n, actor, action}], extensions [{at_step, condition, flow, kind: alternate ou failure}], minimal e success guarantees, nominal, state | `realizes` → INJ escolhida; `includes`/`extends` → SCEN | sessão / desenho; a VAL o executa |
| **ST** | Nó da árvore de estratégia e tática | level, strategy (→ NC ou texto mensurável com MEAS), tactic (→ INJ escolhida ou texto), owner_role (manager, domain-coordinator, lane) | `child-of` → ST; `assumes` → P com role necessary, parallel ou sufficiency; `decomposes-into` → WORK (folhas) | níveis 1–2: a sessão redige e Daniel valida (é o desdobramento da intenção); níveis 3+: o coordenador de domínio; folhas: as lanes / desenho; a ferramenta mede os nós na entrega |
| **OBST** | Obstáculo: a realidade que torna um passo necessário | statement | `blocks` → INJ ou ST; `overcome-by` → ST ou WORK | sessão, com Daniel / desenho |
| NEED (existe) | Necessidade sobre a solução | (existente) | `derives-from` → SCEN ou INJ escolhida (obrigatória); `serves` → NC | sessão / desenho; Daniel valida |
| REQ → … → VAL (existe) | O subsistema de engenharia (D-331) | — | VAL `executes` → SCEN | sessão / entrega |
| WORK (existe) | Unidade e PR | ganha `slices` → SCEN {steps} e `full_kit` (derivado) | `implements` → REQ | sessão / entrega |

### (g) Controle do fluxo: a restrição, o tambor, a corda e o pulmão

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **CONSTRAINT** | A restrição do fluxo | kind (physical, market, policy), where, step (identify, exploit, subordinate, elevate, broken), evidence | `limits` → NC; `held-by` → D ou chave de registro (restrição de política); `exploited-by`/`subordinated-by`/`elevated-by` → INJ ou WORK; `succeeded-by` → CONSTRAINT | a ferramenta (`flow-metrics --constraint`) propõe; a sessão de capacidade confirma / antes e contínuo |
| **POLICY** | A corda: a regra de admissão e claim (quantas frentes, quando abrir mais), hoje escrita à mão no AGENTS.md | a chave de registro e o porquê | `derived-from` → CONSTRAINT; `decided-by` → D | sessão desenha, D decide / desenho |
| **BUFFER** | O pulmão (tempo ou fila), com zonas e a cor por unidade derivada; ajuste dinâmico proposto pela ferramenta | kind (unit, program), size, zones, history | `protects` → CONSTRAINT ou programa | a sessão desenha; a ferramenta mede, colore e propõe o ajuste / desenho e entrega |

A gestão de pulmão alimenta (b): uma unidade em vermelho registra sua causa, e o Pareto dessas causas vira
evidência de UDE. No nível de programa, um pulmão único substitui os limites por PR, como no Critical Chain:

- um fever chart derivado mostra o consumo do pulmão contra o avanço;
- a checagem de **full kit** (todo o necessário pronto) roda antes do claim;
- os programas são admitidos pela capacidade do tambor.

### (h) Medidas da meta: throughput accounting nas unidades da Torre

- **T:** PRs mergeados por segundo, dentro das guardas de qualidade.
- **I:** trabalho em andamento mais os tokens presos em trabalho não mergeado.
- **OE:** tokens, cota e AWS por janela.
- **Derivadas:** T/OE, T/I e T por unidade da restrição.

São MEAS lidas pela ferramenta. Toda injeção escolhida declara o ΔT, ΔI e ΔOE previsto, nessa prioridade, e o
depois mede o realizado.

### (i) Laço de benefício

| Objeto | O que é | Quem / quando |
|---|---|---|
| Benefício (derivado) | O estado de cada NC (met, not-met, measuring, defined) contra baseline e alvo | ferramenta / depois e contínuo |
| UDE `state` | gone ou returned | ferramenta acusa, sessão confirma / depois |
| CASE `closed` | Previsto contra realizado, com os dis-benefícios | sessão / depois |
| CONSTRAINT `broken` → `succeeded-by` | A restrição mudou de lugar e começa nova volta | ferramenta propõe, sessão confirma / depois |
| LESSON (existe) | O que a lógica previu contra o que aconteceu; revisa premissas e a Goal Tree | sessão / depois; Daniel no veredito que muda a intenção |

## 3. Regras (metamodelo e checagens de grafo)

**Estado desejado e estado atual:**

1. Uma INT é coberta por um CSF.
2. Uma NC tem MEAS, alvo e baseline, e uma medida sem fonte não conforma.
3. Uma NC fora do alvo tem um UDE.
4. Um UDE viola uma NC e tem uma CAUSE.

**Problemas e revisão:**

5. A CRT não tem ciclo, e a causa central tem cobertura medida e um CONFLICT que a perpetua.
6. Uma RESERVATION aberta bloqueia a D. A revisão é de um revisor, nunca do autor.

**Soluções:**

7. Toda D de nível business tem `appraisal` com do-nothing e do-minimum, critérios vindos de NC, datados antes das
   notas, e sensibilidade.
8. Uma INJ escolhida:
   - declara ΔT/ΔI/ΔOE e `appetite`;
   - não tem ramo negativo aberto;
   - se for technology, nomeia a regra que substitui;
   - tem um SCEN user-goal nominal e um fora do nominal.
9. Uma premissa de alto raio sob uma INJ escolhida ou sob um ST tem um EXP, ou está confirmada.

**Business case:**

10. Um programa tem CASE antes da D que escolhe a INJ.
11. Todo ponto de revisão do CASE tem veredito, e "não justificado" abre uma D de parar ou ajustar.

**Plano (S&T):**

12. Todo ST tem premissa necessária e premissa de suficiência, uma MEAS e um dono.
13. Uma folha de ST tem WORK.
14. Uma P refutada reabre o nó.

**Necessidades e trabalho:**

15. Uma NEED deriva de um SCEN ou de uma INJ escolhida e serve a uma NC.
16. Uma WORK só recebe claim com full kit, e uma WORK em vermelho registra a causa.

**Controle do fluxo:**

17. Há uma CONSTRAINT ativa por NC de throughput, com evidência atual.
18. A POLICY de admissão deriva da CONSTRAINT ativa.

**O memorando a Daniel:**

19. Um memorando de desenho cobre as seis camadas de resistência:
    1. o problema;
    2. a direção da solução;
    3. que a solução resolve;
    4. os ramos negativos;
    5. os obstáculos;
    6. o comprometimento.

## 4. Implementação proposta (depois do sim de Daniel)

**Sistemas.** Um sistema por seção, modulares e de gestão, separados da engenharia. A engenharia (D-331) não é
reaberta: os novos sistemas entram no `measure` como sistemas próprios, cada um fechado a 100%.

| Sistema | Tipos |
|---|---|
| intent | INT, NC, NEED |
| reality | UDE, CAUSE, CONFLICT, RESERVATION |
| solution | INJ, EXP, CASE, SCEN |
| strategy | ST, OBST |
| flow | CONSTRAINT, POLICY, BUFFER |

**Onde moram os arquivos.** Todo objeto é um arquivo JSON por id, com contrato em `contracts/model/` e tipos gerados.
As pastas são `config/intent/`, `config/reality/`, `config/solution/`, `config/strategy/` e `config/flow/`.

**Fases.** Cada fase é uma PR pela fila, com plano de commits, testes e o modelo em 0 erros:

1. **Decisão e Goal Tree.** Uma D que substitui a D-347. NC (substitui o OBJ do v1) e o estado desejado e atual da
   Torre: CSF de T, I, OE e qualidade; NC com MEAS, alvo e baseline; UDE com evidência; gap derivado no `measure`.
   As NEED que hoje dizem objetivo (throughput, custo) viram NC, e as VAL delas passam a ser a leitura das NC.
2. **Problemas.** CAUSE, CONFLICT, RESERVATION e P com role; a cobertura da central; a checagem de ciclos e das
   reservas formais. Conteúdo: a CRT e o conflito central da Torre a partir do UDE de throughput, revisados por uma
   sessão revisora independente.
3. **Soluções.** INJ, EXP, CASE, SCEN, o `level`/`appraisal`/`change_matrix` da D, e as medidas T, I e OE.
   Conteúdo: as injeções sobre a causa central, a FRT, os ramos negativos, os experimentos, o CASE do programa e os
   SCEN da injeção escolhida.
4. **Estratégia.** ST e OBST, com as folhas ligadas às unidades da fila. Conteúdo: a S&T da intenção (níveis 1–2
   validados por Daniel) até as unidades dos três domínios.
5. **Controle do fluxo.** CONSTRAINT, POLICY e BUFFER. A corda de frentes sai do AGENTS.md para uma chave de
   registro derivada da restrição. Entram o full kit, as cores, o fever chart do programa e o Pareto das causas de
   vermelho como evidência de UDE.
6. **Vistas e experimento.**
   - O `scripts/model show` desenha a Goal Tree, a CRT, a nuvem, a FRT e a S&T como Mermaid gerado.
   - A checagem de completude do memorando cobre as seis camadas.
   - O experimento da premissa "uma sessão constrói árvores que sobrevivem à revisão" mede quantas reservas
     abertas o revisor acha por árvore.
   - O PROB/OBJ do v1 é removido.

**Quem passa a fazer o quê no fluxo, em ordem:**

1. **Antes:**
   - Daniel dá a intenção, aceita os CSF, pesos e alvos;
   - a ferramenta lê as medidas e propõe a restrição, e a sessão fixa os baselines e escreve os UDE;
   - o gerente abre o CASE `outline`.
2. **Desenho:**
   - a sessão constrói a CRT e a nuvem, um revisor levanta as reservas, e Daniel aceita a causa e o conflito
     centrais;
   - a sessão gera as injeções com do-nothing e do-minimum, a FRT, os ramos negativos e os experimentos;
   - a sessão fixa os critérios antes das notas, e a ferramenta pontua e faz a sensibilidade;
   - a D é registrada e o CASE vira `full`;
   - a sessão escreve os SCEN, a S&T (níveis 1–2 com Daniel), os OBST, as NEED e as unidades.
3. **Entrega:**
   - as lanes executam as folhas da S&T;
   - a ferramenta mede os pulmões, o full kit e as cores;
   - a VAL executa os SCEN;
   - nos pontos de revisão, o CASE recebe o veredito.
4. **Depois:**
   - a ferramenta deriva o benefício e o estado dos UDE e da restrição;
   - o CASE vira `closed` e a lição revisa as premissas;
   - a restrição quebrada abre a próxima volta.

## 5. Adiado, e por que não falta (critério: padrão de elite)

- **Valor monetário de T e retorno financeiro:** a Torre não vende. O T em unidades da meta é a própria meta, e
  entra se houver receita.
- **A camada de mercado do Viable Vision** (oferta irrecusável, vantagem competitiva decisiva de mercado): a Torre
  não compete por clientes. A estrutura S&T entra sem essa camada.
- **Agendamento slot a slot do tambor (DBR clássico):** a restrição da Torre é uma fila de eventos, não uma máquina
  agendável. Para esse caso, o estado da arte é o DBR simplificado com gestão de pulmão, e é ele que entra.
- **Reposição distribuída** (Isn't It Obvious): não há estoque distribuído. Entra a parte geral, o ajuste dinâmico
  do pulmão.
- **Camadas de resistência e matriz de mudança como objetos:** o buy-in é de uma pessoa. As camadas entram como
  checagem do memorando e a matriz como campo da D.
- **User story, JTBD/ODI, PRD e PR-FAQ como tipos:**
  - a história é só a gramática opcional da NEED;
  - do JTBD/ODI entram a gramática de resultado das NC e o peso dos CSF;
  - PRD e PR-FAQ são vistas geráveis do grafo, não fonte de verdade.

## 6. O que muda no que já existe

- **v1 (D-347, PROB e OBJ, commits 2 e 3 da #340):** substituído pela fase 1.
- **MEAS, P, D, WORK e LESSON:** reusados, com os campos novos ditos acima.
- **O subsistema de requisitos em diante:** não muda, salvo três ligações novas:
  - NEED `derives-from` → SCEN ou INJ;
  - VAL `executes` → SCEN;
  - WORK `slices` → SCEN.
- **A regra de frentes do AGENTS.md:** vira a POLICY derivada da restrição (fase 5).

## 7. Limites das pesquisas

- Os textos pagos não foram relidos, e as cláusulas vêm de sumários públicos e de conhecimento prévio: 15288, 29148,
  NRM, BABOK, 21502, os livros de Goldratt, Dettmer e o Handbook de Cox e Schleier.
- As definições TOCICO vêm de um espelho e devem ser conferidas no dicionário oficial antes de citação formal.
- O artigo "Strategy and Tactics" de Goldratt estava fora da rede da sessão.
- Não há fonte revisada sobre árvores TOC construídas por agentes. Por isso existe o experimento da fase 6.
