# PADRAO-DEV — o que vem antes dos requisitos: desenho v4 (progressivo)

Para Daniel decidir antes de qualquer implementação. A PR #340 fica em rascunho.

## Histórico e fontes

**Retornos de Daniel (19/11):**

- **v1:** a solução deve ser completa, com separação explícita, quem cria e quando, e a TOC.
- **v2:** ele pediu a TOC completa, a reavaliação dos adiados e uma implementação completa.
- **v3:** o "use case" era o business case, e o cenário de uso sai. Ele pediu saltos progressivos, cada um
  completo, com o critério que diz quando cada salto passa a valer.

**Pesquisas:**

- [problema-pesquisa.md](problema-pesquisa.md): os padrões;
- [problema-pesquisa-toc.md](problema-pesquisa-toc.md) e
  [problema-pesquisa-toc-completa.md](problema-pesquisa-toc-completa.md): a TOC;
- [problema-pesquisa-casos.md](problema-pesquisa-casos.md): o business case e os agentes.

**Critério:** progressivo não é incompleto. Cada salto responde inteiro às perguntas que assume, fecha a 100% no
padrão e não deixa ponta solta para o salto seguinte. O salto seguinte só entra quando seu critério se cumpre, e esse
critério é medido, não opinado.

**Quem cria:** **Daniel** decide e aceita; **sessão** analisa e propõe; **ferramenta** deriva sem mão.

**Quando:** **antes** do programa; **desenho**; **entrega**; **depois**; **contínuo**.

## 1. Salto 1: o núcleo das cinco perguntas

As perguntas são: onde queremos estar, onde estamos, qual a distância, por que ela existe e persiste, e o que fazer
e por quê. Os objetos novos são cinco: NC, UDE, CAUSE, CONFLICT e INJ. Os demais são derivados ou já existem.

### (a) Estado desejado, medido

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| INT (existe) | A intenção e a meta (SEMENTE) | — | — | Daniel / antes |
| **NC** | Fator crítico de sucesso (`level: csf`) ou condição necessária (`level: nc`) | statement (direção + medida + objeto), level, `target` {comparator, valor ou chave de registro, by?}, `baseline` {value, date, source} | `necessary-for` → INT ou NC; `measured-by` → MEAS | a sessão redige; Daniel aceita os CSF e os alvos / antes; a sessão fixa o baseline pela leitura da ferramenta |
| MEAS (existe) | A medida e sua fonte | — | — | a sessão define; a ferramenta lê |

### (b) Estado atual

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| Leitura (derivada) | Valor atual de cada MEAS | value, at | — | ferramenta / contínuo |
| **UDE** | Efeito indesejado, factual e presente | statement, `evidence` [leituras, incidentes, fricções], state (observed, gone, returned) | `violates` → NC (obrigatória) | a ferramenta acusa a NC fora do alvo sem UDE; a sessão escreve / antes e contínuo |

### (c) Gap (derivado, nunca escrito)

Por NC, entram o alvo, a leitura atual, o baseline, a distância e a tendência. Quem calcula é a ferramenta, a cada
leitura, e o resultado aparece no `scripts/model measure` e no `show`.

### (d) Problemas: por que o gap existe e por que persiste

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **CAUSE** | Entidade da árvore da realidade atual (CRT): intermediária, raiz ou central | statement, kind (intermediate, root, core), `and_group` | `causes` → CAUSE ou UDE | a sessão constrói; a ferramenta calcula a cobertura da central e acusa ciclos / desenho; Daniel aceita a central |
| **CONFLICT** | A nuvem que explica por que a causa central persiste: objetivo, duas necessidades, dois pré-requisitos em conflito | a, b, c, d, d_prime | `objective-is` → NC; `perpetuates` → CAUSE central; `assumes` → P (as premissas sob as setas) | sessão / desenho; Daniel aceita |
| P (existe) | A premissa sob uma seta | (existente) | — | sessão |

### (e) Soluções, com a decisão

