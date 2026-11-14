# TRAIN-TEMP-FIX — intake

## Pedido
Daniel (owner of A Torre), 2026-11-02 14:20 BRT, opened straight as a PR with no project above it: "Vamos abrir uma PR
— diretamente uma PR, sem um Projeto — para atacar a questão do Trem. Ele já nos deu trabalho demais e está nos tirando
muito tempo. A função dessa PR é prover uma solução temporária que resolva de forma mais definitiva possível a questão
do Trem enquanto não modificamos sua arquitetura e o redesenhamos. Ao final, eu gostaria de ter a solução temporária
implementada e tudo que está para ser mergeado, mergeado."
He decided: one PR, a temporary fix as durable as today's design allows, and at the end everything that is ready is
merged. At 14:31 he added: "se a gente tiver o trabalho de achar fato, veredicto técnico, causa técnica raiz, esse
trabalho é da função" — he decided that the session finds the facts, the technical verdict and the root cause itself.

## Intenção
Stop paying for the train's failures: the train merges again with the architecture it has, the ready PRs land, and the
next time a run fails nobody has to reconstruct why from ref timestamps.

## Contexto
- The base `mod/roadmap-integration` sat at `fab6e204d` (#1081, 14:10Z) from 14:10Z to 17:32Z with #1084 and #1083
  ready in the train queue.
- The runner VM (`train@the-tower-runner.us-central1-a.c.savvy-bonito-286513.internal`) ran the train every 15 min and
  each run released the lock about 3 s after taking it (audit F3).
- A first launch of this unit (session `01B2LxDVDe3V…`, 14:28 BRT) ran the train from a cloud session at 17:32Z and
  merged #1084 and #1083 (audit F9); this replacement session interrupted it at 17:35Z to keep one writer on the branch.
- CONTROL-ROUTE (#1083) owns the runner and the route swap; CONTROL-STORE (#1084) the job store. #1066 waits for a
  conversation with Daniel about the method. #1082 is merged only if its author declared it ready.

## Regras
D-054 (production frozen; the train is the only merger), D-065 (events, not a clock), D-077/D-081 (unit flow, root
causes), D-025 (commit discipline), D-290 (the control plane is the runner's only job route). No secret printed or
stored. No access to the runner VM (no gcloud, no ssh). The language rule: English, Daniel's words quoted.

## Problema real
A train run that cannot read its queue dies in seconds and leaves no reason anywhere a session can read, so a stalled
train looks healthy until someone reads lock timestamps. Resolved when: `scripts/train queue` is empty, the base is past
`fab6e204d`, a dying run leaves its reason durably (lock release record + the run's last output line, proved by a
test), and `scripts/service status` shows that reason and counts no closed PR.

## Lacunas
- Asked vs. promised: Daniel asked that "tudo que está para ser mergeado" merge; the engine promises only PRs with a
  live `pr.ready` on their exact head and out of draft. #1066 is excluded by his own order; #1082 depends on its author.
- The VM's environment cannot be read from a session: that it lacks `$TOWER_EVENTS_TOKEN` is inferred (audit F6) and
  only someone with access to the VM can confirm it or provision it.
- Out of scope: the train's redesign (batch and lock model, a supervised runner, a credential inventory per runner),
  the control-plane Worker and the job store.
