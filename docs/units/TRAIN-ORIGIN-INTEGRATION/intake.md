# TRAIN-ORIGIN-INTEGRATION — intake

## Pedido
Coordinator update following the 2026-11-02 22:40 BRT merge: “fetch mod/roadmap-integration at a8feab76d, run the full
ordinary gate on it, and check that ORIGIN-FINISH's intent ... survived the -X ours resolution. If anything is red
or lost, fix it definitively on a new branch ... open a PR against mod/roadmap-integration”.

## Intenção
Deliver a green integration tree retaining Origin's forge boundaries and TRAIN-DEFINITIVE's lifecycle guarantees.

## Contexto
ORIGIN-FINISH #1087 merged as d03a377dc. TRAIN-DEFINITIVE #1086 merged as a8feab76d after coordinator merge
71f80814f selected #1086's conflicting hunks. The previous local resolution was stopped and saved privately.
This unit starts exactly from a8feab76d on mod/train-origin-integration; the old branch is untouched.

## Regras
D-077/D-081 unit flow; D-285/D-287 operation relations and accepted responsibility; D-291 job lifecycle.
No rebase, force push, edits to I-052b7eed.md or I-12caecdd.md, or changes to PR #1066. Status goes to the diary.
Daniel's 22:19 BRT performance acceptance stays closed: no more speed optimization or VM/Worker-secret changes.

## Problema real
The merged ordinary gate fails five script suites, and its operation census contradicts the surviving source.
Resolved means the ordinary gate is green and both units' observable behavior and regression intent are retained.

## Lacunas
The post-repair full gate must identify any further integration failures; all such failures remain in scope.
