---
name: learn-rules
description: Use when asked to learn from past sessions, distil corrections into rules, update CLAUDE.md from session history, or run the claude-learn pipeline. Mines Claude Code transcripts for moments the user corrected the agent and turns them into scoped, evidence-backed rules.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Distilling session corrections into rules

Turn "the user had to tell me this" into "the agent already knows this".

Extraction and rule bookkeeping are deterministic Python. Your job is the one step
that needs judgment: reading evidence and writing rules that are specific enough to
change behaviour and general enough to reuse.

## Running it

Always invoke through the wrapper. `python -m claude_learn.cli` only resolves when the
current directory is the checkout with `PYTHONPATH` set, which is never true when this
skill runs from another project:

```bash
# Windows
& "$env:CLAUDE_PLUGIN_ROOT\bin\claude-learn.ps1" extract
# macOS / Linux
"$CLAUDE_PLUGIN_ROOT/bin/claude-learn.sh" extract
```

Outside a plugin install, use the checkout's own `bin/claude-learn.ps1` or `.sh`. The
examples below shorten this to `claude-learn`.

```bash
claude-learn extract           # rebuild the corpus and bundles from all history
```

Extraction always covers all history: the corpus file is rewritten in place, so a
windowed run would replace the complete corpus with a slice. For incremental work use
`pending` (see below), not a narrower extract.

Outputs live under `~/.claude-learn/data/`:

| Path | What it holds |
| --- | --- |
| `corpus/events.jsonl` | every selected event, machine-readable |
| `corpus/by-project/<slug>.md` | evidence bundles — read these |
| `reports/extract.md` | counts, signal frequency, per-project totals |

Then read each bundle, write candidates to `~/.claude-learn/rules/candidates/<date>.json`,
and apply them:

```bash
claude-learn ingest ~/.claude-learn/rules/candidates/<date>.json
```

## Writing a rule

One candidate per distinct behaviour. Schema (`{"rules": [...]}`):

```json
{
  "rule": "Test against the real frontend and backend; do not mock the system under test.",
  "why": "Mocks hid integration breakage the user then had to find by hand.",
  "category": "verification",
  "enforceable": false,
  "evidence": [
    {"project": "my-app", "session": "193129bb", "ts": "2026-07-07",
     "quote": "why do you always stub the queue? why not run it against the real worker"}
  ]
}
```

Categories: `anti-pattern`, `expectation`, `style`, `process`, `verification`, `tooling`.

**Rules that pass review**

- Imperative and testable. "Split files over 500 lines" — not "be mindful of file size".
- Say what to do instead, not only what to avoid.
- One behaviour per rule. If it needs "and", it is two rules.
- Carry the user's own reason in `why`. A rule without a reason gets ignored under pressure.

**Rules that get rejected**

- Restating a session's narrative ("the user wanted X in file Y") — that is a fact, not a rule.
- Anything already in `~/.claude/CLAUDE.md` or the repo's own instructions.
- Mechanical checks. Set `enforceable: true` for things a regex or lint can catch
  (`--no-verify`, banned imports, file length) and expect them to become a hook, not prose.
  Prose is for judgment calls.

## Evidence rules

- Quote **verbatim** from the bundle's `User said` block. Never paraphrase into quotes,
  never invent a quote. Every quote must be greppable back to `~/.claude/projects`.
- Trim to the sentence carrying the signal, ≤25 words.
- Attach every occurrence you found. Occurrence count drives scope and confidence.

## Scope is computed, not chosen

`ingest` applies the gate: evidence in **≥2 projects or ≥3 sessions** → `global`;
otherwise `repo:<project>`. You may set `scope`, but the gate can only pull it *down*.
So: gather all occurrences of a rule across bundles before filing it. Splitting the same
rule per project keeps it repo-scoped forever.

Worktree slugs collapse onto their repository, so a worktree never fakes a second project.

## After ingest

- Repo rules are written automatically to `rules/repos/<project>/rules.md`.
- Global candidates land in `rules/global/PROPOSED.md`. **Never edit `~/.claude/CLAUDE.md`
  yourself.** Present the candidates and let the user pick; only then:

```bash
claude-learn adopt R-0004 R-0009 --apply-global
```

That splices a marked block into `~/.claude/CLAUDE.md`, backs up the old file, and refuses
to write if the block exceeds its line cap (global text costs tokens in every session of
every project).

- `ingest` reports **violations**: candidates matching an already-adopted rule. Those are the
  interesting ones — the rule exists and did not work. Reword it, move it earlier, or make it
  a hook. Report them; do not silently re-add.

```bash
claude-learn rot     # what to escalate, what to retire
```

## Always archive after ingesting

```bash
claude-learn archive
```

Claude Code deletes transcripts after 30 days by default. A rule outlives its transcript,
so unarchived evidence becomes unverifiable — `verify` will report it as *expired*, and it
cannot be recovered. Archive in the same run that files the rules.

## Working from the session-end queue

The `SessionEnd` hook accumulates events in `data/queue/queue.jsonl`. Distil from the
pending slice, not the whole queue:

```bash
claude-learn pending --bundle ~/.claude-learn/data/corpus/pending.md
# ... write candidates from that bundle, then ingest ...
claude-learn consume --note ~/.claude-learn/rules/candidates/<date>.json
```

Without `consume`, every run re-reads every event ever captured.

## Reporting back

State: events read, rules created (with ids and scope), violations of existing rules, and
anything you deliberately skipped. If a bundle was capped, say how many events were omitted.
