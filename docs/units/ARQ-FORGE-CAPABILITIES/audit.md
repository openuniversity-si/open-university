# ARQ-FORGE-CAPABILITIES — audit

## Entradas

- [intake.md](intake.md): fixa a intenção de tornar demonstrável a compatibilidade de um fluxo com a forja escolhida, sem redescobrir capacidades e exceções a cada troca. Registra que o requisito nasce da pesquisa desta unidade; não determina arquitetura, troca de seleção ou critérios novos nesta auditoria.
- [research.md](research.md): informa a comparação entre descoberta, seleção e conformidade, com pluggy, abc e stevedore, e a escada de ambição. Não escolhe arquitetura nem transforma A2 em desenho decidido.
- Decisão literal herdada da ARQ-SISTEMA, reproduzida no intake e registrada em seu plano como R3 → A1, **remendo**: “R3 → A1: a matriz orienta o desenho sem alterar seleção de forja ou fingir que nove métodos equivalem a 24 requisitos. Follow-up: unidade proposta ARQ-FORGE-CAPABILITIES, ainda não aberta, para A2 e tratamento das 13 exceções.” A2 é continuidade proposta, não desenho decidido.
- Não há documento intermediário entre a árvore e este arquivo: cada contagem abaixo remete ao arquivo:linha ou ao comando que a produziu. As entradas orientam a pergunta sobre compatibilidade; não determinam os achados nem as alternativas do plano.

Revisão observada: `70a1ade53`, branch `arq/u2-work`, worktree `/tmp/wt-u2`. As contagens são desta árvore, antes deste arquivo. Nenhuma observação remota foi feita. A leitura efetiva de `config.get`, com `OU_CONFIG_STORE=file`, registrou nesta sessão `forge-events.adapter=github` e `forge-events.log_adapter=control`; `adapter_from_config()` resulta em `RoutingAdapter` sobre `GitHubAdapter`. Isso descreve seleção, não prova execução remota.

**Método e custo:** operação, no censo, é um nome de forja despachado ao adaptador: 18 nomes chamados por consumidores entre os 26 métodos públicos de `ForgeEvents`; os outros 8 são do diário/porta. `read` aparece no percurso do trem como diário, sem virar outra operação de forja. Arquivos e consumidores atravessados são proxies do trabalho de entender e verificar uma mudança; não há medição causal de minutos por raiz. O censo AST percorre `scripts/lib/**/*.py`, exclui `scripts/tests/` e os módulos de adaptador e cliente, e conta as chamadas cujo receptor nomeia a porta (`port`, `self.port`, `role.port(...)`, `reader`, `publisher`, `events`) ou o adaptador alcançado por ela (`port.adapter`, `adapter_from_config()`). Chamadas por `getattr` dinâmico, `**kwargs` ou injeção em teste não entram: é **piso, não teto**. As sondas foram execuções em memória, não execuções de gate, trem, bateria ou suite.

## Findings

1. **Superfície disponível não equivale a requisito de todo fluxo.** O levantamento AST de métodos públicos diretamente definidos contou 24 em `GitHubAdapter` (`scripts/lib/forge_github.py:106`) e 9 em `OriginAdapter` (`scripts/lib/forge_origin.py:57`); 16 existem só no GitHub e 1 só na Origin. No recorte dos demais adaptadores da porta, `MemoryAdapter` e `FileAdapter` têm 4 métodos públicos e `RoutingAdapter` tem 4, dos quais `append`, `read` e `recent` são de log e `route` é de roteamento (`forge_events.py:88,116,212`); `BoardAdapter` e `ControlAdapter` têm 3 (`forge_events.py:179`, `forge_control.py:22`). `GitRefs` (`forge_git_ref.py:40`) não é adaptador da porta: é o cliente de refs que o adaptador Origin e o log git-ref usam, com 8 métodos públicos (`url:62`, `read:65`, `tip:79`, `log:85`, `advance:107`, `append:127`, `merge`, `read_tip`). São superfícies de objetos com funções de diário e auxiliares, não 24 requisitos universais. A porta tem 26 métodos públicos, dos quais 18 são operações de forja (`forge_events.py:317`; contagem AST das classes). Das 18 operações efetivamente chamadas, apenas 5 estão na superfície de 9: `change`, `open_changes`, `merge`, `approvals`, `set_status`; 13 não estão (conferência de conjuntos contra os 9 nomes do `OriginAdapter`). A diferença de superfície só ganha significado diante do consumidor.

