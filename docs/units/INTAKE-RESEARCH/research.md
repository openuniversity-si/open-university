# INTAKE-RESEARCH — research

Starts from the real problem of [intake.md](intake.md): units audit before anyone has written down what was asked, why, and who already solved it.

## Quem já resolveu
- **Amazon "Working Backwards" (PR/FAQ)** — <https://www.aboutamazon.com/news/workplace/an-insider-look-at-amazons-culture-and-processes>: before building, write the customer-facing press release and FAQ; it fixes the *intention* and the "done" metric before any design. Solves: building the literal request instead of the need.
- **Google design docs ("Context and scope", "Goals and non-goals", "Alternatives considered")** — <https://www.industrialempathy.com/posts/design-docs-at-google/>: a fixed opening section for context and goals, and a mandatory alternatives section. Solves: the same two gaps (intent, prior art) in one short document.
- **Rust / Python RFC templates ("Motivation", "Prior art", "Unresolved questions")** — <https://github.com/rust-lang/rfcs/blob/master/0000-template.md>, <https://peps.python.org/pep-0001/>: every proposal must cite how other languages solved it and list what is still unknown. Solves: reinventing known designs; hidden unknowns.
- **Design Council "Double Diamond" (discover/define before develop/deliver)** — <https://www.designcouncil.org.uk/our-resources/the-double-diamond/>: diverge on the problem, converge on one problem statement, only then on solutions. Solves: solving the wrong problem.
- **Architecture Decision Records (Nygard)** — <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>: Context → Decision → Consequences, one small file per decision, immutable once accepted. Solves: decisions without their context; already the shape of our D-NNN.

## Estado da arte
- **Standard:** a template with fixed headings (context, goals, prior art, open questions), required before the design review (Google, Rust RFC). Needs: a template and someone who refuses a document without it.
- **Most advanced:** the template is machine-checked at the door (RFC bots, ADR linters such as `adr-tools`/`log4brains` structure checks), and prior art is a required, non-empty section with links. Needs: a check in the pipeline and a "not retroactive" rule so old documents do not fail.
- Each requires a single owner of the template and a cheap way to say "the reference is obvious, one line".

## Encaixe em nós
- **Copy directly:** fixed headings checked at the door — our `structure check` stage already does it for the effort block (`scripts/lib/effort.py`), including grandfathering by first-commit date.
- **Adapt:** Working Backwards and the Double Diamond become the INTAKE sections Intenção and Problema real (one sentence + a metric). The RFC "Prior art" becomes RESEARCH, sized at one page / ~15 minutes, because our units are small.
- **Does not fit:** a review meeting before the design (D-055: there is no review step); a separate RFC repository (the unit folder already is the record).

## Escada de ambição
1. **Minimum useful now (this PR):** Padrão v6 tells every session the order; the `structure check` refuses a new unit without `intake.md`/`research.md` or with a missing heading; templates exist. Cost ~30 min + one gate.
2. Next: the coordinator renders `intake.md` from the request it receives (the brief already carries the literal ask), so the session fills only the gaps.
3. Then: a reference index (`docs/process/research/`) so a second unit on the same problem reuses the first one's research instead of searching again.
4. State of the art: Lacunas that only the requester can answer become an event (`plan.input`) that reaches Daniel before effort is spent, and RETRO measures how often research changed the plan.
