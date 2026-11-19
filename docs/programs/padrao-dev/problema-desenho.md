# PADRAO-DEV — o que vem antes dos requisitos: desenho v2

Pedido de Daniel (19/11 ~13:11 BRT, pela Torre), com o retorno sobre o desenho v1 (19/11 ~13:22 BRT):

- uma solução completa, no nível do padrão, e não o mínimo;
- separação explícita entre estado atual, estado desejado, problemas do gap e soluções;
- quem cria cada objeto e quando;
- a Teoria das Restrições pesquisada e pesada.

Pesquisas: [problema-pesquisa.md](problema-pesquisa.md) (15288, 29148, INCOSE NRM, BABOK, ISO 21502) e
[problema-pesquisa-toc.md](problema-pesquisa-toc.md) (os processos de pensamento de Goldratt e o Logical Thinking
Process de Dettmer). Este desenho é para levar a Daniel antes de implementar. A PR #340 fica em rascunho, e o código
de PROB/OBJ já empurrado nela será substituído por este desenho.

## 0. Critério

- Nível de esforço adequado e solução completa. Cada elemento entra porque um padrão de elite o exige, e cada adiado
  diz por que não falta.
- Quando um objeto que já existe no modelo é a mesma coisa que um da referência, ele é reusado, para que não existam
  duas verdades: medida (MEAS), premissa (P), decisão (D), unidade e trabalho (WORK), lição (LESSON).

## 1. O que as duas pesquisas dizem juntas

A Teoria das Restrições (TOC) responde três perguntas:

- **O que mudar?** A árvore da realidade atual (CRT) e a nuvem do conflito central.
- **Para o que mudar?** As injeções e a árvore da realidade futura (FRT), com os ramos negativos podados.
- **Como causar a mudança?** A árvore de pré-requisitos e a de transição.

Dettmer põe a **Goal Tree** primeiro: meta, fatores críticos de sucesso e condições necessárias. Um efeito indesejado
(UDE) é, por definição (TOCICO), uma condição necessária que hoje não se cumpre. Assim, o **gap é a Goal Tree contra a
realidade atual**.

As duas fontes se completam:

| A TOC é mais forte em | Os padrões são mais fortes em |
|---|---|
| a lógica causal do sintoma à causa central, verificada (Categories of Legitimate Reservation) | medida, baseline e alvo |
| o conflito que explica por que o problema persiste | necessidade separada do requisito |
| a prova lógica da solução antes de agir (FRT) | alternativas e decisão formal |
| o risco como ramo causal | experimento empírico |
| os obstáculos explícitos | realização de benefício medida |

O desenho usa as duas: a lógica da TOC com as medidas dos padrões.

## 2. O modelo, por seções

Siglas de quem cria:

- **Daniel**: o dono; decide e aceita;
- **sessão**: um agente que analisa e propõe;
- **ferramenta**: deriva sozinha das medidas e dos registros.

Momentos:

- **antes**: antes do programa;
- **desenho**: o desenho do programa;
- **entrega**: durante a entrega;
- **depois**: depois da entrega.

### (a) Estado desejado: a Goal Tree com medidas

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **INT** (existe) | A intenção e a meta do sistema (SEMENTE §3 e §6); fronteira de cima | statement, owner, source | — | Daniel / antes |
| **NC** (novo) | Fator crítico de sucesso (`level: csf`, 3 a 5 por meta) ou condição necessária (`level: nc`) | statement, level, `target` {comparator, value ou registry key, by opcional}, `baseline` {value, date, source} | `necessary-for` → INT ou NC; `measured-by` → MEAS (obrigatória) | a sessão propõe e Daniel aceita os CSF e os alvos / antes; o baseline é fixado pela sessão a partir da leitura da ferramenta |
| **MEAS** (existe) | A medida (ISO 15939): fonte, função, consumidor | (existente) | — | a sessão define, a ferramenta lê / antes |

Uma Goal Tree sem medida não é falsificável, e uma medida sem Goal Tree perde a lógica de necessidade. Por isso cada
NC exige uma MEAS e um alvo.

### (b) Estado atual

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **Leitura** (derivada) | O valor atual de cada MEAS | value, at | — | ferramenta / contínuo (o que `scripts/model measure` já faz) |
| **UDE** (novo) | Efeito indesejado observado, factual e no presente | statement, `evidence` [leituras, incidentes, fricções, comandos], magnitude, state (observed, gone, returned) | `violates` → NC (obrigatória: um UDE sem condição violada não é UDE) | a ferramenta acusa uma NC fora do alvo sem UDE; a sessão escreve o UDE / antes e entrega |

