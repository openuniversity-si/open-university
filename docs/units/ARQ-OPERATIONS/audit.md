# ARQ-OPERATIONS — audit

## Entradas

[intake.md](intake.md) fixa a intenção de tornar explícita a responsabilidade por operação, para que mudar uma operação não exija inferir seu dono pela posse de arquivos.
Informa o problema e a ausência de denominador global; não determina desenho, universo completo nem critérios novos para a auditoria.
[research.md](research.md) distingue catálogo, política e prova arquitetural, com Backstage, OPA e ArchUnit como referências.
Informa a comparação e a escada de ambição; não escolhe arquitetura nem transforma a continuidade A2 em decisão de implementação.

Revisão observada: base `70a1ade53`, branch `arq/u1-work`, worktree `/tmp/wt-u1`.
As contagens foram medidas nesta árvore, antes deste arquivo; cada uma traz o comando que a produziu.
O universo é um **recorte da forja**, não um censo de operações do engine.
A ARQ-SISTEMA e D-284 são o ponto de partida: posse de caminho e `requires` não equivalem a posse exclusiva de operação.
O objeto aqui é a operação e seu responsável; capacidades parciais e grafo dinâmico não são reabertos como diagnósticos autônomos.

**Método:** operação, neste recorte, é cada um dos 17 nomes literais pedidos a `_operation` em `scripts/lib/forge_events.py`.
`change` é observado como passagem direta adjacente, fora desse denominador; métodos públicos dos adaptadores incluem auxiliares e diário e não ampliam automaticamente o universo.
Arquivos e unidades atravessados são proxies de leitura, coordenação e verificação, não medição causal de minutos.
A busca por nome também pode alcançar homônimos; mede alcance textual, não uma árvore de chamadas comprovada em execução.
O histórico mede introdução de operações; não autoriza atribuir a mesma distribuição a toda alteração posterior.

## Findings

1. **A operação não existe como artefato declarado; existe como nome no ponto de chamada.** O censo de `units/*/unit.json` encontrou 47 manifestos e zero campos `contract`, `operations` ou `operation`.
   Comando: `python3 -c "import json,glob,collections; c=collections.Counter(); [c.update(json.load(open(p)).keys()) for p in glob.glob('units/*/unit.json')]; print(c)"`.
   `contracts/adapters/` contém somente `engine-vendors.v1.json`; esse contrato trata vendedores, não operações da forja.
   `scripts/lib/unit_check.py:63-113,131-145` verifica posse de caminhos e `requires`; `rg -n operation scripts/lib/unit_check.py` não encontrou linhas.
   `scripts/lib/vendor_check.py:167-181` faz encolher o baseline de chamadas de vendedor; não conhece responsabilidade por operação.
   Os 17 nomes estão no código de chamada, e `scripts/lib/forge_events.py:449-457` resolve cada um com `getattr(self.adapter, name, None)` em tempo de chamada.
   **Custo observado:** descobrir o objeto da responsabilidade exige ler consumidores e implementações; nenhum campo dos manifestos dá essa resposta. Raiz R1.

2. **A superfície nomeada e as implementações não coincidem entre adaptadores.** A porta nomeia 17 operações; a AST das classes conta 24 métodos públicos diretos em `GitHubAdapter` e 9 em `OriginAdapter` (`scripts/lib/forge_github.py:106`, `scripts/lib/forge_origin.py:57`).
   Esses totais de métodos não são totais de operações da porta: incluem outras funções da classe.
   Faltam zero operações do recorte no GitHub e 13 no Origin: `calls`, `change_commits`, `close_change`, `comment`, `comments`, `find_change`, `lock`, `open_change`, `open_pulls`, `pull`, `pushes`, `unlock`, `upsert_comment`.
   Há implementação concreta em pelo menos duas unidades para seis nomes: `approvals`, `comments`, `merge`, `open_changes`, `pull`, `set_status` (AST das classes `GitHubAdapter`, `OriginAdapter` e `OriginClient`).
   `approvals` e `set_status` aparecem em `forge_github` e `forge_origin`; `comments` e `pull`, em `forge_github` e `forge_origin_client`.
   `open_changes` aparece em `forge_github`, `forge_origin` e `forge_origin_client`.
   `merge` aparece em quatro arquivos de três unidades: `forge_git_ref` (`engine-events`), `forge_github` (`engine-forge-github`), `forge_origin` e `forge_origin_client` (`engine-forge-origin`), todos em `scripts/lib/`.
   Isso conta implementações disponíveis, não quatro merges simultâneos nem prova de duplicação indevida de toda a semântica. Raízes R1/R3.

