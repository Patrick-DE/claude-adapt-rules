"""claude-adapt-rules: mine Claude Code sessions for corrections, distil them into rules.

Pipeline:

    transcripts  ->  signals  ->  extract   ->  /learn-rules  ->  ledger  ->  render
    (parse jsonl)   (score)      (bundles)      (LLM distil)      (identity)  (two tiers)

Everything except `/learn-rules` is deterministic and dependency-free.
"""

__all__ = ["extract", "ledger", "render", "signals", "transcripts"]
__version__ = "0.1.3"
