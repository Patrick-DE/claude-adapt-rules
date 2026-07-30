# claude-adapt-rules

Mine your own Claude Code sessions for the moments you corrected the agent, distil
those into rules, and land them where a future session will actually read them.

Two tiers, because the cost of a rule is not the same everywhere:

| Tier | Target | Policy |
| --- | --- | --- |
| **repo** | `~/.claude-adapt-rules/rules/repos/<project>/rules.md` | auto-written; blast radius is one project, and it's a git diff away from gone |
| **global** | `~/.claude-adapt-rules/rules/global/PROPOSED.md` → `~/.claude/CLAUDE.md` | proposed only, you approve; every line is loaded in every session of every project |

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

## Install

As a Claude Code plugin, from a local checkout:

```bash
claude plugin marketplace add /path/to/claude-adapt-rules
```

Then enable `claude-adapt-rules`. That registers two hooks — `SessionStart` (inject this
project's rules) and `SessionEnd` (capture corrections) — plus the `/claude-adapt-rules` skill.
Requires Python on PATH as `python`.

| Platform | What loads | Notes |
| --- | --- | --- |
| Claude Code (Windows) | skill + both hooks | primary target; hooks exec `python` directly, no shell needed |
| Claude Code (macOS/Linux) | skill + both hooks | change `command` to `python3` in `.claude-plugin/plugin.json` if `python` is absent |
| Antigravity / Gemini | skill + `GEMINI.md` context | no session hooks — run `extract` on a schedule and read rules from `~/.claude-adapt-rules/` |
| Codex | skill + `AGENTS.md` context | same |

**State lives in `~/.claude-adapt-rules/`** (`CLAUDE_ADAPT_RULES_HOME` overrides), never inside the
plugin directory — installed plugins live under a versioned cache path, so an update
would orphan your ledger, queue and archive.

```
~/.claude-adapt-rules/
  rules/ledger.json          rule identity, evidence, adoption dates, violations
  rules/global/PROPOSED.md   awaiting your approval
  rules/repos/<project>/     auto-written per-project rules
  rules/candidates/          distilled candidate batches
  data/corpus, queue, archive, reports
```

Run the CLI from anywhere without installing the package:

```bash
bin/claude-adapt-rules.sh status      # or bin\claude-adapt-rules.ps1 status on Windows
```

### Using the skill without installing the plugin

Plugin skills only load once the plugin is installed, and `.claude/skills/` only loads
inside its own project. To get `/claude-adapt-rules` in every project from a plain checkout, link
it into your user skills directory — no admin needed on Windows, and it stays a single
source of truth:

```bash
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\claude-adapt-rules" -Target "C:\path\to\claude-adapt-rules\skills\claude-adapt-rules"
```

```bash
ln -s /path/to/claude-adapt-rules/skills/claude-adapt-rules ~/.claude/skills/claude-adapt-rules
```

Skills are enumerated at session start, so it appears in the next session. Remove the link
if you later install the plugin, or the same skill loads twice.

## How rules reach a session

Distilling rules is worthless if nothing reads them. Both tiers have a delivery path:

| Tier | Delivery |
| --- | --- |
| **repo** | a `SessionStart` hook injects the current project's rules as session context — nothing is written into your other repositories, so teammates see no diff and a reworded rule takes effect next session |
| **global** | `adopt --apply-global` splices a marked block into `~/.claude/CLAUDE.md` after you name the ids |

Sessions started inside a git worktree receive the parent repository's rules. Projects with
no rules get nothing — the hook prints nothing and exits 0.

```bash
claude-adapt-rules doctor      # is any of this actually working?
```

`doctor` exists because hooks fail open: a broken capture is silent by design. It reports
captured/pending events, recent hook failures, archive coverage, transcripts approaching
the cleanup age, and how many rules the current project would receive.

## Pipeline

```
transcripts → signals → extract → /claude-adapt-rules → ledger → render
 (parse)      (score)   (bundles)  (the only             (identity,  (two tiers)
                                    model step)           rot tracking)
```

Everything except `/claude-adapt-rules` is deterministic and **stdlib-only** — the SessionEnd
hook imports this package on every session exit, so a dependency here would break
unrelated work in other projects.

```bash
python -m claude_adapt_rules.cli status                 # parse and report, write nothing
python -m claude_adapt_rules.cli extract                # corpus + per-project bundles
python -m claude_adapt_rules.cli ingest ~/.claude-adapt-rules/rules/candidates/<date>.json
python -m claude_adapt_rules.cli verify                 # every quote must be verbatim
python -m claude_adapt_rules.cli adopt R-0001 --apply-global
python -m claude_adapt_rules.cli rot                    # which rules aren't working
```

Then in Claude Code: `/claude-adapt-rules` reads the bundles and writes the candidates file.

## What makes an event worth reading

Lexical signals (`don't`, `wrong`, `always`, `nicht`, `warum hast du`) are cheap and noisy.
Structural signals are weighted higher because they're harder to fake:

- **repeated_instruction** — you said the same thing twice in one session (strongest)
- **user_denied** — you rejected a tool call outright
- **interrupted** — you hit escape

`after_edit` is deliberately worth **zero**. 407 of 778 prompts follow an edit; scoring it
ranks "commit and push" alongside a real correction. It only adds a point when the words
are corrective too.

## Scope comes from generality, not from frequency

Every rule is classified `applies: universal | project`. Universal means it would hold in
a repo you have never seen — "never commit code that does not build" qualifies after being
said **once**, which no evidence-count gate would ever promote. Project means it is tied
to this codebase's tooling, architecture or vocabulary.

A `universal` claim is vetoed when the rule text names a path, filename, identifier or
known project name, and the reason is reported:

```
? R-0027 is universal but names a path (releases/canvas-debug.log) — scoped to repo
```

`project` is never widened. Unclassified rules fall back to the old count gate
(≥2 projects or ≥3 sessions), which is only a proxy for generality.

```bash
claude-adapt-rules reclassify R-0024=universal R-0026=project --apply
```

Promotion out of repo scope drops the rule back to *proposed*: repo rules auto-apply,
global rules never do.

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
python -m claude_adapt_rules.cli archive        # cited sessions only
python -m claude_adapt_rules.cli archive --all  # every session, before it ages out
```

The weekly job archives after every extract. `verify` reads the archive too, and reports a
vanished transcript as **expired** rather than as bad evidence — decay must not look like
fabrication.

To keep raw history longer, raise retention in `~/.claude/settings.json`:

```json
{ "cleanupPeriodDays": 365 }
```

## Automation

- **SessionStart hook** (`bin/inject.py`) — puts the current project's rules into context.
- **SessionEnd hook** (`bin/capture.py`, or `bin/capture.sh` / `bin/capture.ps1` as shims)
  appends each finished session's candidates to
  `~/.claude-adapt-rules/data/queue/queue.jsonl`. No model, no network, always exits 0.

Both are declared by the plugin and exec `python` directly, so neither needs a shell — on
Windows that removes the Git Bash dependency. Where only `python3` exists, change the
`command` in `.claude-plugin/plugin.json`.
- **Weekly refresh** — `hooks/weekly_extract.ps1` (Windows Task Scheduler) or
  `hooks/weekly_extract.sh` (cron). Both re-extract full history and then archive.

```bash
schtasks /Create /TN "claude-adapt-rules weekly" /SC WEEKLY /D MON /ST 09:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\claude-adapt-rules\hooks\weekly_extract.ps1"
```

```bash
0 9 * * 1 /path/to/claude-adapt-rules/hooks/weekly_extract.sh
```

The distil step stays manual: it needs a model. Run `/claude-adapt-rules` when the bundles look
worth reading.

## Layout

```
src/claude_adapt_rules/       transcripts, signals, extract, ledger, render, verify, archive, inject, cli
skills/claude-adapt-rules/    the model-facing distillation instructions
bin/                          hook entry points (capture, inject) + claude-adapt-rules CLI wrappers
hooks/                        weekly extract for Task Scheduler (.ps1) and cron (.sh)
.claude-plugin/               Claude Code plugin + marketplace manifests
.codex-plugin/                Codex manifest; AGENTS.md is its context file
gemini-extension.json         Antigravity / Gemini manifest; GEMINI.md is its context file
tests/                        suite run with `python -m pytest`
```

No rules ship with the plugin — the ledger starts empty and everything you distil stays
in `~/.claude-adapt-rules/`.
