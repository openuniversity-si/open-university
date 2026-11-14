# BASE-REGIME — audit

## Entradas
- `docs/units/BASE-REGIME/intake.md`: the real problem (the base's whole script suite red since 10:52 BRT) and the metric of "resolved".
- `docs/units/BASE-REGIME/research.md`: hermetic judges pin every ambient state; a queue judges the combined head.

## Findings
1. The whole script suite at the lane head `c5a21e700` (base `3d641027` plus three generated brief files) exits 1: 7 test
   files fail, 10 distinct test names, 43 failing assertions in their unittest summaries. Output of `scripts/test-suite`:
   "141 script tests judged, 134 by key, 7 ran, 7 failed". Log: `scratchpad/suite-main.log`.
2. The real gate on the base tip `3d641027` (`scripts/gate-shadow run`, bypass off) exits 1 after 35.5 s in the stage
   "script tests" (`.gate/shadow/3d64102732cc….json`, `failing: script tests`). An earlier 0.7 s exit 2 came from the train
   checkout having no `.toolchain/` (preflight); `scripts/cloud/setup.sh` fixed that, and the failure above is the base's.
3. One cause behind the seven files: under the regime a lock's refusal is a warning. Failing assertions show
   `WARN structure lock lifted by the exception regime: …` (`scripts/tests/test_structure_effort.py:330`,
   `test_structure.py:282`) and `code 0 != 1` (`test_commit_check.py:82`, `:264`; `test_config_check.py:175`;
   `test_unit_check.py:178`; `test_lane_ship.py:53`; `test_flow_metrics.py:88`, `:95`, `:173`).
4. With `regime.exception_active` default `false` in a throwaway worktree (not committed, removed), the seven modules pass.
5. The default has been `true` since `9c41dc836` (01/11 10:52 BRT, "the exception regime is on, granted by Daniel"); it was
   `false` in `45175f7dc` (07:21 UTC). The shared store reads `regime.exception_active = True`, `granted_by = Daniel`,
   `kept = [money, people]`.
6. Every lock reads the regime through `regime.state()`: `scripts/lib/regime.py:24` and `:36`, `structure.py:717`,
   `commit_check.py:153`, `flow_metrics.py:118`, `decision_next.py:134`, `train.py:343`, `gate_bypass.py:58` and `:71`.
7. The hermetic hook (`scripts/lib/hermetic/sitecustomize.py`, `_PinConfig`) pins the store of the code under test's own
   `config` module for every script test and its children, but pins nothing about the regime. The only judge that isolates
   the regime is `scripts/tests/test_train.py:202-203`, written by hand (`mock.patch.object(train.regime, 'lift', …)`).
8. The registry declares the readers of `regime.exception_active` as `scripts/lib/regime.py` only
   (`config/registry/regime/regime.exception_active.json`, `x-readers`). The lock modules read it indirectly, through
   `regime.lifted()`, so the declaration does not name them.
9. PR #1024, which carries `9c41dc836`, merged at 11:00 BRT under `gate.bypass`: its stages are marked PASS by the bypass, so
   none of its tests ran (`docs/operations/gate-bypass.md`, "What is green at once"). The lane's scoped gate for #1014 passed
   the script tests stage (`scratchpad/lap-1014-2.log`), because that diff selected only its own tests.
10. The shadow is the only gate that runs the whole suite on the base. The train loop with `--shadow` started at 13:52 BRT,
    after `9c41dc836` had merged (`/var/tmp/ou-train/train-loop.log`).
11. The description of `regime.exception_active` says "Off by default" (in `regime.json` and in the per-key file), while its
    default has been `true` since `9c41dc836` (finding 5).
12. Of the 141 script tests, 134 were answered from shared results (their keys had not moved), so a suite run after a change
    to shared tooling must run every test once (`docs/process/lane.md`, "Selection holes").
13. `config.test.sh` passes alone on this head (`scripts/run test config`, exit 0). Its `FAIL` line in the interleaved suite
    output belongs to another test. KD-3ec4be1f (its open defect) is not reproduced here.

## Causas raiz

### R1. The script tests judge the lock rules under the live exception regime, because the hermetic judge pins no regime
Cadeia de porquês:
1. Por que a suíte falha no base? Sete arquivos de teste esperam a recusa de um lock (código 1) e recebem "lifted by the
   exception regime" (código 0). Evidência: Findings 1 e 3.
2. Por que o lock vira aviso? Porque `regime.exception_active` vale `true` por default desde `9c41dc836`, e todo lock lê o
   regime por `regime.state()`. Evidência: Findings 5 e 6.
3. Por que o teste vê o regime vigente? Porque o gancho hermético fixa o store do código sob teste, mas não o julgamento do
   regime; só `test_train.py` isola o seu caso, à mão. Evidência: Finding 7.
4. Por que nenhuma condição do juiz cobre o regime? Porque o desenho do hermético (D-069 item 5) previa rede, relógio, semente
   e store; o regime (D-260) entrou depois sem entrar nessas condições. Evidência: `scripts/lib/hermetic.py` (`install`).
5. Por que o regime não foi apanhado ao entrar? Porque o PR que o trouxe passou sob bypass sem rodar testes (Finding 9), a
   suíte inteira só roda no shadow, que começou depois (Finding 10), e a seleção por covers não alcança os leitores indiretos
   (Finding 8).
Classe: mecanismo faltando
Evidência: Findings 1 a 10.

### R2. The regime key's description contradicts its default, and the grant has two sources of truth
Cadeia de porquês:
1. Por que a descrição diz "Off by default" e o default é `true`? Porque `9c41dc836` mudou a linha `default` e não a frase
   `description`. Evidência: Finding 11.
2. Por que a frase não foi revisada? Porque a concessão vive em dois lugares: o estado gravado no store compartilhado
   (`granted_by = Daniel`) e o default copiado no registro do repositório. Evidência: Finding 5.
3. Por que nada acusou a divergência? Porque nenhum teste compara a descrição de um default com o próprio default; a frase só
   aparece no texto. Evidência: Finding 11.
4. Por que a concessão não tem um registro no repositório? Porque a fonte da verdade do regime é o store compartilhado
   (D-260, "a recorded state"), e o repositório guarda uma cópia do default que ninguém compara com ele.
Classe: arquitetura/desenho
Evidência: Findings 5 e 11.

## Distância do estado da arte
- Research's first rung (the judges pin every ambient state) exists for the store, the clock, the network and the seed, and
  not for the regime. This unit closes that gap for the script tests.
- Research's state of the art reads one recorded state in every judge. We have two copies (the shared store and the head's
  default). R2 keeps the copy as it is, because which one holds the truth is Daniel's decision.
- The combined-head queue (research's third rung) is the program's R1 and the train's queue, planned in
  `docs/programs/fluxo-amplo/plan.md`, not this unit.

## Base defects expected
- None left after this unit's fix: the whole suite passes at the new head (141 of 141 run, exit 0).
- KD-3ec4be1f (`config.test.sh`): not reproduced on this head; its owner (engine-lane) keeps it.
- Speed: the whole suite takes 107 s against the gate's 10 s goal (a warning, not a failure; owner engine-gate-speed).
