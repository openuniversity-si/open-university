# PADRAO-DEV — avaliação

Programa pelo [método de gestão](../../padrao/METODO.md) (PDCA: avaliação → pesquisa → análise → solução → fases →
verificação → retrospectiva), com os modelos de [`_template/`](../_template/) e o
[Padrão v8, programa](../../padrao/v8/program.md) onde não conflitam com o método. Os números vêm da
[análise](analise.md).

**Revisão 2 (15/11, depois da correção de Daniel das 20:42 e 20:44 BRT).** A primeira versão (PR #58) subordinou tudo à
taxa de escape: duas das seis fases eram de teste, requisitos ficaram na última fase e só os de comportamento, e
arquitetura virou "todo arquivo tem unidade". A correção é procedente: a própria pesquisa já trazia a 12207 como lista
de sistemas que precisam existir e o SWEBOK como mapa de cobertura, e a solução não os usou. Esta revisão põe cada
sistema do ciclo de engenharia como objeto de primeira classe, num modelo único; testes e validação continuam, como dois
dos sistemas, não como o eixo.

## Pedido
Daniel Bello, 15/11/2026, 19:50 BRT (abertura do programa, resumo literal): formar o padrão interno de desenvolvimento
da Torre; a partir dele, configurar todos os nossos sistemas e operá-los e implementá-los. O padrão precisa ser muito
bem desenhado, para que todo código novo já nasça nele, no estado da arte.

Correção, 20:42 BRT (por outra sessão, em nome dele): o programa ficou focado demais em teste. Faltam um sistema
unificado de gestão de requisitos (todos os requisitos: produto, operação, qualidade e restrições; ciclo de vida
proposta → aprovado → implementado → verificado → substituído; dono; rastreio requisito → arquitetura → código → teste;
medida própria), um de arquitetura (visões, decisões com ciclo de vida e confirmação, componentes e unidades, contratos
e portas, a arquitetura de referência existente, funções de aptidão) e um do padrão (catálogo de regras, propostas de
mudança, versões, conformidade calculada).

Complemento, 20:44 BRT: **tudo tem um sistema.** Cada parte do ciclo, do requisito ao teste de validação, tem um sistema
de gestão próprio e unificado; no mínimo requisitos, arquitetura, desenvolvimento (construção: unidades, código,
revisão, integração, entrega), testes (unidade, integração, sistema), verificação e validação (inclusive o teste de
validação final), o padrão e a gestão do padrão; a lista se fecha pela pesquisa (SWEBOK v4, ISO/IEC/IEEE 12207 e 15288),
não só pela dele. Cada sistema tem objeto gerido, ciclo de vida, dono, registro como dado, ligações de rastreio com os
vizinhos, medida própria e conformidade calculada. Os sistemas se encaixam num modelo único, para que a cadeia
requisito → arquitetura → código → teste → validação seja navegável e verificável de ponta a ponta.

Restrições que continuam valendo: GitHub como fonte da verdade com a fila de merge, gate em até 1 minuto, deploy com
mediana de 1 s, teto AWS de US$200 por mês, operação por eventos sem polling, código da era Origin dormente.

## Sintoma
1. **Consertamos o que um processo teria evitado.** Em dois dias de GitHub (14–15/11, 55 PRs mergeadas), 6 PRs levaram
   a `main` um defeito encontrado depois do merge, e outras 6 existem só para consertá-los (#7, #16, #18, #30, #47, #49).
   Os escapes se distribuem pelo ciclo inteiro, não só pelos testes: dois são de comportamento operacional que nenhum
   requisito escrevia (#40, #41), um de efeito em outro módulo que nenhuma arquitetura ligava (#17), um de construção que
   um verificador de tipos pega (#3), e dois e meio de seleção de testes (#26 e a árvore inicial).
2. **Os artefatos de cada parte do ciclo existem, espalhados, sem sistema.** Requisitos vivem em pelo menos sete lugares
   (a intenção e as metas travadas da [semente](../../SEMENTE.md), 294 decisões, 15 invariantes e 6 garantias de
   `CONTRACT.md`, 12 capacidades, 58 premissas, os requisitos da [arquitetura de referência](../../arquitetura-referencia/01-requisitos.md),
   21 chaves de SLO e orçamento no registro), cada um com forma, estado e dono próprios ou nenhum. Arquitetura vive em
   cinco (33 ADRs, a maioria do produto que saiu; 28 documentos da arquitetura de referência; 6 de `docs/architecture`;
   61 manifestos de unidade; as regras estruturais como testes), sem ciclo de vida comum (6 das 33 ADRs declaram estado)
   e sem ligação verificada entre eles. O padrão vive em três (o Padrão v8, os 16 princípios D-069, o registro de regras
   com 1 registro para 49 recusas), e checagens nascem em modo relatório e nunca viram bloqueio.
3. **O custo de mudança é alto,** porque as ligações entre os artefatos são escritas à mão em arquivos que várias
   mudanças editam: 2.486 entradas `covers`, 1.154 `x-readers`, os `paths` e `requires` das unidades. Daniel cita
   arquivos compartilhados e dependências anotadas à mão que já deram problema várias vezes.
4. **Não sabemos o que é verdade.** Não sabemos quantos requisitos existem, quais têm teste, qual parte da arquitetura o
   código segue, a cobertura dos testes, nem se os testes selecionados executam o que dizem: uma rastreação dos 214
   testes mostrou que 207 executam algum arquivo cuja mudança, sozinha, não os faria rodar no gate.

## Sistema que falhou
Não falharam quatro sistemas isolados. Falhou **o sistema de engenharia como um todo, por não ser um sistema de
sistemas**: cada parte do ciclo tem artefatos, alguns muito bons (o registro de configuração com leitores conferidos, as
dependências entre unidades conferidas, as decisões em um arquivo por registro, o gate por plano, a fila de merge), mas
nenhuma parte tem os sete atributos de um sistema gerido (objeto, ciclo de vida, dono, registro como dado, rastreio,
medida, conformidade calculada), e não há um modelo que ligue as partes. Por isso:

- uma mudança não sabe que requisito realiza, que elemento da arquitetura toca, que testes a provam e que validação a
  aceita; quem sabe é a sessão, por leitura;
- uma regra do padrão não sabe onde se aplica nem se está sendo seguida;
- um defeito encontrado depois do merge não volta para o sistema que o deixou passar.

É um sistema a **construir** (o modelo único e os sistemas que faltam) que **incorpora e melhora** os artefatos que já
existem, sem recomeçar nenhum deles.

**A lista dos sistemas** fica fechada pela pesquisa ([pesquisa](pesquisa.md), seção "Sistemas do ciclo"). Ponto de
partida, de Daniel: requisitos; arquitetura; construção (unidades, código, revisão, integração, entrega); testes
(unidade, integração, sistema); verificação e validação, com a validação final; o padrão; a gestão do padrão.

## Sistema ideal
Um **modelo de engenharia único**, versionado no repositório, em que:

1. **Tudo tem um sistema.** Cada parte do ciclo de vida da 12207/15288 que a Torre precisa (a lista fechada na pesquisa)
   é um sistema com objeto gerido, estados de ciclo de vida, dono, registro como dado (um arquivo por objeto, nunca uma
   lista compartilhada), ligações de rastreio tipadas com os sistemas vizinhos, uma medida própria e a conformidade
   calculada por máquina.
2. **Uma cadeia navegável de ponta a ponta.** Requisito → elemento de arquitetura → unidade e código → teste →
   verificação → validação, com cada ligação declarada uma vez no objeto que a conhece e verificada contra o real; uma
   ligação fica suspeita quando o objeto de origem muda, e a cadeia mostra o que uma mudança afeta antes do merge.
3. **Nada que a máquina deriva é escrito à mão.** Dependências, leitores, seleção de testes, donos e agregados vêm do
   código e da execução; o que só uma pessoa ou uma sessão sabe (uma intenção, um requisito, uma decisão) é declarado uma
   vez e verificado contra o resto.
4. **Toda regra é dado com checagem.** O padrão é um catálogo de regras, cada uma ligada aos sistemas e objetos a que se
   aplica, com a sua checagem, os testes da checagem e um modo (aviso com prazo, depois bloqueio). Mudar o padrão é uma
   proposta com ciclo de vida e versão, como qualquer outro objeto.
5. **Todo código novo nasce no modelo.** Os geradores criam o objeto, as ligações e o teste juntos; o gate recusa o que
   não está ligado.
6. **O próprio modelo melhora pelo ciclo.** Cada escape é atribuído ao sistema que o deixou passar e muda esse sistema.
   Só restam os limites físicos: os 60 s do gate, a fila, a cota.

## Distância
- **Existe e entra no modelo como está ou quase:** o registro de configuração (825 chaves, um arquivo por chave,
  leitores conferidos), as unidades com dependências conferidas, as decisões como registros com prova, as capacidades
  com estado, as premissas com raio, o gate por plano com cache por conteúdo, a fila de merge, a suíte completa
  pós-merge, os eventos com contrato, o método de gestão.
- **Existe como prosa ou em partes, sem os sete atributos:** requisitos (sete lugares), arquitetura (cinco lugares), o
  padrão (três lugares), testes (sem nível, sem adequação medida, seleção por declaração manual), validação (um canário
  de deploy; nenhuma validação contra a necessidade de quem pediu), revisão (nenhuma, por decisão: D-055).
- **Não existe:** o modelo único com as ligações tipadas e verificadas; o ciclo de vida comum; a conformidade calculada
  por sistema; a gestão do padrão como sistema (propostas, versões, conformidade); a ligação de um escape ao sistema que
  o deixou passar.

## Painel de métricas
**Objetivo:** toda mudança nasce ligada à cadeia requisito → arquitetura → código → teste → validação, cada sistema da
cadeia é gerido e medido, e a mudança chega a `main` certa na primeira vez, com custo baixo.

**Principal: a fração da cadeia verificada de ponta a ponta.** Dos requisitos ativos (todos os tipos), a fração cuja
cadeia está completa e verificada: ligado a pelo menos um elemento de arquitetura, que é realizado por pelo menos uma
unidade, que tem testes ligados ao requisito, verdes em `main`, e uma verificação ou validação registrada; nenhuma
ligação suspeita. Maior é melhor. É uma só métrica que puxa todos os sistemas: ela só sobe se requisitos existem como
dado, se a arquitetura liga requisito a código, se o código tem dono, se os testes provam o requisito e se a validação
existe. Ela se infla com poucos requisitos, e por isso a guarda de inventário abaixo a acompanha.

**Medidas próprias de cada sistema** (uma por sistema; definidas por inteiro na solução, com a lista fechada):
requisitos com dono, estado e verificação; elementos de arquitetura com decisão aceita e função de aptidão verde;
arquivos de código com unidade e regras de construção sem piora; testes com nível, seleção completa e adequação medida;
requisitos com validação registrada; regras do padrão com checagem; propostas do padrão decididas no prazo. E a
**conformidade calculada** de cada sistema: a fração dos seus objetos que cumpre as regras do padrão que se aplicam a ele.

**Guardas:**
- **Inventário de requisitos:** os requisitos que existem em cada fonte conhecida (as sete da análise) entram no
  sistema; a métrica principal não pode subir com fontes deixadas de fora.
- **Taxa de escape** (resultado): PRs mergeadas que levam a `main` um defeito encontrado depois do merge, 10,9 % na
  linha de base; cada escape atribuído ao sistema que o deixou passar. Não pode piorar, e é a prova de que o modelo
  serve para alguma coisa.
- **Vazão:** PRs mergeadas por dia não caem por causa do padrão (SEMENTE §3).
- **Tempo do gate** p50 e p99 ≤ 60 s, **custo AWS** ≤ US$200/mês e **deploy** com mediana de 1 s (restrições
  travadas).
