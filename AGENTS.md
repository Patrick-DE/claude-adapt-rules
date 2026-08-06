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
bin/claude-adapt-rules.sh reclassify R-0024=universal --apply
bin/claude-adapt-rules.sh merge <duplicate> <keeper>
bin/claude-adapt-rules.sh archive     # copy cited transcripts out of the cleanup path
bin/claude-adapt-rules.sh verify      # every quote must be verbatim
bin/claude-adapt-rules.sh doctor      # is the pipeline working? hooks fail open
bin/claude-adapt-rules.sh rot         # which adopted rules are still being broken
bin/claude-adapt-rules.sh guards      # rules enforced by a hook, and which could be
bin/claude-adapt-rules.sh workflows   # work repeated by hand: skill candidates
bin/claude-adapt-rules.sh constraints # rules for the next skill/agent file you write
```

State lives in `~/.claude-adapt-rules/` (override with `CLAUDE_ADAPT_RULES_HOME`), never in the
install directory.

## Non-negotiables

- **Quotes are verbatim.** Never paraphrase evidence, never invent it. `verify` fails on
  changed word order or capitalisation.
- **Global rules are proposed, not applied.** Candidates go to
  `~/.claude-adapt-rules/rules/global/PROPOSED.md`; the user names the ids to adopt. Per-repo
  rules may be written automatically.
- **Scope is judged, not counted**: each rule is labelled `universal` or `project`.
  A `universal` claim naming a path, filename, identifier or project name is vetoed
  down to `project`. Only an unlabelled rule falls back to the count gate
  (≥2 projects or ≥3 sessions).
- **Archive after ingesting.** Transcripts are deleted after ~30 days.

## Development

```bash
python -m pytest        # suite run with stdlib-only runtime
```

Runtime code imports nothing outside the standard library: the session-end hook loads it
on every session exit, so a broken dependency here would break unrelated work.
