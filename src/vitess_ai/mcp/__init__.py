"""The VITESS execution boundary, both halves.

``server`` runs in the ``vitess-mcp`` container and executes the binaries;
``connection`` runs in the application and reaches it over HTTP; ``payloads``
holds the models they both use; ``execution`` runs the process pipeline itself.

Nothing is re-exported here on purpose. ``server`` must stay free of the agent
framework and ``connection`` pulls it in, so importing this package must not
drag one side into the other's process.
"""