| Objeto | O que é | Campos | Ligações | Quem / quando |
|---|---|---|---|---|
| **INJ** | Injeção, a solução candidata. Sempre há uma `do-nothing` e uma `do-minimum` entre as candidatas | statement, kind (policy, mechanism, measure), `effects` [efeito desejado, cada um invertendo um UDE], `branches` [ramo negativo: efeito, severidade, `trimmed_by` ou aceito na D], `cost` {tokens, usd, wall} estimado, state (candidate, chosen, rejected) | `addresses` → CAUSE central ou CONFLICT; `invalidates` → P; `inverts` → UDE; `decided-by` → D | sessão / desenho |
| D (existe) | A escolha | ganha `appraisal`: critérios vindos das NC, fixados com data antes das notas; opções → INJ (com do-nothing e do-minimum); nota por critério com evidência (MEAS ou P); custo por opção; por que a escolhida; caminho de volta | INJ `decided-by` → D | Daniel, ou a sessão pela D-294/D-325 / desenho |
| NEED (existe) | Necessidade sobre a solução escolhida | (existente) | `derives-from` → INJ escolhida (obrigatória); `serves` → NC | sessão / desenho; Daniel valida |
| REQ → … → VAL (existe) | O subsistema de engenharia (D-331) | — | — | sessão / entrega |

### Benefício: o laço do salto 1

O benefício é derivado pela ferramenta, depois da entrega e de forma contínua. É o estado de cada NC (met, not-met,
measuring) contra o baseline e o alvo. Junto, o UDE passa a gone ou returned, e a LESSON (que já existe) compara o
previsto pela injeção com o que aconteceu. Uma NC que continua not-met volta a ser UDE, e o ciclo recomeça.

### Regras do salto 1 (metamodelo e checagens da ferramenta)

1. Uma INT é coberta por um CSF.
2. Uma NC tem MEAS, alvo e baseline. Uma medida sem fonte não conforma.
3. Uma NC fora do alvo tem um UDE.
4. Um UDE viola uma NC e tem uma CAUSE.
5. A CRT não tem ciclo. A causa central tem cobertura medida e um CONFLICT.
6. A causa central tem INJ candidatas, entre elas do-nothing e do-minimum.
7. Uma INJ escolhida tem uma D com `appraisal` e não tem ramo negativo aberto.
8. Os critérios do `appraisal` vêm de NC e têm data anterior à das notas.
9. Uma NEED deriva de uma INJ escolhida e serve a uma NC.

### O que o salto 1 faz no que já existe

