# Método de gestão: programa, projeto, processo, operação

Decidido por Daniel em 02/11/2026 e registrado aqui em 03/11/2026. Este documento é o padrão de gestão do motor. Onde
ele diverge das versões antigas do Padrão (`docs/padrao/v7/`, `docs/padrao/v8/program.md`, superadas por `VER-v9` em
`config/standard/rules/`, D-317) ou da regra de fluxo de unidade do AGENTS.md (D-077), vale este documento. O
`structure check` já não cobra a regra de intake e pesquisa (D-292).
A pesquisa da unidade MGMT-METHOD (a antiga PR #1066 no GitHub, hoje a
[PR #3 no Origin](https://cursor.com/codebase/openuniversity-si/open-university/pull/3), branch `arq/gestao`) fica
como referência de literatura. O plano dela foi superado por este documento e a PR não será mergeada.

## 1. Os quatro níveis

| Nível | O que é | Contém | Gestão | Encerra quando |
|---|---|---|---|---|
| Programa | Um conjunto de projetos que leva um benefício ao ideal | Projetos | Melhoria (PDCA) | O benefício medido chega à meta: um número com alvo e métricas de guarda, nenhuma guarda piora |
| Projeto | Um resultado com começo e fim | Fases; cada fase realiza processos | Melhoria (PDCA) | O resultado existe ou não existe: prova binária |
| Processo | Uma unidade coesa que leva algo da versão 1 à versão 2 | Fases próprias, onde as operações acontecem | Rotina (SDCA) | A unidade foi entregue inteira e coesa, nunca pela metade |
| Operação | O ato | Passos | Rotina (SDCA) | O ato foi feito e registrado |

Exemplo: uma PR é um conjunto de operações; dentro de cada operação há passos.

Acima do programa fica o portfólio. Cada fase de capacidade do motor (1.000, 10.000 e 100.000 PRs por dia, conforme
`docs/SEMENTE.md` §3) abre um portfólio, dividido em programas.

A literatura não oferece quatro níveis num eixo único (PMI, ITIL, TOGAF e SAFe, ver a pesquisa da PR #3). Por isso o
nível não é só posição numa hierarquia: cada item de trabalho declara a sua natureza (o nível), o seu critério de
encerramento e o seu dono.

## 2. Programa e projeto: gestão de melhoria (PDCA)

Os dois seguem o mesmo caminho longo e diferem só na prova de encerramento:

1. **Avaliação.** O que se quer e qual sistema ideal falhou.
2. **Pesquisa.** O que o mundo já sabe (seção 5).
3. **Análise.** O estado atual medido e as causas.
4. **Solução.** Uma escolha só, entre alternativas. Cada alternativa traz custo, alcance e requisitos. A escolhida é
   declarada a solução corrente. Ela pode ser revista se a verificação mostrar que não leva aonde a avaliação pediu.
5. **Fases.** Nascem só depois da escolha da solução. Uma fase é uma unidade de progresso dentro da solução escolhida,
   nunca uma solução.
6. **Verificação** ao fim de cada fase e do nível.
7. **Retrospectiva** de cada fase e uma do nível inteiro.

Cada fase tem quatro passos:

- **Auditoria técnica.** Olha o código e os fatos daquela fase. Não repete a avaliação nem a análise.
- **Planejamento.**
- **Execução.**
- **Verificação.** Confere se a fase entregou o que prometeu. Verificar não é medir: medir dá o número; verificar
  diz se a promessa foi cumprida.

## 3. Processo e operação: gestão de rotina (SDCA)

Processo e operação seguem um padrão curto de execução. Intake, pesquisa e análise de causa raiz nunca são exigidos
de toda unidade de trabalho nem de toda PR.

O processo tem:

- **Preparação.** O checkout inicial, o gate inicial e a preparação são fundamentais e vêm primeiro.
- **Auditoria do processo.** Um olhar local e com evidência sobre o código real: arquivos, dependências, ciclos,
  arquivos compartilhados, literais e strings mágicas, o que pertence a quem. Não é pesquisa e não é uma cadeia de
  porquês.
- **Planejamento do processo.** As operações como um grafo, com o caminho crítico, a preparação que remove a restrição
  e quem faz o quê.
- **Execução** das operações.
- **Retrospectiva.**

## 4. Um nome só: retrospectiva

O passo de revisão se chama retrospectiva em todos os níveis, com o mesmo significado: o que aconteceu, o que se
aprendeu e o que muda no padrão. Não existe um segundo nome (por exemplo "padronização") para o mesmo ato.

## 5. Pesquisa: o estado da arte é o piso

O padrão absorve o que o mundo já sabe antes de executar. Experimento só para o que só A Torre pode responder.
A escada é informação útil, depois conhecimento útil, depois inteligência útil.

Contexto: intenção, padrão e execução (antes semente, motor e programa). A intenção procura o melhor padrão, a execução
o testa, e os dois se alimentam. A distância entre o que a intenção e a inteligência disponível permitiam e o que o
padrão entregou é o defeito do padrão naquele ciclo.
A intenção, o ciclo e a trava da intenção estão na [semente](../SEMENTE.md).

## 6. Fluxo e métrica

- **Toda parada no fluxo é um incidente.** O dono só é consultado sobre login, credencial, dinheiro ou outras pessoas.
  O resto é feito e reportado (AGENTS.md, "Act, don't ask").
- **A métrica é a vazão do sistema:** entregas terminadas por unidade de tempo, no sistema inteiro. A latência de uma
  unidade isolada não é a métrica.

## 7. No motor de hoje

Os itens abaixo são instrumentos do nível mais baixo deste motor, as operações e os passos. Não são regras gerais do
método e podem mudar sem mudar o método (fluxo vivo no GitHub/AWS desde D-314):

- a PR em rascunho contra `main` como primeiro ato;
- o gate `tower/gate` (`scripts/verify-commit`) e `web` no head exato e no commit da merge queue;
- `scripts/commit-check` e `scripts/structure-check`, com o plano de commits e o trailer `Plan: N`;
- `scripts/model check` e `scripts/model measure` sobre o modelo de engenharia (`VER-v9`);
- a merge queue do GitHub e a campainha de deploy AWS (`.github/workflows/deploy-doorbell.yml`, `scripts/deploy status`);
- os instrumentos dormentes da era Origin (`scripts/gate-dev`, `scripts/pr-ready`, `scripts/train`) permanecem no tree
  sem operar no fluxo vivo (D-314).
