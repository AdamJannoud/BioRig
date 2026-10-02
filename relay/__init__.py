"""BioRig verifier relay: the one process that holds VERIFIER_ROLE, allocates plot identities and signs mintTree.

One registration is one tree. The client sends a measurement and a GPS fix; the relay derives the H3 cell, allocates
the tree's ordinal in that cell, derives the nullifier from (cell, ordinal), queues the job and broadcasts it. See
README.md for running it and docs/relay-api.md for the HTTP contract.

Nothing in this package imports Streamlit: dashboard/__init__.py is empty, and the dashboard modules reused here
(h3_nullifier, allometry, config, chain) import it only inside dashboard.config.hosted_secrets(), which the relay
never calls.
"""
