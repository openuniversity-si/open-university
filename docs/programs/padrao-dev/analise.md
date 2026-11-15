# PADRAO-DEV — análise

O estado atual medido, com linha de base, e as causas (método §2, passo 3). Corresponde ao `diagnostico.md` dos
modelos (Padrão v8); o método chama a etapa de análise. Medido em 15/11/2026, entre 22:55 e 23:59 UTC, no contêiner da
sessão (4 vCPUs), sobre `main` em `40bec46` (depois das PRs #56 e #57), salvo onde a linha diz outra fonte.

## Métrica principal
**Taxa de escape:** PRs mergeadas que levaram a `main` um defeito encontrado depois do merge ÷ PRs mergeadas, numa
janela. Uma PR escapou quando (a) a suíte completa ficou vermelha em `main` por causa dela, (b) foi revertida, ou (c) uma
PR posterior conserta o que ela quebrou. Menor é melhor.

É uma proxy com lacunas conhecidas: só conta o defeito que alguém encontrou (a suíte completa, um deploy, uma medida);
um defeito que ninguém viu não conta. Por isso as métricas de conhecimento dos testes, abaixo, são guardas dela: se a
suíte deixa de encontrar defeitos, a taxa cai sem que nada tenha melhorado. Hoje a classificação é feita à mão a partir
dos corpos das PRs; a fase F1 a torna um evento (ver [solução](solucao.md)).

## Métricas de guarda
- **Vazão:** PRs mergeadas por dia (o padrão não pode ganhar qualidade travando o fluxo).
- **Tempo do gate:** duração do `tower/gate` por execução, p50 e p90, em `pull_request` e em `merge_group`.
- **Custo:** AWS por mês e mediana do deploy (restrições travadas; medidas pelos programas do deploy, não por este).

## Linha de base

### Escapes e retrabalho (55 PRs mergeadas, 14/11 04:28 a 15/11 22:55 UTC)
Fonte: as PRs e issues do GitHub (`list_pull_requests`, `list_issues`, os corpos de #7, #16, #18, #30, #47, #49) e as
execuções do `full-suite` (`actions_list`, 41 execuções).

| PR que escapou | Encontrado por | Conserto | Classe do escape |
|---|---|---|---|
| #3 (engine-repo) | o primeiro deploy do GitHub falhou a checagem de saúde e voltou | #7 | teste fraco: o teste "só procurava a chamada"; um nome de módulo sombreava o engine do banco, erro que um verificador de tipos pega |
| #17 (GATE-SHUTDOWN) | o `prune` diário do serviço quebrou nas funções removidas | #18 | efeito não local: a mudança apagou recursos que outro módulo listava, e nenhum teste ligava os dois |
| #26 (QUEUE-RELOAD) | suíte completa vermelha em `main` (issue #28) | #30 | seleção: `vendor-ports` varre o repositório inteiro, mas o seu `covers` não nomeava `deploy.py`, e o gate não o rodou |
| a árvore inicial | a primeira suíte completa no GitHub (issue #15): quatro testes vermelhos, dois deles "vermelhos aqui também; o `tower/gate` nunca os tinha selecionado" | #16 | seleção (dois) e ambiente do executor (dois) |
| #40 (QUEUE-BELL) | medida do build: um merge só de `scripts/` refez as pilhas ECS em 3 min 24 s | #49 | comportamento operacional sem requisito nem teste |
| #41 | medida: o toque do deploy recebeu 409 e nenhum build rodou | #47 | comportamento operacional sem requisito nem teste |

- **Taxa de escape: 6 de 55 = 10,9 %** (a árvore inicial contada como uma). **Retrabalho:** 6 PRs de 55 existem só para
  consertar o que outra quebrou (#7, #16, #18, #30, #47, #49).
- **Suíte completa em `main`:** 3 vermelhas em 41 execuções (7,3 %): #15 e #28 acima, e #36, um teste instável
  (`runner-env`) vermelho uma vez e verde sozinho, não atribuível a uma PR.
- **Classes:** seleção do gate 2,5 escapes; comportamento operacional sem requisito 2; teste fraco 1; efeito não local
  1; ambiente 0,5. Nenhum escape veio de conflito textual de merge nesta janela: o histórico no GitHub tem dois dias.
  Antes dele, o [audit do test-excellence](../test-excellence/audit.md) (28/10) mediu o CODEOWNERS editado à mão em 30 de
  76 PRs e 27 pares de PRs em conflito nas baselines de literais, e o cabeçalho de `scripts/lib/merge_regenerate.py`
  registra doze PRs abertas no mesmo agregado gerado no mesmo dia; as três causas foram tratadas (CODEOWNERS saiu,
  registro dividido em um arquivo por chave, D-095; decisões em um arquivo por registro, D-217; driver de merge para os
  agregados gerados).

### Vazão e gate
- **Vazão:** 55 PRs em cerca de 43 horas, cerca de 31 por dia (a meta é 1.000 por dia).
- **`tower/gate`, `pull_request`:** 34 execuções concluídas; duração da execução (início ao fim, com a instalação do
  toolchain) p50 82 s, p90 166 s, máximo 219 s. **`merge_group`:** 26 execuções, p50 27 s, p90 153 s. O p50 da PR já
  passa do teto de 60 s quando se conta a execução inteira; o passo `verify` sozinho é menor (o programa gate-speed mede
  por passo). Fonte: `actions_list` de `tower-gate.yml`, campos `run_started_at` e `updated_at`.

### Testes: inventário, execução e seleção
| Medida | Valor | Comando |
|---|---|---|
| Testes de script (`*.test.sh`) | 214, cada um com um manifesto `covers` | `ls scripts/tests/*.test.sh` |
| Funções de teste Python e JS (estático) | 4.858 `def test_` e 80 `test(`/`it(` | `rg -c '^\s*def test_' scripts/tests infra` |
| Suíte completa a frio, sem cache | 214 rodaram, 213 passaram, 1 falhou; parede 237 s | `GATE_TEST_CACHE_DIR=<vazio> OU_SHARED_RESULTS=0 scripts/test-suite --json F` |
| O vermelho | `infra-intask-standby`: cinco casos "not in time" sob carga; verde sozinho em 11 s | `bash scripts/tests/infra-intask-standby.test.sh` |
| Contagem de casos por teste no gate | nenhuma: o gate julga o `*.test.sh` pelo código de saída; não compara casos executados com casos esperados | `scripts/lib/gate_test_cache.py` |
| Entradas `covers` escritas à mão | 2.486 (241 globs) em 214 manifestos | `scripts/tests/covers/*.json` |
| Código que executa fora do próprio `covers` | ver "Completude da seleção" abaixo | `strace -f -e trace=openat,execve` por teste |
| Cobertura de linhas | medida uma vez, em 30/10: 89,12 % de `scripts/` (gate-speed); nunca mais; não inclui `infra/` | `scripts/test-suite --metrics --coverage DIR` |
| Mutação | nunca medida | — |

**Completude da seleção.** O gate escolhe os testes de uma mudança pelos `covers` que nomeiam os arquivos mudados, e o
cache de cada teste é função dos arquivos que o seu `covers` nomeia (`scripts/lib/gate_script_tests.py`,
`gate_test_cache.py`). Um arquivo que nenhum `covers` nomeia roda a suíte inteira (falha fechada); um arquivo que algum
`covers` nomeia roda só esses testes. Logo, um teste que executa um arquivo sem declará-lo não é selecionado nem tem o
cache invalidado quando esse arquivo muda. A rastreação mediu isso diretamente: cada `*.test.sh` rodou sob `strace`, e
os arquivos de código versionados que ele abriu foram comparados com o seu `covers` (mais as entradas comuns
`gate.test_cache_common_inputs`). As leituras do registro (`config/registry/**`) ficam de fora, porque a seleção por
leitores de chave (`x-readers`) as trata.

Resultado numa amostra dos primeiros 77 testes em ordem alfabética (de `aws-*` a `gate-*`; a rastreação dos 214 custa
cerca de uma hora sob `strace` e passa a ser medida pelo comando da F1):

| Medida | Valor |
|---|---|
| Pares teste × arquivo de código executado | 2.132 |
| Pares fora do `covers` do teste | **1.659 (78 %)** |
| Desses, arquivos que algum outro `covers` nomeia (a mudança não cai na falha fechada) | 1.659: todo arquivo de código é nomeado por algum `covers`, muitos por globs como `scripts/lib/*.py` |
| Testes com pelo menos um arquivo assim | **32 de 77 (42 %)**; 7 deles varrem mais de 50 arquivos (regras do repositório inteiro, a classe do escape #26) |
| Arquivos cuja mudança deixa pelo menos um teste que o executa sem rodar | 480 |
| Os que mais deixam | `scripts/lib/gate-budget.sh` (14 testes), `scripts/lib/config.py` (11), `scripts/gate-local`, `scripts/lib/gate_select.py` e os `gate-hooks/*.sh` (10 cada) |

Prova no plano real do gate (`scripts/gate-check plan checks --base origin/main`, numa worktree com um commit de uma
linha): mudar só `scripts/lib/gate_select.py` seleciona 12 testes e não `gate-flake`, que executa esse arquivo; mudar só
`scripts/lib/gate-budget.sh` seleciona 4 e também não `gate-flake`. Nos dois casos `gate-flake` também não perde o cache.
Uma leitura não prova uma dependência de comportamento (um varredor lê o código como dado), mas cada par é um teste que
pode ficar vermelho sem que o gate o rode, e é assim que #26 escapou.

**O detector de escape ficou na era Origin.** O evento `selection.escape` ("o tier 2 falhou um teste que o tier 1 não
selecionou", `contracts/events/selection.escape.v1.json`) e a quarentena de instáveis (`test.flaked`,
`test.quarantined`, `scripts/lib/quarantine.py`) são emitidos pelo trem (`scripts/lib/train.py`), dormente desde a
migração (D-314, D-316). No GitHub, a suíte completa pós-merge abre uma issue e nada classifica o escape, atribui a PR
ou conta a instabilidade: as issues #15, #28 e #36 foram lidas e fechadas à mão.

### Requisitos
- **Decisões como registros:** 81 arquivos `docs/domain/decisions/D-NNN.md`, cada um com o campo `proof`; 2 provas não
  existem mais (D-220 `scripts/tests/structure.test.sh`, D-274 `scripts/tests/test_lane_ship.py`) e nada acusou. As 213
  linhas anteriores ficam na tabela de `DECISIONS.md` com a prova em prosa. Nenhuma checagem liga uma decisão aos testes
  que a provam nem diz se a prova ainda roda.
- **Invariantes:** `docs/domain/CONTRACT.md` (154 linhas), sem rastreio gerado para testes.
- **Comportamento operacional** (o que o deploy, a fila e o serviço devem fazer): sem registro de requisito; dois dos
  seis escapes são dessa classe.
- **Ferramenta:** `scripts/decision-next` falha no GitHub (`forge_origin.OriginAdapterError: github.com: git remote is
  not an Origin git host`); `scripts/decision-record` funciona localmente.

### Arquitetura e forma do código
- **Unidades:** 61 manifestos `units/*/unit.json`; 443 importações Python entre unidades no código de produção, todas
  declaradas em `requires` (a checagem de `scripts/lib/unit_map.py` funciona); 81 importações de testes entre unidades
  não declaradas. **368 arquivos de código sem unidade** (186 em `scripts/lib`, 126 em `scripts/tests`, 51 em
  `infra/service`).
- **Leitores do registro:** 1.154 entradas `x-readers` em 825 chaves, escritas à mão e conferidas pelo código
  (`scripts/lib/registry_readers.py`, que também corrige com `--fix`): sem lacuna hoje.
- **Pontos quentes:** os arquivos mais tocados pelas 54 PRs são também os maiores: `scripts/tests/test_deploy_sh.py`
  (2.091 linhas), `infra/service/tower_infra/autodeploy.py` (1.508), `infra/aws/deploy.sh` (1.459),
  `infra/service/tower_infra/__main__.py` (751, 7 PRs). 19 arquivos de código passam de 1.000 linhas.
- **Custo de mudança:** por PR, mediana de 2,5 arquivos (p90 16) e 2 unidades (p90 6); 54 % das PRs tocam código fora da
  sua unidade principal (mediana 1 arquivo, p90 9). Comando: o diff de cada merge de primeiro pai em `main`, com os
  arquivos atribuídos às unidades pelos `paths` dos manifestos.
- **Construção:** o gate tem `shellcheck`, mas nenhuma etapa de lint ou de tipos para Python. Linha de base, fora do gate:
  `pyright` acusa 1.229 erros em 423 arquivos (888 `reportAttributeAccessIssue`, 152 `reportOptionalMemberAccess`);
  `ruff --select F` acusa 64 importações não usadas, 8 variáveis não usadas, 4 redefinições. Nenhum dos dois está no
  toolchain fixado (`config/registry/toolchain.json`).
- **Agregados gerados:** 1 driver de merge regenera os agregados num merge local (`.gitattributes`), mas a fila do GitHub
  não executa drivers locais; `.gitattributes` nomeia `config/registry/architecture.json`, que não existe.

### O próprio padrão
- **O que o Padrão versionado cobre:** `docs/padrao/v8` tem 15 regras, todas de gestão do trabalho do agente (salvar,
  decidir, paralelizar, programa, intake, auditoria, retro, árvore de agentes, esforço, veredito do gate). Nenhuma trata
  requisitos, forma do código, construção ou adequação de testes. Das 18 áreas do SWEBOK v4, o Padrão cobre processo e
  gestão; as demais estão em outros documentos ou em nenhum.
- **As regras de engenharia que existem:** os 16 princípios de `docs/process/principles/D-069.md` (26/10), cada um com
  a sua tabela "Enforced by": 52 linhas `exists`, 20 `planned` (com ids de um plano da era Origin, C0, M2, U3a, N1, que
  não têm PR aberta) e 9 `left`. O princípio 16 ("convenções geradas e aplicadas por lint") tem só o `shellcheck`.
- **O registro de regras:** `config/registry/rules.json` e `scripts/rule` existem desde 28/10 (RULE-AUDIT); o catálogo
  tem **1 registro**, `scripts/rule check` encontra **49 funções que recusam, 48 sem registro**, 32 premissas vencidas, e
  roda em modo `report`. O registro exigido tem cerca de vinte campos (justificativa, dano se passar, impacto positivo,
  negativo e medido da remoção, premissas, pergunta permanente com respostas, data de revisão, condição de fim); o
  custo de escrever um registro explica por que só um foi escrito. O censo de regras (`docs/audits/rules/census.json`) contou 1.017 linhas em 28/10 e não foi
  refeito.
- **Prosa que se pede ao agente:** AGENTS.md (70 linhas, 3.206 palavras) e CLAUDE.md (168 palavras) em toda sessão; o
  lançamento acrescenta as 15 regras do v8 (4.494 palavras). A pesquisa (Gloaguen, ICLR 2026) mostra que prosa de contexto custa mais de 20 % e não sobe o sucesso.

## Causas
Cada achado segue até uma causa de sistema (Padrão v8: a culpa é de um sistema, nunca do acaso ou de uma pessoa).

### C1. O padrão de engenharia não é um sistema gerido
1. Por que um escape como #3 ou #17 passa? Porque nenhuma regra de construção (tipos, efeito em outro módulo) é
   aplicada a todo código, só as que nasceram de incidentes anteriores.
2. Por que só essas? Porque as regras de engenharia estão espalhadas (D-069, AGENTS.md, checagens do gate, decisões) e
   nenhum catálogo diz quais existem, qual checagem prova cada uma e qual ainda é texto; o registro de regras tem 1 de 49.
3. Por que o catálogo não andou? Porque o Padrão versionado foi desenhado para a gestão do trabalho do agente, e as
   regras de engenharia ficaram fora dele, sem dono, sem medida de cobertura e sem caminho de aviso para bloqueio.

Classe: mecanismo faltando. Evidência: as seções "O próprio padrão" e "Construção" acima.

### C2. A dependência é declarada à mão e decide a seleção e o cache
1. Por que #26 e dois vermelhos da issue #15 escaparam? Porque o gate não rodou os testes que os pegariam.
2. Por que não rodou? Porque a seleção e o cache leem o `covers`, uma lista escrita à mão, e a lista não tinha o arquivo.
3. Por que uma lista à mão? Porque a dependência teste → código nunca foi medida; a rastreação desta análise é a primeira.

Classe: arquitetura/desenho (declarar o que se pode derivar). É a hipótese (b) no ponto onde ela mais custa: um arquivo
editado à mão por quem muda o código e por quem muda o teste, e sem checagem contra o real.

### C3. Os testes não são medidos pelo que garantem
1. Por que não sabemos a cobertura? Porque ela foi medida uma vez (30/10) como guarda de um programa e não virou medida
   contínua; o `infra/` cresceu fora dela.
2. Por que não sabemos se os testes verificam algo? Porque não há mutação nem contagem de casos por teste.
3. Por que um teste instável fica verde? Porque o vermelho em lote roda de novo sozinho e conta o verde
   (VERIFY-ALONE, #6), sem registrar a instabilidade como defeito do teste.

Classe: mecanismo faltando.

### C4. Requisitos de comportamento não existem como dado
1. Por que #40 e #41 escaparam? Porque o comportamento esperado (um merge só de scripts não refaz pilhas; todo merge
   tem o seu build) não estava escrito em lugar nenhum que um teste provasse.
2. Por que não? Porque requisito, hoje, é uma decisão de Daniel com uma prova; o que o sistema deve fazer além das
   decisões não tem registro, e a ligação decisão → teste não é checada (2 provas sumiram sem aviso).

Classe: mecanismo faltando.

### C5. A forma do código concentra as mudanças
1. Por que uma mudança toca outras unidades em 54 % das PRs? Porque o comportamento do deploy e do serviço vive em
   poucos arquivos grandes (2.091, 1.975, 1.508, 1.459 linhas) e 368 arquivos não têm unidade.
2. Por que isso custa? Porque esses arquivos são os pontos quentes: as mesmas PRs que escapam (#17, #26, #40, #41) os
   tocam, e cada mudança neles precisa de um contexto grande.

Classe: arquitetura/desenho. Confirma a hipótese (a) na forma que a pesquisa achou: fronteiras de ocultação de
informação, verificadas; não "mais arquivos".

## Distância do estado da arte
Temos o que muitos não têm: fila de merge, gate por plano com cache por conteúdo, testes herméticos, suíte completa
pós-merge, decisões em arquivo por registro, registro de configuração em arquivo por chave com leitores conferidos,
dependências entre unidades conferidas, regras estruturais como testes. Falta, contra a pesquisa: o catálogo de regras
como dado com checagem por regra (Google, OpenAI, Soundcheck); o mapa teste → código derivado da execução (TAP, Meta); a
contabilidade de casos por teste (TAP `1..N`); a adequação medida, cobertura do diff e mutação do diff (Google 2019,
2021); a gestão de instabilidade com quarentena (Google 2016); requisitos como dado com rastreio gerado (DO-178C,
OpenFastTrace); lint e tipos com catraca (Factory, Cursor/MSR 2026); e a taxa de retrabalho como métrica (DORA 2024).
