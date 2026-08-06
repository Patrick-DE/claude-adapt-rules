"""claude-adapt-rules: mine Claude Code sessions for corrections, distil them into rules.

Pipeline:

    transcripts -> signals -> extract  -> /claude-adapt-rules -> ledger  -> render
    (parse jsonl)  (score)    (bundles)   (the only model step)  (identity) (two tiers)

Delivery is the point: `inject` puts a project's rules into the next session,
`authoring` puts them in front of whatever you write next, and `guards` enforces
the subset a regex can decide. Everything except the distil step is deterministic
and dependency-free.
"""

__all__ = [
    "archive",
    "authoring",
    "extract",
    "guards",
    "inject",
    "ledger",
    "migrate",
    "render",
    "signals",
    "transcripts",
    "verify",
    "workflows",
]
__version__ = "0.1.5"
