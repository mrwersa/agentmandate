# Synthetic Accepted Continuity Fixture

This directory is an explicitly synthetic test control. It is not provider
evidence and does not change the review state of either committed continuity
experiment.

`manifest.json` supplies the exact mandate bytes. `binding.json` joins those
bytes and the `caller` principal to one synthetic AgentCore policy-session
boundary. `provider.json` records one unchanged, platform-verified transition
whose first unit is admitted and whose second is denied by a maximum of one.
`binding-verification.json`, `policy.json`, and `provider-control.json` are the
complete digest-pinned source set.

The accepted reviewer identity, provider protocol, boundary, transition, and
source interpretations all name their synthetic role. The fixture exists only
to prove that the private contract can produce a complete `satisfied`
safe-continuation result. It makes no claim about AWS, Anthropic, deployed
cryptography, or runtime mediation.
