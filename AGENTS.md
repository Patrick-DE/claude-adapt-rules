# claude-learn

Mines past agent sessions for the moments the user corrected the agent, then distils
those into rules that future sessions read.

Skill: `skills/learn-rules/SKILL.md` — read it before distilling anything.

## Commands

```bash
bin/claude-learn.sh status      # parse transcripts, report, write nothing
bin/claude-learn.sh extract     # corpus + per-project evidence bundles
bin/claude-learn.sh pending --bundle /tmp/pending.md
bin/claude-learn.sh ingest <candidates.json>
bin/claude-learn.sh consume --note <candidates.json>
bin/claude-learn.sh archive     # copy cited transcripts out of the cleanup path
bin/claude-learn.sh verify      # every quote must be verbatim
bin/claude-learn.sh rot         # which adopted rules are still being broken
```

State lives in `~/.claude-learn/` (override with `CLAUDE_LEARN_HOME`), never in the
install directory.

## Non-negotiables

- **Quotes are verbatim.** Never paraphrase evidence, never invent it. `verify` fails on
  changed word order or capitalisation.
- **Global rules are proposed, not applied.** Candidates go to
  `~/.claude-learn/rules/global/PROPOSED.md`; the user names the ids to adopt. Per-repo
  rules may be written automatically.
- **Scope is computed**: global needs evidence in ≥2 projects or ≥3 sessions.
- **Archive after ingesting.** Transcripts are deleted after ~30 days.

## Development

```bash
python -m pytest        # 57 tests, stdlib-only runtime
```

Runtime code imports nothing outside the standard library: the session-end hook loads it
on every session exit, so a broken dependency here would break unrelated work.