### (c) Gap

| Objeto | O que é | Quem / quando |
|---|---|---|
| **Gap** (derivado, nunca escrito) | Por NC: alvo contra leitura atual contra baseline, com distância e tendência | ferramenta / contínuo; `scripts/model show NC-…` e o sistema `intent` no `measure` |

### (d) Problemas: por que o gap existe e por que persiste

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **CAUSE** (novo) | Entidade da CRT: intermediária, raiz ou central (`kind: intermediate, root, core`) | statement, kind, `clr` {verdict, by} | `causes` → CAUSE ou UDE (com `and_group` para a suficiência conjunta) | a sessão constrói; a ferramenta calcula a cobertura (a fração dos UDE que a central alcança) e acusa ciclos / desenho; Daniel aceita a causa central |
| **CONFLICT** (novo) | A nuvem: objetivo A, necessidades B e C, pré-requisitos D e D′ em conflito | a, b, c, d, d_prime | `objective-is` → NC; `perpetuates` → CAUSE central; `assumes` → P (as premissas sob as setas) | a sessão escreve (pela CRT ou pelo método das três nuvens); Daniel revê / desenho |
| **P** (existe) | Premissa sob uma seta da nuvem ou da CRT | (existente: estados to-validate, confirmed, refuted) | — | sessão / desenho; um EXP a confirma ou a refuta |

O conflito é a razão de o problema persistir. Sem ele, a injeção é um palpite, e uma causa central sem cobertura medida
também é um palpite.

### (e) Soluções: candidatas, prova lógica, prova empírica, escolha

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **INJ** (novo) | Injeção, a solução candidata. Várias por problema, uma delas "não fazer" | statement (a condição futura), kind (policy, mechanism, measure), `effects` [o efeito desejado, cada um invertendo um UDE], `branches` [ramo negativo: efeito, cadeia, severidade, `trimmed_by` INJ ou `accepted_by` D], state (candidate, chosen, rejected) | `addresses` → CAUSE ou CONFLICT; `invalidates` → P; `inverts` → UDE (pelos efeitos); `decided-by` → D | a sessão gera as candidatas e a FRT; a ferramenta acusa um UDE sem efeito que o inverta e um ramo sem poda nem aceite / desenho |
| **EXP** (novo) | Experimento, protótipo ou prova de conceito de uma premissa ou injeção | hypothesis, method, `criterion` (sobre uma MEAS: comparator, value), result, state (planned, running, confirmed, refuted) | `tests` → P ou INJ; `measured-by` → MEAS | a sessão desenha e roda; a ferramenta lê o resultado / desenho e entrega |
| **D** (existe) | A escolha: as injeções escolhidas e as rejeitadas, com o porquê, os ramos residuais aceitos e o caminho de volta | (registro de decisão) | INJ `decided-by` → D | Daniel, ou a sessão pela D-294/D-325 com caminho de volta / desenho |

A FRT dá a prova lógica, o EXP a prova empírica e o ramo negativo o risco. Nenhuma das fontes sozinha cobre os três.

### (f) Transição: da solução escolhida às necessidades e ao trabalho

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **OBST** (novo) | Obstáculo: por que a injeção escolhida não acontece hoje | statement | `blocks` → INJ; `overcome-by` → WORK (a unidade que o vence, o objetivo intermediário) | sessão, com contribuição de Daniel / desenho |
| **Conceito** | Como a solução escolhida opera: o `solucao.md` do programa | — | INJ escolhida `source` → o documento | sessão / desenho |
| **NEED** (existe) | Necessidade sobre a solução escolhida | (existente) | `derives-from` → INJ escolhida (obrigatória); `serves` → NC | sessão / desenho; Daniel valida |
| **REQ → … → VAL** (existe) | O subsistema de engenharia, fechado pela D-331 | — | — | sessão / entrega |
| **WORK** (existe) | Unidade e PR: as ações da árvore de transição | (existente) | `overcomes` → OBST; `implements` → REQ | sessão / entrega |

### (g) Laço de benefício: o gap fechou?

