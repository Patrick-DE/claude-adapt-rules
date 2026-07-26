# claude-learn

Mine your own Claude Code sessions for the moments you corrected the agent, distil
those into rules, and land them where a future session will actually read them.

Two tiers, because the cost of a rule is not the same everywhere:

| Tier | Target | Policy |
| --- | --- | --- |
| **repo** | `rules/repos/<project>/rules.md` | auto-written; blast radius is one project, and it's a git diff away from gone |
| **global** | `rules/global/PROPOSED.md` → `~/.claude/CLAUDE.md` | proposed only, you approve; every line is loaded in every session of every project |

## Where the human text actually is

The interesting finding from building this. In a Claude Code desktop install,
`~/.claude/projects/<slug>/<session>.jsonl` records your prompts as:

```json
{"type": "queue-operation", "operation": "enqueue", "content": "<what you typed>"}
```

The `type: "user"` records are almost entirely tool results and machine continuations.
On this machine: 17k `type:user` records, of which **64** survive noise filtering — and
all 64 are machine-generated (`Continue from where you left off.`, compaction summaries,
skill payloads). The 1325 real prompts are all in `queue-operation` records.

A miner that reads `type: "user"` learns nothing about the user. Both channels are read
here, queue preferred, overlaps de-duplicated.

## Pipeline

```
transcripts → signals → extract → /learn-rules → ledger → render
 (parse)      (score)   (bundles)  (the only      (identity,  (two tiers)
                                    model step)    rot tracking)
```

Everything except `/learn-rules` is deterministic and **stdlib-only** — the SessionEnd
hook imports this package on every session exit, so a dependency here would break
unrelated work in other projects.

```bash
python -m claude_learn.cli status                 # parse and report, write nothing
python -m claude_learn.cli extract                # corpus + per-project bundles
python -m claude_learn.cli ingest rules/candidates/<date>.json
python -m claude_learn.cli verify                 # every quote must be verbatim
python -m claude_learn.cli adopt R-0001 --apply-global
python -m claude_learn.cli rot                    # which rules aren't working
```

Then in Claude Code: `/learn-rules` reads the bundles and writes the candidates file.

## What makes an event worth reading

Lexical signals (`don't`, `wrong`, `always`, `nicht`, `warum hast du`) are cheap and noisy.
Structural signals are weighted higher because they're harder to fake:

- **repeated_instruction** — you said the same thing twice in one session (strongest)
- **user_denied** — you rejected a tool call outright
- **interrupted** — you hit escape

`after_edit` is deliberately worth **zero**. 407 of 778 prompts follow an edit; scoring it
ranks "commit and push" alongside a real correction. It only adds a point when the words
are corrective too.

## Scope is computed, not chosen

`global` requires evidence in **≥2 projects or ≥3 sessions**. Otherwise the rule stays
`repo:`. The model may propose a scope; the gate can only pull it down.

Worktree slugs (`...-app--claude-worktrees-brave-newton-a1b2c3`) collapse onto their
repository — otherwise one repo's quirk looks like cross-project evidence and gets promoted.

## Why it compounds

`ingest` treats a candidate matching an already-adopted rule as a **violation**, not a new
rule. That is the signal worth having: the rule existed and did not work. Reword it, hoist
it earlier, or convert it to a hook.

`rot` then splits adopted rules into *still being broken* (escalate) and *quiet for 30 days*
(stop paying its token cost).

Rules a regex can enforce are marked `enforceable` and belong in a `PreToolUse` hook, not
in prose. Prose is for judgment calls.

## Evidence integrity

`verify` re-checks every quote against the decoded transcript text and fails on
paraphrase, changed capitalisation, or attribution to the wrong session. Raw JSONL escapes
inner quotes, so grepping file bytes gives false failures — hence decoded comparison.

The first real run produced two bad quotes out of 48, both mine, both caught this way.

## Transcripts expire — archive or the audit trail rots

Claude Code deletes transcripts after `cleanupPeriodDays` (**default 30**). Measured
2026-07-26: the oldest file in `~/.claude/projects` was exactly 30 days old, and four
evidence quotes from rules distilled that same morning already cited deleted sessions.

```bash
python -m claude_learn.cli archive        # cited sessions only
python -m claude_learn.cli archive --all  # every session, before it ages out
```

The weekly job archives after every extract. `verify` reads the archive too, and reports a
vanished transcript as **expired** rather than as bad evidence — decay must not look like
fabrication.

To keep raw history longer, raise retention in `~/.claude/settings.json`:

```json
{ "cleanupPeriodDays": 365 }
```

## Automation

- **SessionEnd hook** (`hooks/session_end_capture.ps1`, wired in `~/.claude/settings.json`)
  appends each finished session's candidates to `data/queue/queue.jsonl`. No model, no
  network, always exits 0.
- **Weekly task** `claude-learn weekly extract` (Windows Task Scheduler, Mondays 09:00)
  re-extracts full history via `hooks/weekly_extract.ps1`. Remove with:

```bash
schtasks /Delete /TN "claude-learn weekly extract" /F
```

The distil step stays manual: it needs a model, and the `claude` CLI is not on PATH here.

## Layout

```
src/claude_learn/     transcripts, signals, extract, ledger, render, verify, cli
.claude/skills/learn-rules/SKILL.md   the model-facing distillation instructions
hooks/                session-end capture + weekly extract
rules/ledger.json     rule identity, evidence, adoption dates, violation counts
rules/candidates/     distilled candidate batches (model output — versioned)
rules/global/         PROPOSED.md (awaiting you) and ADOPTED.md (the spliced block)
rules/repos/<proj>/   auto-written per-project rules
data/                 gitignored: corpus, bundles, queue, reports
tests/                42 tests, run with `python -m pytest`
```
