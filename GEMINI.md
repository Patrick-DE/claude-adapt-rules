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
install directory — a plugin update replaces that directory.

## Non-negotiables

- **Quotes are verbatim.** Never paraphrase evidence, never invent it. `verify` fails
  on changed word order or capitalisation.
- **Global rules are proposed, not applied.** Write candidates to
  `~/.claude-adapt-rules/rules/global/PROPOSED.md` and wait for the user to name ids. Per-repo
  rules may be written automatically.
- **Scope is computed**: global needs evidence in ≥2 projects or ≥3 sessions. The gate
  can only lower a proposed scope, never raise it.
- **Archive after ingesting.** Transcripts are deleted after ~30 days; unarchived
  evidence becomes unverifiable.

## Platform notes

On the Antigravity CLI (`agy`), map skill actions as follows: subagents →
`invoke_subagent`; todo lists → a task artifact via `write_to_file` with
`IsArtifact: true` and `ArtifactType: "task"`. Automatic session-end capture is a Claude
Code hook; on other platforms run `extract` or `pending` manually.
