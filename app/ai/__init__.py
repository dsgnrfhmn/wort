"""Optional AI layer (disabled by default).

Nothing here talks to the network unless WORT_AI_ENABLED=1 *and* the provider module is imported by
`service.build`. With the layer off, the app never imports `anthropic_provider` and never opens a
socket. The decision to enable it is recorded in DECISIONS.md (D0 revision); see DEPLOY.md.
"""
