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
bin/claude-learn.sh doctor      # is the pipeline working? hooks fail open
bin/claude-learn.sh rot         # which adopted rules are still being broken
```

State lives in `~/.claude-learn/` (override with `CLAUDE_LEARN_HOME`), never in the
install directory — a plugin update replaces that directory.

## Non-negotiables

- **Quotes are verbatim.** Never paraphrase evidence, never invent it. `verify` fails
  on changed word order or capitalisation.
- **Global rules are proposed, not applied.** Write candidates to
  `~/.claude-learn/rules/global/PROPOSED.md` and wait for the user to name ids. Per-repo
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
