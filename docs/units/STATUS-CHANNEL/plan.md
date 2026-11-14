# STATUS-CHANNEL — plan

## Alternativas

### R1. The delivery contract declares a status channel of its own
Classe: arquitetura/desenho; evidência: auditoria R1/F1/F3/F4/F9. O contrato de entrega de `AGENTS.md` diz como um
delivery é registrado, e a sessão o obedece acima do brief.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Apagar só a frase ofensora de `AGENTS.md` | remendo | Não; a seção `## Storage in the forge` de `EVENTS.md` continua dizendo que os eventos são comentários de PR | 5 min | Reverter uma linha | A sessão perde a instrução de progresso e não ganha nenhuma: passa a inventar um canal | 0 |
| A2 Trocar as duas frases pela regra do diário, nomeando o comando e o que o PR carrega | corrige a classe | Sim para as duas ocorrências medidas: nenhum texto de entrega nomeia comentário de status | 25–40 min | Reverter os dois arquivos | Nomear mal o comando ou o adapter: a regra passa a apontar para um caminho que não existe | 1 |
| A3 Gerar o contrato de entrega a partir do registro | redesenho | Sim, e impede a deriva futura; exige um gerador novo e a migração de `AGENTS.md` para um template | 180–300 min | Reverter gerador e template juntos | Um gerador para um arquivo de 200 linhas é custo sem segunda instância; o contrato deixa de ser legível como prosa | 3 |

A2 mantém `AGENTS.md` como prosa legível e troca só a frase que nomeia o canal, sem tocar nas outras regras do bullet.
A ordem de Daniel é textual: o diário é o único canal de status; A2 a escreve onde a sessão lê.

### R2. The event contract describes the storage of an adapter the registry no longer selects
Classe: mecanismo faltando; evidência: auditoria R2/F2/F3/F5/F7. A seção `## Storage in the forge (v0)` é prosa sem campo
declarado que nomeie o adaptador que descreve.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Corrigir a prosa sem nomear chave, endpoint e variável | remendo | Não; a próxima troca de `log_adapter` deixa a seção velha outra vez, agora sem âncora para conferir | 10 min | Reverter a seção | A descrição volta a envelhecer em silêncio | 0 |
| A2 Reescrever a seção com os nomes que o código lê (chave, endpoint, variável do token) e o modo legado explícito | corrige a classe | Sim para o leitor: cada afirmação da seção é conferível contra o registro e `forge_control.py` | 30–45 min | Reverter a seção | Descrever um mecanismo que o código não tem; mitigado por ler `forge_control.py` e o registro antes de escrever | 1 |
| A3 Gerar a seção a partir de `config/registry/forge-events.json` | redesenho | Sim; a seção deixa de poder divergir | 120–200 min | Reverter gerador e seção | Um gerador para uma seção de prosa; o adapter legado ainda precisaria de texto à mão | 3 |

A2 usa os nomes exatos do registro (`forge-events.log_adapter`, `service.control_url`, `forge-events.control_token_env`)
e os erros reais de `ControlAdapter._call`, para que a seção seja falsificável linha a linha.

### R3. The rule that governs sessions has no refusing check
Classe: regra faltando; evidência: auditoria R3/F1/F2/F8. Nenhum teste afirma nada sobre as duas frases.

| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Não afirmar nada; confiar na revisão | remendo | Não; a frase volta na próxima reescrita do bullet, como voltou em `77f2eaae9` | 0 min | — | A deriva é inobservável: o dono descobre apagando comentários | 0 |
| A2 Um teste na suíte de contratos de evento que lê os dois arquivos e recusa as duas frases, com `AGENTS.md` no manifesto de cobertura | corrige a classe | Sim para estas duas frases: a suíte já lê `EVENTS.md` e já é dona dos dois arquivos que o teste toca | 20–30 min | Reverter o teste e a linha do manifesto | Um teste de texto é lexical: recusa a frase medida, não qualquer paráfrase futura | 1 |
| A3 Uma regra do `structure-check` sobre todo documento que nomeie canal de status | redesenho | Sim em alcance; exige arquivo de gate e, pela regra do gate, um `D-NNN` aprovado | 90–150 min | Reverter a regra do gate | Uma heurística sobre prosa livre gera falso positivo em documento histórico e bloqueia PR alheio | 3 |

A2 é a menor afirmação que torna a deriva observável hoje, no dono que já cobre `docs/process/EVENTS.md`. A3 fica
refusada: um verificador de prosa livre sobre todo o repositório custa mais do que a segunda instância justifica.

## Escolha

