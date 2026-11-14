# R1 — audit

## Entradas
- docs/units/R1/intake.md (the real problem: a red base must hold merges while the regime is on)
- docs/units/R1/research.md (the reference: admission gated by the result on the tip; a red trunk stops it)

## Findings
1. The base was red for about three hours with no alarm. RC-005 (docs/process/rule-challenges/RC-005.md, on the base): red from 10:52 to about 14:20 BRT; every PR gate and the train's tier 2 read green; the first real measurement, `scripts/gate-shadow run` on 3d641027 at 14:05 BRT, failed in the script tests stage.
2. The train's merge decision does not read the base's real state. `Train.merge` (scripts/lib/train.py:439-470) checks that the base did not move and that the merged tree equals the tested tree, then emits `pr.merged`. Its only red reaction is the batch's own verdict: `train.batch.red` and `halt` (scripts/lib/train.py:425-430).
3. Under the regime the batch verdict is green without running anything: docs/operations/gate-bypass.md, "What is green at once": the train's tier 2 is green without running a command.
4. The real gate on the base is measurement only. `scripts/lib/train_loop.py:35-38` starts `gate-shadow run HEAD` detached, "for measurement only ... the loop never waits for it". docs/operations/gate-bypass.md: `gate-shadow` runs "with the bypass off and no events or records" and "It never blocks a merge". Its result is written to `.gate/shadow/<sha>.json` on the host that ran it.
5. Merges happened while no real result existed for the tip: `scripts/lane-status` at 14:40 BRT printed "base: no shadow gate result yet", and the train merged #1026 (14:24 BRT), #936 (14:27), #933 (14:30), #1027 (14:37), #932 and #980 (14:4x) in that window (`scripts/service status`, merged list).
6. The train runs on another host: the lock holder is `train@grok-bot-vm-301145804:…` (`scripts/service status`, 14:40 BRT). The lane container cannot read its `.gate/shadow` or its loop flags.
7. The state shared between hosts is three refs and the forge's events: `refs/heads/train/lock`, `refs/heads/train/wake`, `refs/heads/train/probe-*` (`git ls-remote origin 'refs/heads/train/*'`). No ref or event carries the real result of a base tip.

## Causas raiz

### R1. The base's real-gate state is not an input of a merge while the regime is on
Cadeia de porquês:
1. Por que a base ficou vermelha por cerca de três horas sem bloquear nenhum merge? Porque os gates de PR e o tier 2 liam verde sob o bypass, e o único gate real da base era o shadow, que não bloqueia (Findings 1, 3, 4).
2. Por que nenhum merge consultou o estado real da base? Porque `Train.merge` decide só pelo veredito do lote e pela árvore do tip (Finding 2).
3. Por que o estado real da base não é entrada do merge? Porque a regra do regime trata o gate real da base como medição, que "never blocks a merge" (Finding 4).
4. Por que essa regra não tem contrapartida de admissão? Porque o desenho do bypass (D-151) cuidou da velocidade do gate de PR e não listou o estado da base como condição de merge; nenhuma regra torna a base verde pré-condição de merge enquanto o bypass estiver ligado.
5. Por que nenhuma regra foi escrita? Porque o regime foi concedido por uma decisão de velocidade (D-151, D-260) e o efeito sobre a base vermelha só apareceu como incidente (RC-005). A falha é do sistema de regras: uma concessão de regime não obriga a declarar quais verificações continuam sendo entradas do merge.
Classe: regra faltando
Evidência: docs/process/rule-challenges/RC-005.md; docs/operations/gate-bypass.md ("It never blocks a merge"); scripts/lib/train.py:439-470.

### R2. A real-gate result of a base tip is visible only on the host that ran it
Cadeia de porquês:
1. Por que o train não pode consultar o resultado do gate real da base? Porque o resultado é gravado em `.gate/shadow/<sha>.json` no host que rodou o shadow (Finding 4).
2. Por que o resultado fica nesse host? Porque o shadow é um comando local que não grava nada compartilhado: "no events or records" (docs/operations/gate-bypass.md).
3. Por que não grava nada compartilhado? Porque o shadow foi desenhado para o `lane-status` ler na própria lane (D-151), não para o train decidir a partir dele.
4. Por que o train não tem outro canal para o estado da base? Porque o estado da base não é um registro do fluxo: o forge guarda eventos de gate de PR e do train (`gate.passed`, `pr.ready`, `pr.merged`), e o estado compartilhado do train são refs (`train/lock`, `train/wake`), sem nenhum ref ou evento para o tip da base (Finding 7).
5. Por que o estado da base ficou fora dos registros compartilhados? Porque a separação "medir" (lane) e "decidir" (train) foi feita sem um lugar comum para o resultado de cada tip; o desenho assumiu um só host. A falha é de arquitetura: o resultado de um tip não tem dono compartilhado.
Classe: mecanismo faltando
Evidência: scripts/lib/train_loop.py:35-38; `scripts/lane-status` at 14:40 BRT, "base: no shadow gate result yet"; `git ls-remote origin 'refs/heads/train/*'`.

## Distância do estado da arte
We have a per-batch verdict and a check that the tip did not move: the first rung of a merge queue. We lack the base's real state as an admission input (SubmitQueue, GitHub and GitLab merge queues) and a shared result per tip (CI results keyed by sha). Against research.md's ladder we are on rung 0 without its input: a red published result does not hold a merge. This unit reaches rung 0 of the ladder as research.md defines it.

## Base defects expected
- KD-3ec4be1f (scripts/tests/config.test.sh, open, owner engine-lane): may show in the script tests of this unit; not reproduced in this session.
- The lane-ship conflict stop (RC-006): if the base moves over a plan.md the unit touches, a lap stops for a person (#962 is stuck in docs/programs/fluxo-amplo/plan.md).