3. **O alcance textual de uma operação atravessa unidades por construção.** A mediana é 7 arquivos e 4 unidades; 17/17 operações alcançam pelo menos duas unidades.
   Comando por nome, substituindo `<op>`: `rg -l -e '(\.<op>\(|def <op>\(|_operation\(.<op>.)' --glob '*.py' --glob '*.sh' .`.
   A tabela mantém o recorte e a atribuição por `units.unit_of`; em `calls`, o total inclui uma posição sem dono, não uma unidade nomeada adicional.

   | Operação | Arquivos | Unidades |
   |---|---:|---:|
   | approvals | 7 | 4 |
   | calls | 11 | 7 (uma posição sem dono) |
   | change_commits | 4 | 3 |
   | close_change | 5 | 3 |
   | comment | 7 | 4 |
   | comments | 10 | 6 |
   | find_change | 5 | 4 |
   | lock | 14 | 8 |
   | merge | 17 | 7 |
   | open_change | 4 | 3 |
   | open_changes | 14 | 6 |
   | open_pulls | 7 | 4 |
   | pull | 10 | 6 |
   | pushes | 6 | 5 |
   | set_status | 7 | 4 |
   | unlock | 7 | 5 |
   | upsert_comment | 3 | 3 |

   A construção da porta também se espalha: `rg -l adapter_from_config scripts --glob '*.py'` encontra 38 arquivos em 26 unidades, com `scripts/tests/test_gate_forge_budget.py` sem dono.
   Fora dos adaptadores, o baseline GitHub contém 13 sites em 11 arquivos de 11 unidades (`scripts/lib/adapters/engine-vendors.json`, vendor `github`, campo `baseline`).
   Construir a porta, implementar uma operação e consumir uma operação são relações distintas; nenhuma dessas contagens isoladas identifica seu responsável.
   **Custo observado:** a pergunta sobre uma operação normalmente atravessa mais de uma posse de arquivo, mesmo com acesso centralizado pela porta. Raiz R3.

4. **Introduzir uma operação já exigiu atravessar configuração e código gerado.** O histórico do recorte reúne nove commits distintos, com mediana de 11 arquivos e 4 unidades, mínimo de 3 unidades.
   Sete dos nove tocaram `config/registry/*.json` ou `scripts/lib/generated/*`.
   Comando de seleção por operação: `git log --no-merges --reverse --format=%h -S"_operation('<op>')" -- scripts/lib/forge_events.py`.
   São introduções localizadas pelo nome, não uma amostra de todas as mudanças nem uma medição de tempo humano.

   | Introdução | Commit | Arquivos | Unidades | Arquivos config/generated |
   |---|---|---:|---:|---:|
   | approvals | `010dd04b4` | 13 | 4 | 3 |
   | set_status | `48be6d0bd` | 6 | 3 | 2 |
   | calls | `cc22202a5` | 16 | 5 | 5 |

   A configuração ao redor da forja contém 37 chaves distintas `config.get(...)`; 11 começam por `forge-events.github` nos módulos `forge_events`, `forge_github`, `forge_origin`, `forge_git_ref`, `forge_control` e `forge_board`.
   A distribuição histórica não prova que cada arquivo acompanhante era inevitável; demonstra que a introdução observada não ficou contida no implementador da operação.
   **Custo observado:** o responsável inferido pela posse do método ainda não abrange a configuração e a geração que acompanharam sua entrada. Raiz R4.