- R1 → A2: resolve as duas ocorrências medidas ao custo de dois arquivos de prosa, com reversão trivial; A1 deixa a segunda ocorrência viva e A3 paga um gerador por um arquivo só. Degrau 1.
- R2 → A2: torna cada afirmação da seção conferível contra o registro e o código, desfaz-se revertendo a seção; A1 volta a envelhecer e A3 gera prosa que ainda precisaria de texto à mão para o modo legado. Degrau 1.
- R3 → A2: afirma as duas frases onde a suíte já lê `EVENTS.md`, sem arquivo de gate e sem decisão nova; A1 deixa a regra sem prova e A3 amplia o alcance a prosa livre. Degrau 1.

## Commits

Esta seção é o checklist que `scripts/pr-ready` lê: o plano do PR em `- [ ] N.`, como em `docs/units/GX22/plan.md`, e o
tick é derivado dos trailers `Plan: N` dos commits, nunca escrito à mão (`scripts/plan-tick`, D-065 V4). Assim
`scripts/pr-ready --pr <n> --body docs/units/STATUS-CHANNEL/plan.md` acha o plano que o corpo do PR repete.

- [ ] 1. `docs/units/STATUS-CHANNEL/{intake,research}.md` — o pedido e a pesquisa.
- [ ] 2. `docs/units/STATUS-CHANNEL/audit.md` — as três raízes.
- [ ] 3. `docs/units/STATUS-CHANNEL/plan.md` — este plano.
- [ ] 4. `AGENTS.md` — a regra do diário no lugar da frase do comentário.
- [ ] 5. `docs/process/EVENTS.md` — a seção de armazenamento no presente do adapter de controle.
- [ ] 6. `scripts/tests/test_event_contracts.py` e `scripts/tests/covers/event-contracts.json` — o teste que recusa as duas frases.
- [ ] 7. `docs/units/STATUS-CHANNEL/plan.md` — esta seção como checklist, para o comando de `pr.ready` documentado.
- [ ] 8. `docs/units/STATUS-CHANNEL/plan.md` — esta seção, com a lista de `docs/padrao/v8` como o único resto medido do mesmo canal.

Sem paralelo: cada commit depende do anterior (o plano lê a auditoria, os dois textos seguem o plano, o teste afirma os
dois textos, o item 7 lê o próprio plano). Nenhum arquivo é dono de dois commits.

## Premises

Premises: none.

## Tests

- Commit 6 roda sozinho: `scripts/tests/event-contracts.test.sh` (`python3 scripts/tests/test_event_contracts.py`).
- `scripts/structure-check` e `scripts/structure-check --pr-body <file>` para o corpo do PR.
- `scripts/units check` e `python3 scripts/lib/test_orphans.py` para a cobertura do teste novo (nenhum arquivo novo de
  teste: a afirmação entra na suíte existente).
- Gate final: `scripts/gate-dev --pr <n>` no head exato, com a bateria de mão, porque D-151 faz o gate não executar
  estágios.

## O resto medido do mesmo canal: o Padrão v8

Depois das duas frases, o mesmo canal de status continua escrito em quatro regras da **versão ativa** do Padrão — que
`coordinator_launch.render_brief` cola literalmente em todo brief de sessão (`## Padrão v8` + `'\n\n'.join(rules)`), então
vale mais que qualquer texto deste PR:

| Arquivo (v8, ativo) | Frase |
|---|---|
| `docs/padrao/v8/decide-then-report.md:3` | "record the decision and its reason in a PR comment" |
| `docs/padrao/v8/think-before-acting.md:3` | "state the choice and why in one line in your PR comment" |
| `docs/padrao/v8/no-probe-prs.md:3` | "record the numbers in your PR comment" |
| `docs/padrao/v8/retro-before-merge.md:3` | "commit docs/units/<unit>/retro.md and post it as one PR comment titled \"RETRO\"" |

Fica fora deste unit de propósito, e não por esquecimento: o Padrão é versionado (`coordinator.padrao_version` = `v8`,
`docs/padrao/v8/padrao.json`) e o manifesto diz que "a change is a new version folder", então corrigir as quatro frases é
uma versão nova (`v9`) mais a troca da chave — decisão de desenho do Padrão, não a correção de duas frases medidas que
Daniel ordenou. Também não há verificador de Padrão (`ls scripts | grep -i padrao` é vazio), então a recusa que este unit
acrescenta não as alcança. O teste deste unit afirma só os dois arquivos medidos; afirmar o Padrão entra com a v9.

## Base defects expected

Nenhum conhecido. `scripts/decision-table --check` já falha em 23 registros sem linha em `DECISIONS.md` (pré-existente,
não deste unit; este unit não adiciona decisão).

## Cheapest useful effort
Action: rewrite the two governing sentences and add the one test that refuses them.
Cost: about 45–70 minutes of session time, no quota spent outside the local gate.
Requirement: Daniel, who ordered on 02/11 ~10:45 BRT that the diary is the only status channel and deleted the STATUS comments twice.
Cheaper rejected: deleting only the AGENTS.md sentence (leaves the storage section telling the same thing, and nothing refuses either); a structure-check rule over all prose (a gate file that needs an approved decision and cannot judge free text without false positives).