2. **A porta admite o adaptador sem declarar o que ele atende.** `ADAPTERS` é um dicionário de construtores (`scripts/lib/forge_events.py:174-176`), não uma tabela de operações. `_operation` faz `getattr(self.adapter, name, None)` em tempo de chamada e só então produz a falta nomeada (`:453-457`). `change` chama `self.adapter.change` diretamente, sem `_operation` (`:459-460`). `RoutingAdapter.__getattr__` encaminha qualquer nome ao `main` (`:257-258`), sem lista de capacidades. A fábrica escolhe por configuração e pode compor o roteador quando porta e log diferem (`:261-278`); nenhuma dessas estruturas declara quais operações cada adaptador atende. Seleção aceita e compatibilidade do fluxo continuam propriedades distintas. Raiz R1.

3. **O requisito efetivo está disperso pelos consumidores.** O censo registrou 18 operações, 38 sites e 14 arquivos consumidores (censo AST dos consumidores); os caminhos abreviados na tabela são relativos a `scripts/lib/`. `change` concentra 12 sites em 7 consumidores e `open_changes`, 4 em 4. Doze operações — `approvals`, `change_commits`, `find_change`, `open_change`, `close_change`, `comment`, `upsert_comment`, `set_status`, `calls`, `pushes`, `lock` e `unlock` — têm um único consumidor cada; `open_pulls`, `merge`, `pull` e `comments` têm dois. `lock`/`unlock` aparecem somente em `engine_role.py`; `set_status`/`upsert_comment`, somente em `gate_status.py`. Isso mede dispersão de chamadas reconhecidas, não independência operacional dos arquivos.

   | Operação | Sites | Consumidores | Arquivo:linha |
   |---|---|---|---|
   | `change` | 12 | 7 | `gate_report.py:96`, `gate_report.py:118`, `gate_status.py:156`, `pr_ready.py:67`, `service_runner.py:149`, `train.py:181`, `train.py:210`, `train.py:497`, `train_queue.py:153`, `train_verdict.py:232`, `train_verdict.py:261`, `train_verdict.py:511` |
   | `open_changes` | 4 | 4 | `defect_router.py:38`, `stall_report.py:71`, `train_queue.py:140`, `train_verdict.py:231` |
   | `open_pulls` | 2 | 2 | `flow_check.py:101` (direto no adaptador), `prepush.py:437` |
   | `merge` | 2 | 2 | `train.py:477`, `train_verdict.py:499` |
   | `approvals` | 1 | 1 | `train.py:197` |
   | `pull` | 2 | 2 | `replay_branch.py:86`, `stall_report.py:40` |
   | `change_commits` | 1 | 1 | `replay_branch.py:89` |
   | `find_change` | 1 | 1 | `replay_branch.py:128` |
   | `open_change` | 1 | 1 | `replay_branch.py:131` |
   | `close_change` | 1 | 1 | `replay_branch.py:134` |
   | `comment` | 1 | 1 | `replay_branch.py:133` |
   | `upsert_comment` | 1 | 1 | `gate_status.py:317` |
   | `set_status` | 2 | 1 | `gate_status.py:312`, `gate_status.py:345` |
   | `comments` | 2 | 2 | `lessons.py:349`, `stall_report.py:57` |
   | `calls` | 1 | 1 | `train.py:609` |
   | `pushes` | 1 | 1 | `stall_report.py:41` |
   | `lock` | 2 | 1 | `engine_role.py:133`, `engine_role.py:155` |
   | `unlock` | 1 | 1 | `engine_role.py:161` |

   A matriz por arquivo do censo e a conferência de conjuntos contra os 9 nomes do `OriginAdapter` mostram compatibilidade integral da superfície censada em 6 arquivos e falta em 8. Isso não certifica o fluxo composto: `train_queue` e `train_verdict` cabem nas 9 operações, mas o papel do trem depende também de `engine_role`. Raiz R2.