5. **A fronteira descobre incompatibilidade na chamada e nem uniformiza a falha.** `_operation` só consulta a presença do método ao recebê-lo (`scripts/lib/forge_events.py:449-457`).
   `change` chama `self.adapter.change(...)` diretamente em `:459-460`, sem passar por essa consulta.
   A prova com um adaptador vazio, executada nesta árvore, produz:

   ```text
   open_pulls → ForgeEventsError: the Bare has no open_pulls operation
   change → AttributeError: 'Bare' object has no attribute 'change'
   ```

   `RoutingAdapter.__getattr__` encaminha qualquer nome ao adaptador principal (`scripts/lib/forge_events.py:257-258`), sem lista de operações admitidas.
   A falta não é representada como incompatibilidade da operação antes de seu uso; chega ao consumidor como descoberta tardia, com erros distintos conforme o caminho.
   **Custo observado:** selecionar ou construir a porta não elimina a investigação da superfície exigida por cada consumidor. Raiz R2.

6. **O contrato herdado cobre exatamente o subconjunto comum do recorte.** `ForgeContract` tem oito casos (`scripts/tests/forge_events/test_forge_contract.py:32-66`), herdados por `GitHubContract` em `:121` e `OriginContract` em `:184`.
   Entre as 17 operações, os casos cobrem quatro: `approvals`, `merge`, `open_changes`, `set_status`; os demais casos tratam `change`, identidade e diário, fora desse denominador.
   `change` não conta como quinta operação coberta: acessa o adaptador direto, sem `_operation`.
   Conferência executada com Python: `ast.parse` de `forge_events.py`, `forge_origin.py` e `test_forge_contract.py`; coleta dos argumentos literais de `_operation`, dos `FunctionDef` diretos de `OriginAdapter` e das chamadas `self.adapter.*` em `ForgeContract`.
   Para os conjuntos `ops`, `methods` e `calls` assim extraídos, `ops - calls == ops - methods` retornou `True`.
   O conjunto idêntico tem 13 nomes: `calls`, `change_commits`, `close_change`, `comment`, `comments`, `find_change`, `lock`, `open_change`, `open_pulls`, `pull`, `pushes`, `unlock`, `upsert_comment`.
   Assim, um adaptador que não serve 13 das 17 operações satisfaz a superfície exigida pelos casos herdados; isso não declara aprovação em uma execução feita nesta auditoria.
   **Custo observado:** a existência do contrato não informa compatibilidade das operações que ficaram fora dele. Raiz R2.

7. **O mapa existente descreve, mas não governa responsabilidade.** `docs/architecture/ENGINE-OPERATIONS.md` tem 83 linhas e 11 operações em `:16-28`; `units.unit_of('docs/architecture/ENGINE-OPERATIONS.md')` retorna `None`.
   `rg -l ENGINE-OPERATIONS` encontra somente três documentos: `docs/domain/decisions/D-284.md`, `docs/domain/DECISIONS.md:268` e `docs/units/ARQ-SISTEMA/plan.md`.
   Nenhum código ou verificador referencia o mapa; a ausência de dono de caminho tampouco fornece responsável pelas operações ali nomeadas.
   `docs/architecture/PORTS.md:12` descreve três nomes (`append`, `read`, `change`); a docstring de `scripts/lib/forge_events.py:7-17`, cinco (`remote`, `append`, `read`, `recent`, `change`), contra 17 no recorte atual.
   Essas listas também incluem diário e passagem direta: não são versões reduzidas, mas descrições que divergem do vocabulário operacional efetivamente despachado.
   **Custo observado:** consultar a documentação ainda exige reconciliá-la com código para saber o que existe e não resolve quem responde pela operação. Raízes R1/R3.

8. **A medição herdada explica a abertura, mas não responde ao objeto desta unidade.** A ARQ-SISTEMA registrou 47 manifestos na mesma lane efetiva, 20/29 commits de código atravessando unidades e medianas de 2 unidades e 5 arquivos por commit (`docs/units/ARQ-SISTEMA/audit.md`, F1–F3).
   São números **HERDADOS**, não nova amostragem de histórico nesta auditoria.
   Seu denominador é um recorte de commits e arquivos; não é o conjunto de operações, cujo denominador global continua inexistente.
   O acréscimo desta auditoria é localizar a ausência de artefato de operação, de regra de responsável e de prova de compatibilidade por operação no recorte da forja.
   O alcance medido em F3 não converte cruzamento de arquivo em defeito, nem a lane comum em responsabilidade operacional inequívoca. Raízes R1/R3.