| Objeto | O que é | Quem / quando |
|---|---|---|
| **Benefício** (derivado) | O estado de cada NC, derivado da sua medida contra o alvo (met, not-met, measuring, defined); com o baseline, diz se o gap fechou | ferramenta / depois |
| **UDE** `state` | gone quando a leitura volta ao alvo; returned se volta a violar | a ferramenta acusa a mudança; a sessão confirma / depois |
| **LESSON** (existe) | Retrospectiva: o que a lógica previu contra o que aconteceu (premissa refutada, ramo não visto, UDE novo) | sessão / depois; volta à Goal Tree |

O laço fecha assim:

- a VER prova o REQ;
- a VAL prova a NEED;
- o benefício, que é a leitura da NC, prova a Goal Tree.

Um gap que não fecha volta a ser um UDE, e começa outra volta do ciclo de melhoria contínua (POOGI).

## 3. Regras (metamodelo e checagem)

Cada regra é uma cobertura (`covered_by`) ou uma ligação obrigatória (`must_link`) do metamodelo, ou uma checagem de
grafo da ferramenta:

1. Uma INT é coberta por uma NC.
2. Uma NC tem MEAS e alvo, e fica não conforme enquanto a medida não tem fonte.
3. Uma NC fora do alvo tem um UDE que a viola.
4. Um UDE tem uma causa (CAUSE) que o explica.
5. A causa central tem uma INJ que a enfrenta.
6. Toda INJ escolhida tem uma D e não tem ramo negativo aberto.
7. Uma premissa de alto raio sob uma INJ escolhida tem um EXP, ou é confirmada.
8. Uma NEED deriva de uma INJ escolhida e serve a uma NC.
9. Um OBST tem a unidade que o vence.
10. A CRT não tem ciclo, e toda causa central tem cobertura.

## 4. O que a sessão, a ferramenta e Daniel fazem, em ordem

1. **Antes do programa:**
   - Daniel declara ou confirma a intenção (INT);
   - a sessão propõe a Goal Tree (NC com MEAS e alvo), e Daniel aceita os CSF e os alvos;
   - a ferramenta lê as medidas, e a sessão fixa os baselines;
   - a ferramenta mostra o gap e acusa as NC fora do alvo, e a sessão escreve os UDE.
2. **Desenho:**
   - a sessão constrói a CRT até a causa central e a nuvem com as premissas, e Daniel aceita a causa central;
   - a sessão gera as injeções (com "não fazer"), a FRT e os ramos negativos;
   - a sessão desenha os experimentos das premissas de alto raio;
   - Daniel, ou a sessão pela D-294, escolhe numa D;
   - a sessão escreve os obstáculos, as unidades que os vencem e as NEED.
3. **Entrega:**
   - REQ → arquitetura → construção → VER → VAL, como hoje;
   - os experimentos rodam;
   - a ferramenta lê as medidas continuamente.
4. **Depois:**
   - a ferramenta deriva o benefício (o estado das NC) e o estado dos UDE;
   - a sessão escreve a lição;
   - Daniel aceita o veredito que muda a intenção.

## 5. Adiado, e por que não falta

- **Throughput accounting (T, I, OE) como medidas obrigatórias:** são do domínio financeiro. A Goal Tree aceita
  qualquer MEAS, e a meta da Torre não é financeira.
- **A árvore Strategy & Tactics como tipo próprio:** NC, INJ e WORK representam um programa de até dois níveis. Entra
  quando um programa tiver mais níveis com donos distintos.
- **As categorias de reserva (CLR) como objetos:** um veredito por entidade e por seta (`clr`) carrega o escrutínio.
  Viram objeto quando houver revisão adversarial frequente.
- **Business case monetário:** a Torre não decide por retorno financeiro. O gap medido e os ramos negativos fazem
  esse papel.

## 6. O que muda no que já existe

- O v1 (PROB e OBJ, D-347 e os commits 2 e 3 da #340) é substituído:
  - o PROB vira UDE, com a CAUSE ao lado;
  - o OBJ vira NC;
  - D-347 é substituída por uma nova decisão quando Daniel aprovar este desenho.
- As NEED de hoje que dizem um objetivo, como NEED-throughput e NEED-cost, viram NC. Ficam como NEED só as
  necessidades sobre uma solução escolhida.
- As VAL que medem esses objetivos passam a ser a leitura das NC (benefício). As VAL que medem uma solução continuam
  VAL.
