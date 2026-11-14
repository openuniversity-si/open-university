# STATUS-CHANNEL — audit

## Entradas
- [intake.md](intake.md): Daniel's order that the diary is the only status channel, and the two measured places that
  contradict it.
- [research.md](research.md): the journal as the only status channel, the conditions pattern for the one mutable status
  per head, and rung 1 of the escalade.

## Findings
1. `AGENTS.md:45`, in `## Delivery flow`, ends a bullet with "Each step posts a one-line PR comment." The bullet is the
   canonical statement of how a delivery is recorded, for every coding agent and human.
2. `docs/process/EVENTS.md:189-201`, `## Storage in the forge (v0)`, states "**Events: PR comments.**" and describes the
   GitHub adapter appending one issue comment per `publish`, plus "One one-line comment per batch."
3. `config/registry/forge-events/forge-events.log_adapter.json` has `default: "control"`, and
   `scripts/lib/forge_events.py:302-306` builds a `RoutingAdapter` whose `default` journal is that adapter: every event
   kind not routed elsewhere is appended to the control plane, not to a comment.
4. `scripts/lib/forge_control.py:19-45` `ControlAdapter._call` posts to `{service.control_url}/v1/events` with
   `authorization: Bearer <token>`, where the token is read from the environment variable that
   `forge-events.control_token_env` names (`TOWER_EVENTS_TOKEN`); an empty token raises
   `ControlError('no events token: set $TOWER_EVENTS_TOKEN')`, an HTTP error `control plane /v1/events answered <code>`,
   and an `OSError` `control plane unreachable: <e>`.
5. `scripts/lib/forge_events.py:238` `RoutingAdapter.read` with a `default` reads only the routed logs, so the forge's
   comment history is no longer the channel's history once `log_adapter` is set.
6. `scripts/lib/forge_github.py:3-8` still documents the comment storage, correctly: it is the GitHub adapter's own
   storage, which is what the v0 section described and what no longer runs in production.
7. `scripts/lib/gate_status.py:1-6` publishes one live stage table comment per PR head and mode, found again and edited
   in place, never duplicated: the PR thread already carries the only status a reader needs.
8. No test asserts on either sentence: `grep -rn "Each step posts" scripts/tests` is empty, and the only assertion on
   `docs/process/EVENTS.md` reads the `## Events` table between `## Events` and `## The port`
   (`scripts/tests/test_event_contracts.py:98`), a section this change does not touch. `scripts/tests/covers/
   event-contracts.json` names `docs/process/EVENTS.md`; no covers manifest names `AGENTS.md`.
9. `git log -S "Each step posts a one-line PR comment"` puts the sentence in `77f2eaae9` ("Remove the delivery-tail
   checkpoint that wrote PROGRESSO.md"): the retired progress file was replaced by a per-step comment, and the event
   contract was not consulted.
10. A **versão ativa** do Padrão diz a mesma coisa em quatro regras, e `coordinator_launch.render_brief` cola essas
    regras literalmente em todo brief de sessão (`scripts/lib/coordinator_launch.py:95`): `docs/padrao/v8/
    decide-then-report.md:3` "record the decision and its reason in a PR comment", `think-before-acting.md:3` "state the
    choice and why in one line in your PR comment", `no-probe-prs.md:3` "record the numbers in your PR comment",
    `retro-before-merge.md:3` "and post it as one PR comment titled "RETRO"". É o mesmo canal, num texto que vale mais
    que este PR; fica fora do escopo dele (plan.md, "O resto medido do mesmo canal").

## Causas raiz

### R1. The delivery contract declares a status channel of its own, so every session posts status where the owner deletes it
Cadeia de porquês:
1. Por que uma sessão postou STATUS num PR aberto? Porque o `## Delivery flow` de `AGENTS.md` diz que cada passo posta
   um comentário de uma linha no PR (finding 1).
2. Por que a sessão obedece essa linha e não o brief? Porque `AGENTS.md` é o contrato que a sessão lê antes de agir e o
   brief é escrito sob ele: o texto do repositório define como um delivery é registrado.
3. Por que o contrato diz isso? Porque a frase entrou em `77f2eaae9` como substituta do `PROGRESSO.md` retirado, uma
   troca local decidida sem perguntar se deveria existir canal de status por passo (finding 9).
4. Por que não foi revista quando o diário mudou? Porque nenhuma regra liga o contrato de entrega ao contrato de eventos:
   trocar `forge-events.log_adapter` não obrigou a rever os textos que nomeiam o canal (findings 3, 4).
Classe: arquitetura/desenho
Evidência: findings 1, 3, 4, 9.

### R2. The event contract describes the storage of an adapter the registry no longer selects, and nothing compares the two
Cadeia de porquês:
1. Por que `EVENTS.md` diz que os eventos são comentários de PR? Porque a seção `## Storage in the forge (v0)` foi
   escrita quando o adaptador GitHub era o único remoto (finding 2).
2. Por que não foi reescrita quando o adaptador de controle assumiu? Porque a troca foi uma chave de registro (D-282) e
   nenhum verificador confronta a descrição documental com `forge-events.log_adapter` (findings 3, 7).
3. Por que nenhum verificador confronta? Porque a seção é prosa sem campo declarado que nomeie o adaptador que descreve,
   então a divergência é inobservável por construção (findings 2, 5).
Classe: mecanismo faltando
Evidência: findings 2, 3, 5, 7.

### R3. The rule that governs sessions has no refusing check, so a stale instruction survives until the owner deletes its effect by hand
Cadeia de porquês:
1. Por que a frase sobreviveu à migração de canal? Porque nenhum teste ou verificador afirma nada sobre o texto de
   `AGENTS.md` ou sobre esta seção de `EVENTS.md` (finding 8).
2. Por que não há afirmação? Porque os dois arquivos são tratados como prosa: os manifestos de cobertura nomeiam código e
   `EVENTS.md` apenas pela tabela de eventos (finding 8).
3. Por que isso é uma regra faltando? Porque uma regra que vive só em prosa e não é afirmada por ninguém decai em
   silêncio, e o dono a descobre apagando comentários à mão (o pedido do intake).
Classe: regra faltando
Evidência: findings 1, 2, 8.

## Distância do estado da arte
A árvore já tem o jornal (`/v1/events` do control plane, D-282) e já tem o status mutável editado no lugar por head
(`gate_status.py`, finding 7): os dois elementos do estado da arte existem. Falta a metade que os liga aos textos que
governam a sessão: as duas seções citadas dizem o contrário do que o código faz, e nenhum verificador as confronta.
Degrau 0 da escalada de [research.md](research.md): a primeira correção dos dois textos e sua recusa.

## Base defects expected
Nenhum conhecido nesta árvore que este unit encontre. `scripts/decision-table --check` já falha em 23 registros sem
linha em `DECISIONS.md` (pré-existente, não deste unit, e este unit não adiciona decisão).