Esta auditoria **não mediu** um censo global de operações fora da forja nem tempo humano de mudança.
Não executou gate, trem, bateria ou suite; a prova de erro de F5 foi executada nesta árvore e está transcrita ali, e F6 é leitura estrutural dos testes, não sua execução.
Não conferiu produção nem o estado remoto do GitHub/Origin. Nenhuma contagem local demonstra seleção ou disponibilidade operacional remota.

## Causas raiz

### R1. A operação não tem representação declarada e só existe como nome no ponto de chamada

Cadeia de porquês:
1. Por que descobrir quais operações existem exige ler chamadas? Os 17 nomes do recorte estão nos pedidos a `_operation`, sem artefato próprio declarado.
2. Por que os manifestos não fornecem essa lista? Seus 47 registros não contêm `contract`, `operations` ou `operation`; descrevem unidades e caminhos.
3. Por que o contrato de adaptadores não fecha a lacuna? Seu único arquivo trata vendedores, não a identidade das operações que a porta despacha.
4. Por que o mapa documental não equivale à declaração governante? Tem 11 operações, não pertence a unidade e não é consumido por código ou verificador.
5. Por que a descoberta permanece dependente do ponto de chamada? O desenho representa unidade, arquivo e vendedor, mas deixa a operação como convenção nominal dispersa, sem identidade declarada sobre a qual a responsabilidade possa ser afirmada.

Classe: arquitetura/desenho
Evidência: F1/F7; censo JSON de `units/*/unit.json`; `contracts/adapters/engine-vendors.v1.json`; `scripts/lib/forge_events.py:449-457`; `docs/architecture/ENGINE-OPERATIONS.md:16-28`.

### R2. A fronteira aceita superfícies sem prova de compatibilidade por operação

Cadeia de porquês:
1. Por que a falta de uma operação só aparece ao consumidor? `_operation` resolve o método no instante da chamada, e `change` acessa o adaptador diretamente.
2. Por que o roteamento não recusa previamente uma superfície incompatível? `RoutingAdapter.__getattr__` encaminha qualquer nome ao principal sem delimitar operações.
3. Por que a prova herdada não revela as 13 ausências do Origin? Seus casos usam apenas quatro operações do recorte, todas já implementadas nos dois adaptadores.
4. Por que ter um contrato comum não demonstra a compatibilidade exigida pelos consumidores? O conjunto sem caso coincide exatamente com o conjunto ausente no Origin; a prova compartilhada não representa essa demanda restante.
5. Por que a descoberta tardia pode persistir com contrato existente? Falta mecanismo que confronte compatibilidade por operação na fronteira; a existência da fábrica e a prova do subconjunto comum são as garantias observadas.

Classe: mecanismo faltando
Evidência: F5/F6; `scripts/lib/forge_events.py:257-258,449-460`; `scripts/tests/forge_events/test_forge_contract.py:32-66,121,184`; igualdade de conjuntos conferida por AST.

### R3. Nenhuma regra liga a operação ao responsável; a posse verificada é a de arquivo

Cadeia de porquês:
1. Por que localizar o dono do arquivo não resolve quem responde pela operação? Todas as 17 operações alcançam mais de uma unidade no recorte textual.
2. Por que localizar o implementador também não encerra a atribuição? Seis operações têm implementação concreta em pelo menos duas unidades, além de seus consumidores.
3. Por que a exclusividade verificada não arbitra essa responsabilidade? `unit_check` julga posse de caminho e `requires`, não a relação entre operação, responsável e consumidor.
4. Por que a documentação não oferece outra regra vigente? O mapa não tem dono de arquivo nem leitor executável, e os manifestos não declaram operações.
5. Por que a responsabilidade continua sendo inferida caso a caso? Falta uma regra de atribuição operacional no modelo governado; fronteiras físicas legítimas coexistem sem uma relação verificada que diga quem responde pelo comportamento atravessado.

Classe: regra faltando
Evidência: F2/F3/F7; busca por operação da tabela; `scripts/lib/unit_check.py:63-113,131-145`; `units.unit_of('docs/architecture/ENGINE-OPERATIONS.md') → None`.

