"""The VITESS agents: one supervisor and five module specialists.

Importing :mod:`vitess_ai.agents.vitess_agent` registers the supervisor with
core's agent registry. That import is a side effect, and it is deliberate --
JueNA's rule is that adding an agent takes a package, a builder import and one
explicit entry. It also means an application process that never imports this
module serves no VITESS routes at all, which is why the import belongs in the
server's own module with a `# noqa: F401`.
"""