4. **O trem alcança 8 nomes, e a primeira barreira é coordenação do papel.** A cadeia `Train` → `Verdicts` → `LockedRole` (`scripts/lib/train.py:133`) alcança `lock`, `unlock`, `change`, `open_changes`, `read`, `merge`, `approvals` e `calls` (opcional), não quatro. O laço e a renovação tomam `lock` e liberam `unlock` em `engine_role.py:133,155,161`; a aquisição antecede qualquer operação de fila. Os demais percursos estão em `train.py:181,184,197,477,609`, `train_verdict.py:231,232,499` e `train_queue.py:140,153`, conforme o censo do achado 3. `calls` contabiliza REST do próprio motor, com ausência tratada como opcional (`train.py:609-611`).

   `approvals` está morto hoje no caminho desta configuração: a leitura de `units/*/unit.json` por `python3 -c` encontrou 47/47 manifestos com `owner=engine-lane`, 47/47 sem chave `lane` e 0 com campo `contract`. `train_ownership.py:82-100` só avalia a chamada quando há unidade estrangeira; a comparação usa `manifest.get('lane', manifest.get('owner'))` (`:95`). A lane vem de `pr.ready` (`train_queue.py:51`, `pr_ready.py:37-45`). Isso não prova que nunca possa ser chamada: lane estrangeira ou `lane_id=None` muda o caminho. Presença no contrato não equivale a exercício pelo fluxo atual. Raízes R2 e R3.

5. **O gate atravessa o adaptador diretamente e exige mais que a superfície de 9.** `scripts/lib/gate_report.py:96,118` chama `port.adapter.change`; `gate_status.py:156` chama `publisher.port.adapter.change`. É reach-through com guardas diferentes: `ForgeEventsError` em `gate_report.py:95-98`, `Exception` em `:123` e em `gate_status.py:155-158`. O gate também chama `set_status` (`gate_status.py:312,345`), `upsert_comment` (`:317`) e publica pelo diário (`gate_report.py:100`). Na comparação da superfície de 9, **o gate falha em `upsert_comment`** (conferência de conjuntos: `upsert_comment` não está nas 9); isso não é relato de execução de gate. Antes de a porta existir no processo, `scripts/gate-local:126,190` obtém identidade do PR pelo shim `github_cli`, um acesso do baseline. Nem o caminho de publicação nem o de identidade se resumem à interface nominal da porta. Raízes R1, R2 e R4.

6. **A falta de operação resulta em falha clara, falha confusa ou silêncio, conforme o percurso.** As sondas em memória foram executadas com `OU_CONFIG_STORE=file`, sobre dublês e sobre o `OriginAdapter` real com cliente injetado. Não foram execução do trem nem do gate. O dublê `Nine` atravessou a porta em `change`, `open_changes`, `approvals`, `merge`; as ausências produziram exatamente:

   ```text
   ForgeEventsError: the Nine has no open_pulls operation
   ForgeEventsError: the Nine has no pull operation
   ForgeEventsError: the Nine has no lock operation
   ForgeEventsError: the Nine has no comments operation
   ForgeEventsError: the Nine has no calls operation
   ```

   É falha clara quanto ao objeto e ao nome ausente, mas tardia. Sem `change`, a mesma fronteira produziu `AttributeError: 'Bare' object has no attribute 'change'`; essa exceção não é capturada por `gate_report.py:97`. Com roteador, a mensagem foi `ForgeEventsError: the RoutingAdapter has no open_pulls operation`: nomeia o roteador, não o adaptador incompleto. São falhas confusas quanto à fronteira e à identidade responsável. O `OriginAdapter` real com cliente injetado respondeu `change`, `open_changes` e `approvals`; `read_window` encontrou `ControlError: no events token: set $TOWER_EVENTS_TOKEN`; `open_pulls`, `upsert_comment`, `calls` e `lock` tiveram `ForgeEventsError` nomeado. A sonda do caminho de entrada do trem parou em `ForgeEventsError: the OriginAdapter has no lock operation`, antes de qualquer operação de fila. Não demonstra Origin em execução remota.

   Há também absorção da falha. `flow_check.py:101` chama o adaptador fora da porta; `try/except Exception` em `:110-113`, incluindo `:112`, degrada para `pulls=None`. `prepush.py:437` chama pela porta, mas `overlap_part` em `:490-502` transforma qualquer exceção em `overlap: skipped (...)` e devolve 0. `gate_report.py:95-98` não pega o `AttributeError`, enquanto `gate_status.py:155-158` o silencia; a publicação pode imprimir `gate status: not published` (`:390-391`). `train.py:609-611` devolve `None` para `ForgeEventsError` do medidor opcional. Silêncio de metadado, aviso omitido, publicação não realizada e medidor ausente têm efeitos diferentes; ausência de interrupção não demonstra compatibilidade. Raízes R1 e R3.

