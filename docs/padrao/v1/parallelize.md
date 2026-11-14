# Parallelize independent steps (Daniel, Oct 26 23:21 and 23:25)

Before starting your plan, mark which steps depend on which. Run independent steps at the same time with sub-agents (e.g. docs/manifests while code is written, targeted tests while the next change is drafted, base comparison while the head runs). Each sub-agent works on separate files; you integrate, commit small and push. Never serialize work that has no dependency.

Parallel commits safeguards: (a) each sub-agent owns files no other sub-agent touches; steps sharing a file run in sequence; (b) each sub-agent commits and pushes its own small commit as soon as its step's tests pass, so a quota stop loses nothing; (c) the main session runs the affected tests after integrating; one full gate at the end.
