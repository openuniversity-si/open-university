# PADRAO-DEV — o que vem antes dos requisitos: auditoria e desenho

Pedido (Daniel, 19/11 ~13:11 BRT, pela Torre): descobrir o que vem antes dos requisitos e se o ciclo requisitos →
arquitetura → construção → verificação → validação → conformidade é parte de um sistema maior. É uma unidade nova e
não reabre a conclusão da engenharia (D-331). A pesquisa está em [problema-pesquisa.md](problema-pesquisa.md).

## 1. O que a pesquisa diz (resumo)

Pelo consenso das fontes (ISO/IEC/IEEE 15288:2023 6.4.1 e 6.4.2, 29148:2018, o INCOSE Needs and Requirements Manual
§4.3, o BABOK v3 cap. 6 e 8, a ISO 21502:2020 §7.3), a ordem é esta:

1. Primeiro, um **problema ou oportunidade**: a situação a mudar, com o estado atual e sua evidência.
2. Depois, **objetivos medidos**: métrica, baseline e alvo, de onde sai o gap.
3. Em seguida, as soluções candidatas, a escolha de uma delas e o conceito.
4. Só então vêm as **necessidades** e, delas, os requisitos.

O laço fecha na **medida de benefício**: o objetivo é medido de novo depois da entrega, e o portfólio decide
encerrar, iterar ou parar. A validação prova a necessidade; o benefício prova o objetivo e, por ele, o problema. O
limite de fora é a intenção da organização: para a Torre, a da SEMENTE, que só Daniel valida.

## 2. Auditoria do modelo (main 9da8db0)

| Camada de referência | O que o modelo tem | Achado |
|---|---|---|
| Intenção e estratégia | 6 INT (intenção v1, degraus 1 a 3, limites, padrão) | Existe e está certa como camada de fora. |
| Problema ou oportunidade, estado atual | nada | **Falta.** Não há objeto com a situação a mudar nem com sua evidência. |
| Objetivo medido (baseline, alvo, gap) | INT-ladder-* dizem o alvo em texto; VAL têm só o limiar | **Falta.** Nenhum baseline, logo nenhum gap; o alvo do degrau não é um objeto medido. |
| Soluções candidatas e escolha | decisões D-NNN, premissas P-NN | Existe, sem ligação explícita ao objetivo. |
| Conceito (ConOps/OpsCon) | documentos de programa (`solucao.md`) | Existe como texto; fica fora do mínimo. |
| Necessidade | 6 NEED, todas `proposed`, cada uma refina uma INT | **Mistura dois níveis.** NEED-throughput e NEED-cost são objetivos medidos, não necessidades sobre uma solução. |
| Requisito → … → validação → conformidade | 44 REQ, 23 ARC, 283 TEST, 11 VAL… | Fechado (D-331). |
| Benefício (medida depois da entrega) | VAL validam NEED com a mesma medida | **Falta como nível próprio.** A validação faz as duas vezes. |

## 3. Desenho (o caminho mais barato)

O sistema `intent` já declara os processos de análise de negócio ou missão e de necessidades dos stakeholders
(15288/12207). Ele recebe os dois níveis que faltam, sem sistema novo e sem mexer na engenharia.

- **PROB-*** (`config/intent/PROB-*.json`): problema, oportunidade ou ameaça. Campos `statement`, `kind`
  (problem, opportunity ou threat), `current` (o estado atual em texto e a `evidence`, os comandos ou caminhos que o
  mostram), `refines` (as INT que ele concretiza), `owner`, `state` (open, addressed, closed, reopened) e `source`.
- **OBJ-*** (`config/intent/OBJ-*.json`): objetivo medido. Campos:
  - `statement`;
  - `addresses`, os PROB que ele resolve;
  - `measure`, da mesma forma e dos mesmos tipos de medida da VAL, lido pela mesma função `measured`;
  - `comparator`, e `threshold` ou `threshold_key` (o alvo);
  - `baseline`, o valor, a data e a fonte da medida antes;
  - `by`, a data do alvo;
  - `decided_by`, as D-NNN que escolheram a solução.

  O estado é derivado da medida, como o da VAL: defined, measuring, met ou not-met. É a leitura de benefício: o laço
  fecha sem um tipo BENEFIT à parte. O gap é derivado (alvo menos medida atual), nunca guardado.
- **NEED** ganha `derives_from`: os OBJ de que nasce.
- **Ligações:**
  - `refines` passa a valer também para PROB → INT;
  - `addresses` (nova) liga OBJ → PROB;
  - `derives-from` passa a valer também para NEED → OBJ;
  - `decided-by` passa a valer também para OBJ → D.
- **Regras (metamodelo, sem código novo de checagem):**
  - INT é coberta por um PROB que a refina (antes, por uma NEED);
  - PROB é coberto por um OBJ que o enfrenta e tem `refines` obrigatório;
  - OBJ é coberto por uma NEED que deriva dele, tem `addresses` obrigatório e não pode ficar em `defined` (medida
    sem fonte);
  - NEED passa a ter `derives-from` obrigatório.

Fora do mínimo, até uma medida pedir:

- causa raiz como objeto (fica no texto do PROB);
- opções e experimentos como objetos (ficam nas decisões D-NNN e nas premissas P-NN);
- conceito formal;
- hierarquia MOE/MOP/TPM (os MOP e TPM já são REQ verificáveis);
- business case monetário;
- gestão formal de portfólio.

Quem sabe ler o modelo (humano ou agente) passa a andar do problema até o teste, e de volta: a VAL prova a NEED, e o
estado do OBJ, medido depois da entrega, prova o PROB.

## 4. O conteúdo

Cada INT ganha o problema que a concretiza, e cada NEED o objetivo de que deriva. Os baselines são as medidas
registradas no repositório na data do desenho. Um objetivo que não for atingido fica `not-met`: é uma leitura
honesta de benefício, não uma falha do modelo.