7. **O baseline reúne 13 acessos de naturezas diferentes, sem registrar essa distinção.** A lista é `scripts/lib/adapters/engine-vendors.json:29-43`; as razões abaixo foram lidas no código, uma a uma. A coluna de operação distingue REST, shim e acesso que não é tráfego de forja; não atribuo a todos uma API inexistente. Os caminhos `*.py` abreviados são de `scripts/lib/`.

   | Natureza | Entrada e quem chama | Operação observada e razão de estar fora da porta |
   |---|---|---|
   | Hospedagem de artefato | `toolchain_manifest.py:github.com`, `:223,231,235,239,244` | URLs de releases de python-build-standalone, pnpm, cli/cli, gitleaks e postgresql-binaries; distribuição de binários, não operação REST de forja. |
   | Sonda de credencial | `credentials.py:github_api`, `:142-146,175` | `github_api.ping()`, `GET /user`; antecede o store de eventos, que depende da credencial. Passar por esse store fecharia um ciclo. |
   | URL de origem | `release_policy.py:github_api`, `:66-68` | `github_api.api_base()`, sem requisição REST nesse acesso; identifica o host real para a recusa de produção congelada. A porta não expõe essa URL; o análogo Origin usa `self.refs.url()` em `forge_origin.py:139`. |
   | Listagem histórica | `idea_to_prod.py:github_api`, `:28,39` | `GET /pulls?state=closed` e `GET /issues/{n}/comments`; busca PRs mergeados com trailer `Capability:`. A porta não tem listagem histórica por estado. |
   | Dado que a forma da porta omite | `commit_check.py:github_api`, `:231-238` | `GET /pulls/{n}`, `GET /pulls/{n}/commits`, `GET /compare/{base}...{sha}`; julga commits e merge-base. `change` não entrega lista de commits ou merge-base (`forge_github.py:352-360`); a porta não oferece `compare`. |
   | Dado que a forma da porta omite | `delivery.py:gh`, `:48-49` | `gh pr view --json state,headRefOid,baseRefName,mergeCommit,body`; a consulta inclui `mergeCommit`, ausente na forma de `port.pull` (`forge_events.py:481-483`). |
   | Dado que a forma da porta omite | `structure.py:github_api`, `:140-142,659` | `fetch_review`, com body, head sha e `github_api.issue_comments`, em `--review`. `issue_comments` só existe no GitHub (`forge_github.py:525`) e devolve `IssueComments` (`:585`), não a lista de `comments` (`:529`). |
   | Versão de CLI | `scripts/cloud/setup.sh:gh`, `:176` | `gh --version`; verifica a versão fixada na instalação da nuvem, sem operação REST de forja. |
   | Import de módulo | `delivery.py:github_cli`, `:8` | `from github_cli import parse_json, run_gh`; import do shim, sem requisição REST nesse acesso. |
   | Import de módulo | `gate_policy.py:github_cli`, `:11` | `from github_cli import parse_json`; import do shim, sem requisição REST nesse acesso. |
   | Identidade antes da porta | `scripts/gate-local:github_cli`, `:126,190` | `pr view --json headRefOid` em `driver_abort` e `pr view --json headRefOid,baseRefOid`; bash obtém sha/base antes de existir módulo Python da porta no processo e alimenta `gate_report`. |
   | Identidade antes da porta | `gate_policy.py:gh`, `:82-87` | `pr view --json baseRefOid,headRefOid` em `classify_pr`, chamado por `scripts/gate-local:371`. O oid não é dado distinto do `base` sha de `change`; o acesso ocorre sem porta no percurso do bash. |
   | Body/files | `premises.py:github_api`, `:413-414,492-493` | `GET /pulls/{n}` em `fetch_body` e `github_api.pull_files` em `fetch_pr`; lê body sem porta e lista de arquivos, que ela não expõe. O docstring ainda promete substituição pela porta em M2. |

   `vendor_check.py:134-151,167-184` compara conjuntos e recusa crescimento: só sabe que a lista encolhe. A contagem reúne distribuição, bootstrap, consultas com forma ausente e acessos operacionais sem porta; não mede uma dívida homogênea nem explica por si a permanência de cada entrada. Raiz R4.