- O v1 (D-347, PROB/OBJ, commits 2 e 3 da #340) é substituído:
  - uma nova D substitui a D-347;
  - o OBJ vira NC;
  - o PROB vira UDE.
- As NEED que hoje dizem um objetivo (throughput, custo, qualidade) viram NC. As VAL delas passam a ser a leitura
  das NC.
- Conteúdo: a Goal Tree medida da Torre, os UDE atuais, a CRT e o conflito do maior gap (throughput: cerca de 33
  PRs por dia contra 1.000 do degrau 1), as injeções e a decisão.
- Um sistema de gestão só, `problem`, separado da engenharia, com os tipos NC, UDE, CAUSE, CONFLICT e INJ. A
  engenharia não é reaberta.
- O tamanho é uma PR em quatro ou cinco commits: decisão, metamodelo e contratos com testes, conteúdo, migração das
  NEED.

## 2. Business case: entra o núcleo agora, o objeto depois

A intuição de Daniel está certa quanto ao objeto inteiro. O que o padrão exige já no primeiro salto é o **núcleo**
do business case:

- a comparação de opções, sempre com "não fazer" e "fazer o mínimo";
- critérios que vêm dos objetivos;
- o custo de cada opção;
- o porquê da escolha.

Isso está no salto 1 como `appraisal` da D e `cost` da INJ, na forma mais enxuta que atende ao padrão (ISO 21502,
PRINCE2, Five Case Model). O CASE completo fica para o salto 4:

- as cinco dimensões;
- as etapas outline, full, maintained e closed;
- os vereditos de justificativa contínua.

O CASE completo depende de duas coisas que ainda não estão no modelo: as medidas de throughput accounting (a
dimensão econômica) e programas longos com pontos de revisão (a justificativa contínua).

## 3. Os saltos seguintes, em ordem

| Salto | O que entra | Por que nessa ordem | Quando passa a valer (critério medido) |
|---|---|---|---|
| **2. Prova da lógica** | RESERVATION (as categorias de reserva legítima levantadas por uma sessão revisora, nunca o autor; uma reserva aberta bloqueia a D) e EXP (experimento sobre uma premissa ou uma injeção, com critério sobre uma MEAS) | Corrige o ponto fraco do salto 1: a CRT e a injeção feitas por uma sessão são lógica não revisada e prova só lógica. Não há fonte revisada sobre árvores TOC feitas por agentes | quando o salto 1 fechar a primeira volta (uma D tomada e lida depois), ou antes disso, se uma INJ escolhida depender de uma P de alto raio não confirmada |
| **3. Controle do fluxo** | CONSTRAINT (física, de mercado ou de política, com o passo dos cinco em que está e a sucessora), POLICY (a corda: a regra de frentes do AGENTS.md vira uma chave de registro derivada da restrição), BUFFER (pulmão por unidade e por programa, com cores e ajuste dinâmico), full kit antes do claim, e as medidas T, I e OE | O gap de throughput é o maior da Torre, e a TOC diz que ele se fecha na restrição, não no resto. O salto 1 já terá dito qual é a causa central; este salto a controla | quando a NC de throughput ficar not-met por duas leituras seguidas com a mesma restrição apontada pelo `flow-metrics --constraint` |
| **4. Business case e throughput accounting** | O CASE completo de cinco dimensões por programa, e a regra de decisão ΔT > ΔI > ΔOE em toda INJ | Precisa das medidas T, I e OE do salto 3 e de um programa com pontos de revisão | quando duas ou mais injeções competirem pela mesma cota ou pelo mesmo teto de AWS, ou quando um programa passar do seu apetite de tokens |
| **5. Estratégia e tática** | ST (os cinco elementos por nó, com dono por nível) e OBST; as folhas ligadas às unidades | É o "como" em vários níveis. Vale quando o plano de um programa não se lê mais na cadeia INJ → NEED → WORK | quando uma injeção escolhida exigir unidades em dois ou mais domínios, ou mais de dois níveis com donos distintos para o mesmo objetivo |
| **Roteiro futuro** | SCEN (cenário de uso, Use-Case 2.0), a camada de mercado do Viable Vision, o valor monetário de T, o DBR slot a slot | Fora do pedido atual, ou sem aplicação na Torre hoje | o SCEN, quando uma solução tiver atores externos; os outros, se a Torre passar a vender ou a agendar uma máquina |

Em cada salto:

- uma decisão;
- os tipos e as regras;
- o conteúdo real da Torre;
- o fechamento a 100% no `measure`;
- o aviso à Torre e a Daniel.

## 4. Quem cria o quê e quando, no salto 1

1. **Antes:** Daniel dá a intenção e aceita os CSF e os alvos. A ferramenta lê as medidas, e a sessão fixa os
   baselines e escreve os UDE.
2. **Desenho:**
   - a sessão constrói a CRT e o conflito, e Daniel aceita a causa central;
   - a sessão escreve as injeções (com do-nothing e do-minimum) e os ramos negativos;
   - a sessão fixa os critérios, dá as notas e registra a D, que Daniel toma ou a sessão toma pela D-294;
   - a sessão escreve as NEED a partir da injeção escolhida.
3. **Entrega:** o subsistema de engenharia, como hoje.
4. **Depois:** a ferramenta deriva o benefício e o estado dos UDE. A sessão escreve a lição. Daniel aceita o veredito
   que muda a intenção.
