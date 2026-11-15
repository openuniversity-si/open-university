# PADRAO-DEV — avaliação

Programa pelo [método de gestão](../../padrao/METODO.md) (PDCA: avaliação → pesquisa → análise → solução → fases →
verificação → retrospectiva), com os modelos de [`_template/`](../_template/) e o
[Padrão v8, programa](../../padrao/v8/program.md) onde não conflitam com o método. Os números desta avaliação são os
primeiros encontrados; a linha de base completa, com os comandos, fica na [análise](analise.md).

## Pedido
Daniel Bello, 15/11/2026, 19:50 BRT (abertura do programa, resumo literal): formar o padrão interno de desenvolvimento
da Torre; a partir dele, configurar todos os nossos sistemas e operá-los e implementá-los. O padrão precisa ser muito
bem desenhado, para que todo código novo já nasça nele, no estado da arte. O documento de abertura entrega só o
problema; a solução vem da pesquisa e da análise. Restrições que continuam valendo: GitHub como fonte da verdade com a
fila de merge, gate em até 1 minuto, deploy com mediana de 1 s, teto AWS de US$200 por mês, operação por eventos sem
polling, código da era Origin dormente.

O repositório já tem um Padrão versionado (`docs/padrao/` v1 a v8, o método acima deles) e programas vizinhos
([test-excellence](../test-excellence/), [gate-speed](../gate-speed/), [reach-1000-prs-per-day](../reach-1000-prs-per-day/),
[censo-no-manifesto](../censo-no-manifesto/)). O programa não começa do zero: leva esse Padrão ao ideal, e a análise
audita o que já existe.