8. **Há acessos ao GitHub dentro do módulo da porta e da construção do store fora desse baseline.** `scripts/lib/forge_events.py:285` fixa `ADAPTERS['github']().issue_comments` em `board_adapter`, independentemente de `forge-events.adapter`. `config.py:321-334` constrói o adaptador diretamente com `forge_events.ADAPTERS[store_kind(root)]()` (`:329`), sem `RoutingAdapter`; `:341` lê `target.port.adapter.remote` para decidir cache. Esses caminhos não estão nas 13 entradas e escolhem adaptador sem passar pela seleção da porta principal. Não atribuo execução ao board: a leitura de configuração registrou `forge-events.board_issue=0`; registrou também `config.store_adapter=github`. Trocar a seleção principal não descreve sozinho essas escolhas.

9. **A documentação e o contrato descrevem superfícies diferentes, sem requisito declarado por fluxo.** `docs/architecture/PORTS.md:13` lista 3 nomes (`append`, `read`, `change`); o docstring de `scripts/lib/forge_events.py:7-17` lista 5 (`remote`, `append`, `read`, `recent`, `change`). `scripts/tests/forge_events/test_forge_contract.py:1-3` anuncia 8 operações: `change`, `identity`, `append`, `read`, `set_status`, `merge`, `open_changes`, `approvals`; os casos estão em `:35-66`, com contratos GitHub e Origin em `:121,184`. Das 18 operações chamadas pelos consumidores, 13 estão fora desse contrato (conferência de conjuntos contra as 8 do contrato). `identity` não tem site consumidor de forja no censo; `append`/`read` são diário. O contrato existente verifica um subconjunto compartilhado, não a demanda integral dos fluxos.

   `docs/architecture/ENGINE-OPERATIONS.md:16-29` registra uma tabela de 12 operações e uma matriz em `:49-55`, com limites de prova em `:73-81`; sua linha `:24` ainda diz `log_adapter=github`, enquanto o registry declara `default: control` (`config/registry/forge-events.json:443-451`) e a leitura desta sessão devolveu `control`. `units.unit_of('docs/architecture/ENGINE-OPERATIONS.md')` retorna `None`. Nenhum código ou verificador o lê; suas referências são `docs/domain/decisions/D-284.md:7`, `docs/domain/DECISIONS.md:268` e `docs/units/ARQ-SISTEMA/plan.md:85`. O documento comunica o remendo escolhido, mas não constitui declaração executável de requisito nem pertence a uma unidade. Raiz R2.

**O que esta auditoria não mediu:** não rodou gate, trem, bateria nem suite; as provas são leituras e sondas em memória. Não mediu tempo humano nem custo causal em minutos; não conferiu produção, GitHub remoto ou Origin em execução. O censo é piso pelas exclusões de chamadas dinâmicas, `**kwargs` e injeção em teste. Seu universo é `scripts/lib` desta revisão; `services/` e `scripts/cloud/` não foram censados operação a operação. A classificação de uma entrada de bootstrap não amplia esse universo.

## Causas raiz

### R1. A fronteira aceita qualquer superfície e só descobre a incompatibilidade na chamada

