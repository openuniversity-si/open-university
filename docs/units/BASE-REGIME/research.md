# BASE-REGIME — research

## Quem já resolveu
- Bazel, hermetic tests and builds (https://bazel.build/basics/hermeticity): a test sees only the inputs it declares; ambient
  state (environment, network, clock, shared configuration) is either pinned by the runner or refused. Solves: a test cannot
  change its verdict by reading live state it did not declare.
- GitHub merge queue (https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue):
  required checks run on the combined head of the queued changes before a merge, and a red result refuses the merge.
  Solves: the base cannot be judged green by a check that never ran on it.
- Uber SubmitQueue ("Keeping master green at scale", https://www.uber.com/blog/keeping-master-green-at-scale/): speculative
  builds of the combined head, with the whole suite behind each merge. Solves: a change is judged with the code it will land
  next to, not with the subset of tests its own diff selects.

## Estado da arte
- Hermetic judging: every test declares its inputs and the runner pins every ambient one (environment, clock, network, shared
  state). The pin is part of the test harness, not of each test.
- Combined-head judging: the whole suite runs on the head that would land, and a red base refuses merges. Selection by
  declared inputs is safe only when the declarations are complete.

## Encaixe em nós
- Copy: the hermetic harness (`scripts/lib/hermetic/sitecustomize.py`) already pins the store of the code under test for every
  script test and its children. The regime's judges' view is one more ambient state of the same kind: pin it in the same hook.
- Adapt: the selection by declared readers (`x-readers` and covers). The lock readers read the regime indirectly, so the
  selection misses them; that root is recorded as a follow-up, not fixed here.
- Does not fit: making the gate's own verdict ignore the regime. The gate judges the head and the registry; the regime is
  Daniel's state and the gate keeps honouring it (D-260, D-069 item 5). The pin belongs to the judges of the rules, not to the gate.

## Escada de ambição
- Now (the cheapest useful step): the script tests pin the judges' view of the regime off, in the existing hook; the
  registry description of the key states what its default is. Two small commits, both with tests.
- Next: the selection follows indirect readers (a follow-up unit), so a change to the regime key runs the lock tests.
- State of the art: the combined head of every queued change is judged with the whole suite, and a red base refuses the
  merge (the program's R1 and the train's queue), already planned in `docs/programs/fluxo-amplo/plan.md`.
