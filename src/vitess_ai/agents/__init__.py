"""The VITESS agents: a guided supervisor, a sweep agent and six module specialists.

Importing :mod:`vitess_ai.agents.vitess_agent` registers the supervisor with
core's list of agents. That import does its work as a side effect, on purpose:
JueNA's rule is that adding an agent takes a package, an import of its builder
and one explicit entry. It also means an application that never imports this
file serves no VITESS routes at all, which is why the import sits in the
server's own file, marked ``# noqa: F401`` so the linter does not flag it as
unused.
"""