Cadeia de porquês:
1. Por que um fluxo pode receber adaptador sem uma operação que chama? A seleção não pergunta ao adaptador quais operações ele atende.
2. Por que a seleção não faz essa pergunta? Não há declaração de operações a consultar; `ADAPTERS` registra construtores.
3. Por que a ausência só aparece durante o uso? A operação existe como nome no ponto de chamada, procurado por `getattr` em `_operation`; `change` ainda passa diretamente ao objeto.
4. Por que a fábrica aceita esse objeto sem demonstrar compatibilidade? O adaptador é um objeto passado à fábrica, cuja escolha se dá por chave de configuração, não por capacidade.
5. Por que a capacidade não participa dessa fronteira? O desenho da porta trata a forja como armazenamento mais um punhado de métodos opcionais, sem lugar onde a capacidade seja um dado. A incompatibilidade permanece uma propriedade descoberta pelo consumidor.

Classe: mecanismo faltando

Evidência: achados 2 e 6; `scripts/lib/forge_events.py:174-176,257-278,453-460`; erros de `Nine`, `Bare` e `RoutingAdapter` transcritos no achado 6.

Custo em tempo de mudança (proxy): superfícies de 24 e 9 métodos confrontadas nos sites de uso; a recusa depende do percurso e da guarda. Sem duração medida.

### R2. Nenhum fluxo declara as operações que exige, e o contrato verificado é o subconjunto que os dois adaptadores já implementam

Cadeia de porquês:
1. Por que o contrato não demonstra compatibilidade de todos os fluxos? Não é derivado dos consumidores; 13 das 18 operações chamadas ficam fora dele.
2. Por que as exigências dos consumidores não delimitam o contrato? Nenhum fluxo declara as operações que exige.
3. Por que a exigência precisa ser reconstruída a cada análise? Ela aparece dispersa em 18 operações, 38 sites e 14 arquivos, inclusive chamadas diretas ao adaptador e exigências herdadas pelo papel.
4. Por que essa dispersão não aparece como obrigação do fluxo na porta? A porta expõe métodos soltos, sem agrupamento por fluxo; ter um método disponível não declara quem depende dele.
5. Por que o contrato existente deixa essa diferença aberta? A prova foi escrita à mão para os adaptadores existentes e mede o subconjunto que têm em comum, não o que os fluxos pedem. A regra controlada hoje não vincula requisito do consumidor e cobertura verificada.

Classe: regra faltando

Evidência: achados 3, 5 e 9; censo AST e conferência de conjuntos descritos em Entradas; `scripts/tests/forge_events/test_forge_contract.py:1-3,35-66,121,184`; `scripts/lib/train.py:133`, `scripts/lib/engine_role.py:155`.

Custo em tempo de mudança (proxy): 18 operações em 38 sites e 14 arquivos; 13 fora do contrato. Sem duração medida.

### R3. A coordenação de papel (lock) e a contabilidade de chamadas moram no adaptador de forja

Cadeia de porquês:
1. Por que o trem não inicia em adaptador sem `lock`? A aquisição ocorre antes de qualquer operação de fila.
2. Por que a aquisição depende da superfície da forja? O laço do papel toma o lock pela porta, em `engine_role.py:155`, com renovação e liberação pela mesma fronteira.
3. Por que a porta transfere essa dependência ao adaptador? `_operation('lock')` despacha ao objeto selecionado, como as demais operações de forja.
4. Por que isso alcança outros papéis além do trem? `LockedRole`, `train`, `planner_role` e `battery` herdam a mesma exigência de forja para exclusão mútua entre papéis do próprio motor, em vez de uma necessidade particular de operação de PR.
5. Por que uma necessidade do motor ficou nessa superfície? A porta nasceu como diário mais operações de PR e a exclusão mútua entrou ali por conveniência, sem outro lugar onde papel e lease possam viver. A fronteira mistura operação da forja e coordenação do motor; `calls`, contabilidade REST do próprio motor em `train.py:609`, é outro exemplo da mesma classe, embora opcional.

Classe: arquitetura/desenho

Evidência: achados 4 e 6; `scripts/lib/train.py:133,609-611`, `scripts/lib/engine_role.py:101,110,133,155,161`; sonda em memória do `OriginAdapter` real interrompida por `ForgeEventsError: the OriginAdapter has no lock operation` antes da fila.