### R4. A operação e sua configuração não têm fronteira própria

Cadeia de porquês:
1. Por que introduzir uma operação atravessou arquivos além do adaptador? Os nove commits observados envolveram no mínimo três unidades e mediana de 11 arquivos.
2. Por que esse atravessamento inclui mais que consumidores e implementações? Sete dos nove commits tocaram configuração do registro ou código gerado.
3. Por que a configuração faz parte do mesmo caminho de mudança? A construção da porta e dos adaptadores lê configuração distribuída ao redor da forja, com 37 chaves distintas no recorte medido.
4. Por que o dono inferido pelo método não delimita essa mudança? A operação não é representada como limite que associe sua configuração ao comportamento; a atribuição disponível continua sendo a dos arquivos separados.
5. Por que esse custo reaparece ao introduzir ou mudar a operação? O desenho acopla comportamento operacional à seleção e configuração da forja sem fronteira própria da operação e de sua configuração; o histórico demonstra o atravessamento na introdução, sem quantificar toda alteração futura.

Classe: arquitetura/desenho
Evidência: F4; seleção histórica por `git log -S"_operation('<op>')" -- scripts/lib/forge_events.py`; commits `010dd04b4`, `48be6d0bd`, `cc22202a5`; chaves `config.get(...)` lidas pelos módulos da forja.

## Distância do estado da arte

O research distingue o catálogo de componentes/APIs/donos do Backstage, a política sobre fatos apresentados do OPA e a recusa arquitetural exemplificada pelo ArchUnit.
Essa comparação não transfere automaticamente ecossistema, cobertura ou ferramenta para este engine; nenhuma das referências fornece por si o censo semântico ausente.

Já existe vocabulário parcial: 11 operações num documento sem dono e desatualizado diante da porta com 17; a prova de contrato cobre quatro dessas operações (F6/F7).
Há posse verificada de arquivos e contenção de acessos de vendedor (F1), mas essas propriedades não compõem um catálogo consultável de operação ↔ dono ↔ consumidor.
Faltam essa relação declarada, uma regra recusante sobre ela e política sobre fatos declarados de operação; os checks observados julgam outros objetos.

O degrau 1 está parcialmente alcançado: há vocabulário, mas ele diverge do código e não governa responsabilidade.
O degrau 2 não foi alcançado: nenhuma relação operação ↔ dono ↔ consumidor é registrada ou exposta como tal; a tabela de alcance textual não a substitui.
O degrau 3 está fora de alcance nesta evidência, sem denominador global de operações para sustentar censo completo e contrato recusante.
A posição descreve a distância atual; não escolhe degrau-alvo nem alternativa para o plano.

## Base defects expected

O registro `docs/process/defects/scripts-tests-config-test-sh-3ec4be1f.yml:8-10` está `open`, com owner `engine-lane` e unit `engine-config`.
É registro histórico de defeito de base; a falha não foi reproduzida nesta auditoria.
Os registros `scripts-tests-premises-test-sh-4db6e693.yml` e `scripts-tests-generate-test-sh-024bbecb.yml`, no mesmo diretório, estão `resolved` e não entram na contabilidade de abertos.

A dívida documental de F7 é achado desta auditoria, não KD registrado: `docs/architecture/PORTS.md:12` e a docstring `scripts/lib/forge_events.py:7-17` descrevem uma superfície desatualizada; `docs/architecture/ENGINE-OPERATIONS.md` não tem dono nem referência no código.
A atribuição operacional desta dívida é `engine-lane`, pela porta em `engine-events`; a medição herdada de lanes não transforma isso em posse declarada dos documentos.
A conferência Python dos padrões `paths` de `units/*/unit.json` com `fnmatch.fnmatchcase` encontrou `forge_events.py` em `engine-events`, owner `engine-lane`, e nenhuma unidade para `PORTS.md` ou `ENGINE-OPERATIONS.md`.
Assim, o responsável pela porta é identificável por sua unidade, enquanto a ausência de posse dos documentos permanece parte do achado, sem atribuição de manifesto inventada.

Premises: none
