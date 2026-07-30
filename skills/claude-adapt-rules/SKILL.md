---
name: adapt-rules
description: Use when asked to learn from past sessions, distil corrections into rules, update CLAUDE.md from session history, or run the claude-adapt-rules pipeline. Mines Claude Code transcripts for moments the user corrected the agent and turns them into scoped, evidence-backed rules.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Distilling session corrections into rules

Turn "the user had to tell me this" into "the agent already knows this".

Extraction and rule bookkeeping are deterministic Python. Your job is the one step
that needs judgment: reading evidence and writing rules that are specific enough to
change behaviour and general enough to reuse.

## Running it

Always invoke through the wrapper. `python -m claude_adapt_rules.cli` only resolves when the
current directory is the checkout with `PYTHONPATH` set, which is never true when this
skill runs from another project:

```bash
# Windows
& "$env:CLAUDE_PLUGIN_ROOT\bin\claude-adapt-rules.ps1" extract
# macOS / Linux
"$CLAUDE_PLUGIN_ROOT/bin/claude-adapt-rules.sh" extract
```

Outside a plugin install, use the checkout's own `bin/claude-adapt-rules.ps1` or `.sh`. The
examples below shorten this to `claude-adapt-rules`.

```bash
claude-adapt-rules extract           # rebuild the corpus and bundles from all history
```

Extraction always covers all history: the corpus file is rewritten in place, so a
windowed run would replace the complete corpus with a slice. For incremental work use
`pending` (see below), not a narrower extract.

Outputs live under `~/.claude-adapt-rules/data/`:

| Path | What it holds |
| --- | --- |
| `corpus/events.jsonl` | every selected event, machine-readable |
| `corpus/by-project/<slug>.md` | evidence bundles — read these |
| `reports/extract.md` | counts, signal frequency, per-project totals |

Then read each bundle, write candidates to `~/.claude-adapt-rules/rules/candidates/<date>.json`,
and apply them:

```bash
claude-adapt-rules ingest ~/.claude-adapt-rules/rules/candidates/<date>.json
```

## Writing a rule

One candidate per distinct behaviour. Schema (`{"rules": [...]}`):

```json
{
  "rule": "Test against the real frontend and backend; do not mock the system under test.",
  "why": "Mocks hid integration breakage the user then had to find by hand.",
  "category": "verification",
  "applies": "universal",
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

## Classify every rule: `applies`

This is the judgement that decides scope, and it is yours to make:

- `"universal"` — an engineering practice that holds in any codebase. "Never commit code
  that does not build." Said once, in one project, and still true everywhere.
- `"project"` — tied to this codebase's architecture, tooling, product decisions or
  vocabulary. "Start the backend through `start_debug.bat`."

Ask: *would this rule still make sense in a repo I have never seen?* If yes, it is
universal. Do not use evidence count to decide — a universal rule stated once is still
universal, and a local quirk repeated fifty times is still local.

A `universal` claim is **vetoed** automatically when the rule text names a path, a
filename, an identifier (`snake_case`, `camelCase`, `ALL_CAPS`) or a known project name;
it becomes `project` and the reason is printed. If a rule is genuinely universal, say it
in general terms — name the practice, not the file.

`project` is never widened: narrow is the safe default.

Omitting `applies` falls back to the old count gate (**≥2 projects or ≥3 sessions** →
global), which is a frequency proxy for generality and gets one-off universal rules wrong.
Always set it.

Worktree slugs collapse onto their repository, so a worktree never fakes a second project.

## After ingest

- Repo rules are written automatically to `rules/repos/<project>/rules.md`.
- Global candidates land in `rules/global/PROPOSED.md`. **Never edit `~/.claude/CLAUDE.md`
  yourself.** Present the candidates and let the user pick; only then:

```bash
claude-adapt-rules adopt R-0004 R-0009 --apply-global
```

That splices a marked block into `~/.claude/CLAUDE.md`, backs up the old file, and refuses
to write if the block exceeds its line cap (global text costs tokens in every session of
every project).

- `ingest` reports **violations**: candidates matching an already-adopted rule. Those are the
  interesting ones — the rule exists and did not work. Reword it, move it earlier, or make it
  a hook. Report them; do not silently re-add.

```bash
claude-adapt-rules rot     # what to escalate, what to retire
```

## Always archive after ingesting

```bash
claude-adapt-rules archive
```

Claude Code deletes transcripts after 30 days by default. A rule outlives its transcript,
so unarchived evidence becomes unverifiable — `verify` will report it as *expired*, and it
cannot be recovered. Archive in the same run that files the rules.

## Working from the session-end queue

The `SessionEnd` hook accumulates events in `data/queue/queue.jsonl`. Distil from the
pending slice, not the whole queue:

```bash
claude-adapt-rules pending --bundle ~/.claude-adapt-rules/data/corpus/pending.md
# ... write candidates from that bundle, then ingest ...
claude-adapt-rules consume --note ~/.claude-adapt-rules/rules/candidates/<date>.json
```

Without `consume`, every run re-reads every event ever captured.

## Reporting back

State: events read, rules created (with ids and scope), violations of existing rules, and
anything you deliberately skipped. If a bundle was capped, say how many events were omitted.