Custo em tempo de mudança (proxy): os 8 nomes do percurso do trem incluem coordenação e contabilidade; ausência de lock bloqueia até os consumidores cuja superfície cabe nas 9 operações. Sem duração medida.

### R4. O baseline trata treze acessos de naturezas distintas como uma lista única que só encolhe

Cadeia de porquês:
1. Por que cada acesso novo ou mantido exige discussão própria sobre sua relação com a porta? O baseline não distingue a natureza dos acessos nem a razão de permanecerem fora dela.
2. Por que a lista não oferece essa distinção? Registra caminho:token, não a natureza do acesso ou o dado que a forma da porta omite.
3. Por que o verificador não produz essa distinção? `vendor_check.py:134-151,167-184` compara conjuntos e recusa crescimento, sem classificar o motivo de cada entrada.
4. Por que essa regra deixa acessos tão diferentes sob o mesmo sinal? A regra existente é que a lista só encolhe; protege contra regressão, mas não distingue dívida de exceção justificada.
5. Por que a monotonicidade tomou o lugar dessa distinção? A forja nunca teve uma classificação de acesso que separe tráfego de forja, hospedagem de artefato, sonda de credencial e leitura de dado que a forma da porta omite. A regra controlada representa quantidade de exceções, não sua semântica.

Classe: regra faltando

Evidência: achado 7; `scripts/lib/adapters/engine-vendors.json:29-43`, `scripts/lib/vendor_check.py:134-151,167-184`; classificação por código no achado 7, incluindo `scripts/lib/credentials.py:142-146,175`, `scripts/lib/toolchain_manifest.py:223,231,235,239,244` e `scripts/lib/premises.py:413-414,492-493`.

Custo em tempo de mudança (proxy): 13 entradas de naturezas distintas a reinterpretar; a redução da lista não mede sozinha o alcance da substituição. Sem duração medida.

## Distância do estado da arte

Contra [research.md](research.md), já temos porta única, seleção por chave, adaptadores intercambiáveis para subconjuntos reais e um contrato executável de 8 operações (`scripts/lib/forge_events.py:174-176,261-278`; `scripts/tests/forge_events/test_forge_contract.py:1-3`). Há separação implementada entre seleção e parte do comportamento verificado; não há prova de equivalência integral. Faltam declaração de capacidade, requisito por fluxo, recusa na construção e classificação das exceções. A fábrica aceita uma seleção que só será confrontada com o requisito durante a chamada; o contrato não cobre 13 das 18 operações censadas.

A pesquisa distingue especificação e implementação de hooks em pluggy, pendências abstratas em abc e descoberta versus habilitação em stevedore. Presença estrutural e seleção explícita não demonstram comportamento equivalente. abc e pluggy não resolvem sozinhos esta distância: nenhuma das referências elimina os acessos fora do adaptador, e a lista de exceções mistura razões que não são ausência de método. Essa comparação não escolhe ferramenta ou desenho.

Estamos no **degrau 1 da escada**, alcance e limites da compatibilidade documentada: o recorte agora distingue superfície, chamada, contrato, guarda de erro e acesso externo, sem certificar execução remota. A pesquisa não autoriza trocar adaptador. A2 continua uma ambição citada na entrada, não uma arquitetura decidida por esta auditoria.

## Base defects expected

- `KD-3ec4be1f` está aberto, dono `engine-lane`, unidade `engine-config` (`docs/process/defects/scripts-tests-config-test-sh-3ec4be1f.yml:2-13`).
- `KD-024bbecb` e `KD-4db6e693` estão resolvidos no registro de defeitos da base. Nenhum desses defeitos foi reproduzido nesta auditoria; registro de base não equivale a execução de teste.
- `docs/architecture/ENGINE-OPERATIONS.md` não tem unidade dona: `units.unit_of('docs/architecture/ENGINE-OPERATIONS.md')` → `None`, verificado nesta árvore. É fato de atribuição documental observado no achado 9, não defeito aberto registrado.

Premises: none
