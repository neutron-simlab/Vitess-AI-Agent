"""The part of the app that actually runs VITESS, seen from both sides.

``server`` runs in the ``vitess-mcp`` container and runs the VITESS programs;
``connection`` runs in the application and reaches the server over HTTP;
``payloads`` holds the data shapes both sides use; ``execution`` runs the chain
of VITESS programs itself.

Nothing is re-exported here, on purpose. ``server`` must stay free of the agent
framework, and ``connection`` loads it, so importing this package must not drag
one side into the other's process.
"""
