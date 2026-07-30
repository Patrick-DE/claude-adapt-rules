# claude-adapt-rules

Mines past agent sessions for the moments the user corrected the agent, then distils
those into rules that future sessions read.

Skill: `skills/claude-adapt-rules/SKILL.md` — read it before distilling anything.

## Commands

```bash
bin/claude-adapt-rules.sh status      # parse transcripts, report, write nothing
bin/claude-adapt-rules.sh extract     # corpus + per-project evidence bundles
bin/claude-adapt-rules.sh pending --bundle /tmp/pending.md
bin/claude-adapt-rules.sh ingest <candidates.json>
bin/claude-adapt-rules.sh consume --note <candidates.json>
bin/claude-adapt-rules.sh archive     # copy cited transcripts out of the cleanup path
bin/claude-adapt-rules.sh verify      # every quote must be verbatim
bin/claude-adapt-rules.sh doctor      # is the pipeline working? hooks fail open
bin/claude-adapt-rules.sh rot         # which adopted rules are still being broken
```

State lives in `~/.claude-adapt-rules/` (override with `CLAUDE_ADAPT_RULES_HOME`), never in the
install directory.

## Non-negotiables

- **Quotes are verbatim.** Never paraphrase evidence, never invent it. `verify` fails on
  changed word order or capitalisation.
- **Global rules are proposed, not applied.** Candidates go to
  `~/.claude-adapt-rules/rules/global/PROPOSED.md`; the user names the ids to adopt. Per-repo
  rules may be written automatically.
- **Scope is computed**: global needs evidence in ≥2 projects or ≥3 sessions.
- **Archive after ingesting.** Transcripts are deleted after ~30 days.

## Development

```bash
python -m pytest        # suite run with stdlib-only runtime
```

Runtime code imports nothing outside the standard library: the session-end hook loads it
on every session exit, so a broken dependency here would break unrelated work.