## Sintoma
1. **Consertamos o que um processo teria evitado.** Em dois dias de GitHub (14–15/11, 55 PRs mergeadas), a suíte
   completa ficou vermelha em `main` três vezes depois de um `tower/gate` verde (issues #15, #28, #36; 3 de 41 execuções
   do `full-suite`). Na #28 (PR #26) a regra "nenhuma chamada a endpoint fora do seu adaptador" quebrou em
   `scripts/lib/deploy.py:114`, e o gate seletivo não rodou o teste dela, porque a seleção vem de manifestos `covers`
   escritos à mão. A correção veio numa segunda PR (#30). Na #36 um teste instável (`runner-env`) foi vermelho uma vez e
   verde sozinho. Daniel cita arquivos compartilhados e dependências anotadas à mão em arquivo compartilhado, que já
   deram problema várias vezes; o próprio repositório registra o caso de doze PRs abertas editando o mesmo agregado
   gerado no mesmo dia (`scripts/lib/merge_regenerate.py`, cabeçalho).
2. **O custo de mudança é alto.** Cada teste nomeia as suas entradas num manifesto (`scripts/tests/covers/*.json`, 214
   manifestos, 2.486 entradas), cada chave do registro nomeia os seus leitores (`x-readers`, 1.154 entradas em 825
   chaves), cada unidade nomeia os seus caminhos e dependências (`units/*/unit.json`, 61 unidades). Uma mudança que
   cria um arquivo ou um leitor novo edita dados que outras mudanças também editam.
3. **Não sabemos o que os testes garantem.** O gate roda em segundos, mas nenhuma medida diz a cobertura dos testes, se
   cada teste selecionado de fato executou o código que diz cobrir, nem se todos os testes necessários existem. Um teste
   cujo `covers` omite um arquivo que ele lê nem é selecionado nem tem o cache invalidado quando esse arquivo muda
   (`scripts/lib/gate_test_cache.py`, a chave é função do `covers`); não existe ferramenta de cobertura instalada
   (`coverage.py` ausente do toolchain).

## Sistema que falhou
A hipótese do pedido era a falta de quatro sistemas (requisitos, arquitetura, o próprio padrão, testes e validação). A
primeira leitura do repositório corrige o quadro: partes de cada um **existem**, espalhadas e sem um dono que as junte.
O que falhou é um sistema só, com quatro faces:

- **O sistema de padrão de engenharia não existe como sistema gerido.** O Padrão versionado (`docs/padrao/` v1–v8 e o
  método) cobre a gestão do trabalho (programa, projeto, processo, operação) e o fluxo de entrega; não cobre a
  engenharia do produto: que requisitos uma mudança realiza, que forma o código tem, que testes provam o quê. As regras
  de engenharia que existem nasceram de incidentes, uma a uma, em decisões (`docs/domain/decisions/`, 83 arquivos),
  checagens do gate e prosa do AGENTS.md, sem um catálogo que diga quais regras existem, qual checagem prova cada uma e
  qual regra ainda é só texto.
- **Requisitos:** existem como invariantes e decisões (`docs/domain/CONTRACT.md`, `DECISIONS.md`, "a decisão nomeia o
  teste que a prova"), sem rastreabilidade verificada da decisão ao teste.
- **Arquitetura:** existem unidades com dono e dependências verificadas (`units/`, `scripts/lib/unit_map.py`), portas e
  adaptadores (`docs/architecture/PORTS.md`) e regras de estrutura como testes; 368 arquivos de código não pertencem a
  nenhuma unidade.
- **Testes e validação:** existem um mapa de seleção (covers), cache por conteúdo, testes herméticos, checagem de testes
  órfãos e a suíte completa pós-merge; falta a medida de adequação (cobertura, mutação) e a prova de que o mapa de
  seleção é completo, e a dependência declarada à mão é a fonte da seleção.

Por isso é um sistema a **construir** (o padrão de engenharia gerido) que **melhora** sistemas existentes (os quatro
acima), não quatro sistemas a criar do zero.

## Sistema ideal
Um padrão de engenharia versionado, feito para produção de código por agentes em volume (1 PR por minuto ou mais), em
que:

1. **Toda regra é dado com uma checagem.** O padrão é um catálogo de regras; cada regra tem uma checagem automática que
   roda no gate ou é declarada orientação, nunca as duas coisas sem distinção. Uma regra sem checagem não obriga
   ninguém. O catálogo é versionado e mudar uma regra é uma PR como qualquer outra.
2. **Nada que a máquina deriva é escrito à mão.** Dependências, leitores, seleção de testes, donos e agregados são
   derivados do código ou da execução; o que é declarado (uma intenção, um requisito) é declarado uma vez, num arquivo
   próprio, e verificado contra o código.
3. **Cada mudança é local.** A forma do código faz uma mudança caber no contexto de uma unidade: um agente lê pouco,
   muda pouco e não persegue efeitos pelo sistema; dois agentes em paralelo quase nunca tocam o mesmo arquivo.
4. **Os testes provam o que dizem.** Cada requisito aponta para os testes que o provam; a adequação dos testes é medida
   (cobertura e mutação) e tem piso; o gate prova que todo teste afetado rodou e passou, sem depender de declaração.
5. **Todo código novo nasce no padrão.** Os geradores e modelos produzem código já conforme; o gate recusa o que não é.
6. **O próprio padrão melhora pelo ciclo.** Cada escape (defeito que passou pelo gate) é classificado e vira regra com
   checagem ou teste, para que a mesma classe não volte.

## Distância
- **Existe:** o método de gestão; o gate com plano, seleção, cache e hermeticidade; a suíte completa pós-merge que pega
  escapes; geração com driver de merge para agregados; checagens derivadas para leitores do registro
  (`registry_readers.py`) e dependências entre unidades (`unit_map.py`); testes de regras estruturais (portas,
  literais, segredos).
- **Falta:** o catálogo das regras de engenharia com a checagem de cada uma; a medida de adequação dos testes; a prova de
  que a seleção do gate não perde testes (hoje a declaração manual `covers` decide); a rastreabilidade requisito → teste;
  a dono e a forma de cada arquivo de código (368 sem unidade); o fim das listas escritas à mão em arquivo compartilhado;
  a classificação dos escapes como entrada do padrão. O driver de merge dos agregados só roda num merge local: a fila
  do GitHub não o executa, então um conflito num agregado gerado volta a ser de uma pessoa (a verificar na análise).

## Painel de métricas
**Objetivo:** toda mudança nasce no padrão e chega a `main` certa na primeira vez, com custo baixo, sem que ninguém
precise conferir à mão o que a máquina pode provar.

- **Principal: taxa de escape**, a fração das PRs mergeadas que levam a `main` um defeito encontrado depois do merge (a
  suíte completa vermelha atribuída à PR, um revert, ou uma PR posterior que conserta o que ela quebrou). Menor é
  melhor. Puxa o programa porque cada escape é exatamente "o problema que um processo bem definido teria evitado".
  Aceitável no fim: abaixo de 1 % com volume de 1.000 PRs por dia. Linha de base na análise.
- **Guarda, vazão:** PRs mergeadas por dia não caem por causa do padrão (o padrão não pode ganhar qualidade travando o
  fluxo; SEMENTE §3).
- **Guarda, tempo do gate:** `tower/gate` p50 e p99 ≤ 60 s (restrição travada).
- **Guarda, custo:** AWS ≤ US$200/mês e deploy com mediana de 1 s (restrições travadas).
- **Complementar, conhecimento dos testes:** cobertura de linhas do código Python e shell sob a suíte, escore de mutação
  numa amostra fixa, e fração dos testes cujo `covers` contém tudo o que o teste lê de fato (completude da seleção).
  Impedem que a taxa de escape caia só porque a suíte completa deixou de encontrar defeitos.
- **Complementar, regras com checagem:** fração das regras do catálogo que têm checagem automática. Mede o item 1 do
  ideal; não é meta sozinha, porque se infla com regras triviais.
- **Complementar, custo de mudança:** arquivos tocados por PR fora da unidade principal da mudança, e arquivos editados
  à mão por mais de uma PR no mesmo dia (exposição a conflito). Medem os itens 2 e 3 do ideal e testam as hipóteses de
  segmentação e de fim dos arquivos compartilhados.
