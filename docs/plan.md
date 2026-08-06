# Implementation plan: closing the five gaps

**Status:** all five gaps shipped v0.1.7–v0.1.8 · written 2026-08-07
**Derived from:** [vision.md](vision.md) · **tracked in:** [roadmap.md](roadmap.md)

The five gaps in vision.md are ranked by *impact*. This plan re-orders them by
**what to build first**, which is not the same thing: the highest-impact item is not
the one with the shortest path to a signal.

## Sequencing

```
G4 recall tier ──► G1 unattended distil ──► G2 adherence metric
   (growth path)      (closes the loop)        (needs calendar time anyway)

G5 harness inventory ──► review pass (rejected for now, see below)

G3 guard telemetry — small, opportunistic, low yield until guards exist that fire
```

Only one real dependency exists: the review pass needs G5, because reviewing skills is
meaningless without knowing which ever fire. Everything else is ordered by judgement, not
by blocking.

**G4 before G1.** G1 is the highest-impact gap, but it is also the only planned item that
*produces more rules* — unattended drafting means more candidates, more often. Every rule
added today lands in an always-on block that has no exit except a guard. Fixing the growth
path first means G1's output has somewhere to go; the reverse order means shipping a rule
firehose into a tier that already only grows.

This reverses an earlier draft of this plan, which put G4 fourth while simultaneously
arguing "recall tier before more rule production". The argument was right and the ordering
contradicted it.

**G3 is not first, despite being cheapest.** An earlier draft argued guard telemetry gives
a signal immediately, unlike G2 which needs weeks of data. That assumed guards fire.
There is exactly one guard today — R-0024, on `--no-verify` — and its expected rate in
normal work is near zero; the only time it has ever fired was a deliberate test.
`guards` lists one remaining enforceable candidate (R-0018, a spelling rule), also rare.

So the enforceable subset of the current ledger is close to exhausted, and telemetry over
guards that never fire is telemetry over nothing. G3 stays small and worth doing, but it
pays off only once there are guards that actually trip. Sequenced opportunistically rather
than first.

---

## G1 · The loop needs a human to close it

**Rank by impact:** 1 · **Build order:** 2 · **Size:** large · **Status: shipped v0.1.8**

Capture is automatic; distillation is not. Until this ships, the system is an automatic
front end on a manual pipeline.

**Approach.** Extend the existing scheduled job (`hooks/weekly_extract.*`), which
already re-extracts and archives. Add a third step that runs the distil skill headlessly
against the pending bundle and writes `rules/candidates/<date>.json`.

**The decision that matters: draft, never adopt.** The job produces a candidates file
and stops. Ingest stays manual.

*Why.* A bad rule reaches every session of every project, and the entire two-tier design
rests on global text waiting for an explicit yes. Auto-drafting removes the tedious part
(reading bundles, writing JSON); auto-adopting removes the safeguard. Those are not the
same trade.

**Risks.**
- A headless model run is the first non-stdlib, non-deterministic dependency in a
  scheduled path. It must fail like the hooks do — log and exit 0 — or a bad week breaks
  the weekly job silently.
- Unattended drafting can produce quotes that are not verbatim. Gate it: run `verify`
  against the candidates before writing them, and discard any rule whose evidence fails.

**Unstated dependency, now stated.** A headless run must be able to load the distil skill.
Skills come from the installed plugin, so a checkout running in dev mode with the plugin
disabled cannot do this — the scheduled job needs either the plugin enabled or the skill
body passed explicitly.

**Done when:** the scheduled job produces `rules/candidates/<date>.json` with no command
run by hand, every quote in it passes `verify`, and a failed model call leaves the job
exiting 0 with a line in the log.

---

## G2 · Nothing measures whether a rule worked

**Rank by impact:** 2 · **Build order:** 3 · **Size:** medium · **Status: shipped v0.1.8**

**Approach.** `claude-adapt-rules impact`: corrective-event density per prompt, split
before and after each rule's adoption date, reported **per project rather than pooled**.

*Why per project.* "Controlled for project mix" was hand-waving in an earlier draft. With
7 projects and ~800 prompts, a per-rule-per-project-per-window cell holds a handful of
events — far too few to control anything. Pooling across projects hides the dominant
confound; stratifying exposes that the cells are empty. Reporting per project at least
makes the sample size visible instead of laundering it into one number.

**The decision that matters: refuse to conclude below a sample threshold.** The command
prints sample sizes and, under the threshold, says so instead of printing a verdict.

*Why.* Measured 2026-08-06 the density *rises* — 9.1% → 19.1% → 20.8% across three
months. June is 11 prompts; global rules were adopted 2026-08-04. The number is noise
presented as a trend, and a metric that looks like a verdict will be read as one.

**Confounds to control or state.** Project mix (a hard project raises density regardless
of rules), task difficulty, prompt volume, and the fact that better rules may *increase*
measured corrections early by making the user more willing to correct.

**Depends on:** G3 for a second, independent signal; and on calendar time.

**Done when:** per-rule before/after density with explicit sample size, and an explicit
refusal to conclude when underpowered.

---

## G3 · Guard telemetry

**Rank by impact:** 4 · **Build order:** 5 (opportunistic) · **Size:** small · **Status: shipped v0.1.8**

Not in vision.md's five. Cheap, and a second independent signal for G2 — but only once
guards exist that actually fire. See the sequencing note above: today there is one guard,
on a flag the agent rarely reaches for.

**Approach.** `bin/guard.py` already blocks and writes a reason. Also append a line to a
telemetry file; `rot` reads it and reports fires alongside violations.

**What it buys.** A guard firing is unambiguous — the agent was about to break a rule and
was stopped — and it needs no distillation run to observe. It splits `rot` into *broken
and caught* versus *broken and shipped*, which are different problems: the first says the
guard works, the second says the prose does not.

**Precondition.** Guards that fire. Zero fires is indistinguishable from a working system,
so this only becomes informative alongside guards covering behaviour the agent actually
attempts. Worth revisiting whenever the enforceable set grows.

**Risk.** The guard hook runs in front of every matched tool call. An unbounded append
is a slow leak on a hot path; cap the file and never let a write failure block the call.

**Done when:** `rot` distinguishes caught from shipped.

---

## G4 · The always-on tier only grows

**Rank by impact:** 3 · **Build order:** 1 · **Size:** medium · **Status: shipped v0.1.7**

**What shipped.** `Rule.delivery` (`always` | `on_demand`) plus a mandatory `Rule.trigger`.
`defer` moves a rule out; `defer --promote` brings it back. The always-on block keeps
exactly one line naming the triggers and pointing at `rules/global/ON-DEMAND.md`.

**What the build taught.** The first pointer was two lines, which made the block *longer*
when a single rule was deferred — measured 30 → 31 on the real ledger, defeating the whole
mechanism. The unit test missed it because it deferred three rules at once, where the
saving is real. The pointer is now one line, so deferring one rule is neutral and two or
more is a saving; a test asserts the block never grows.

**Still open:** recall telemetry. Nothing observes whether a deferred rule is ever read,
so the graveyard risk below is real but unmeasured.

A rule is `CLAUDE.md` or nothing. Guards are the only exit, and they only take rules a
regex can decide — a set now close to exhausted. Everything else accumulates: 21 global
rules today, each competing for attention in every prompt of every project.

**Approach.** A third tier between always-on and retired: rules retrieved when relevant
rather than loaded always.

**Schema note.** `scope` cannot carry this. It holds `global` or `repo:<name>` — a
delivery target, not a delivery *mode*. The tier is orthogonal to both: a global rule and
a repo rule can each be always-on or on-demand. It therefore needs its own field, and
must not overload `applies` either, which answers a different question (see below).

**The decision that matters: what makes a rule situational.** Not "less important" —
*conditionally* relevant. A rule about UI theming is worthless in a CLI repo and
essential in a frontend one; importance is unchanged, applicability is not. Getting this
wrong turns the tier into a demotion queue for rules nobody wanted to argue about.

**Risk.** A rule that is never recalled is worse than one that was retired, because it
still looks live in the ledger. Recall needs its own telemetry or the tier becomes a
graveyard.

**Done when:** a rule leaves the always-on block without being retired, and a session
that needs it still receives it.

---

## G5 · The harness itself is unmeasured

**Rank by impact:** 5 · **Build order:** 4 · **Size:** medium · **Status: shipped v0.1.8**

`doctor` reports on the pipeline, not on the thing the pipeline exists to improve.

**Approach.** Inventory skills, agents and hooks: which exist, which ever fire, when
each was last used, what each costs. Transcripts already record skill invocations and
tool calls, so most of this is extraction, not new capture.

**Why last.** It is the prerequisite for the deferred review pass below — reviewing
skills is meaningless without knowing which ones fire — but it changes no session on its
own.

**Done when:** `doctor` lists skills and hooks by last-used and cost, and names the ones
that have never fired.

---

## Rejected for now: a second LLM step to review the rules

Considered and **rejected 2026-08-07**, with triggers for revisiting. Recorded so the
argument is not re-run from scratch — the first pass through it reached "yes", from
plausible use cases that turned out not to exist.

### The reframe

There is already a model in the process: the distil step. So the question is never
"should we add an LLM" but "should we add a *second* one", which is a higher bar. The
existing step is safe for three specific reasons:

1. **Evidence-grounded** — it must quote verbatim.
2. **Verifiable afterwards** — `verify` re-checks every quote against decoded transcript
   text and fails on paraphrase.
3. **Human-gated** — global rules wait for an explicit yes.

A review pass has none of the first two. "These two rules contradict" carries no quote
and admits no mechanical check. It is an opinion in the shape of evidence.

### The gate is weaker than it looks

For distillation the gate is cheap: read the quote, judge it. For "merge R-0007 and
R-0031" the reviewer must re-read both rules and redo the reasoning. That is not review,
it is re-work — and a gate that gets rubber-stamped is worse than none, because it
launders the model's judgement as the user's.

### Measured 2026-08-07: there is no work to do

42 adopted rules (21 global), and:

| claimed use case | actual instances |
| --- | --- |
| consolidation | 1 pair (R-0007 / R-0031 at 50%) — already reported by `near_duplicates` |
| rewording what keeps failing | `rot` escalations: none |
| retiring rules a guard covers | one (R-0024) — already listed by `guards` |
| contradictions | none found by hand |

Zero violations have ever been recorded. Every use case is already surfaced
deterministically or has no instances.

### The case that settled it

The strongest semantic finding token overlap misses is **R-0002** ("name the established
library that already does it") against **R-0010** ("search for an existing implementation
before writing a new one"). Low shared vocabulary, same apparent spirit — a review pass
would very likely propose merging them.

That would be wrong. R-0002 is about third-party libraries; R-0010 is about code already
in the codebase. Different concerns, both worth keeping. The highest-value thing a
semantic review would find in this ledger is a mistake someone has to catch.

### A drift direction nothing measures

Consolidation rewards fewer, more general rules. General rules are exactly the ones
ignored under pressure — which is why the skill already rejects "be mindful of file size"
in favour of "split files over 500 lines". A review pass has a built-in pull toward
vaguer rules and no metric watching for it.

### Do this instead

Strengthen the call that already exists rather than adding one. The distil step has the
ledger in context and the human gate already; ask it, in the same call, to flag when a
candidate contradicts or duplicates an existing rule. Marginal cost near zero, no new
approval surface, and it catches the problem when a rule is born rather than months on.

### Revisit when either trigger fires

- **Rule count outgrows a five-minute read** — roughly 100. At 43 the whole ledger can be
  read directly; at 300 it cannot. Task-Observer's author names the same threshold for
  their own review cycle: the formal cycle pays off as the library grows.
- **`rot` escalates the same rule repeatedly** — a rule broken again after adoption is a
  wording problem, and proposing better wording is the one job a model does better than
  the person who wrote it.

### If it is ever built

Same split as everything else: **model proposes, deterministic code applies**.
`review --bundle` emits ledger plus rot plus guard coverage; the skill writes
`proposals.json`; `apply-review` validates and prints a diff. Three constraints:

1. **May merge, reword, retire, or propose a guard. Never create.** Creation stays on the
   evidence-backed path or rules appear with no quote behind them.
2. **Ids and evidence are immutable.** A reworded rule keeps its id, quotes, adoption date
   and violation count, or rot tracking resets at every review.
3. **Proposals only.** Same reason G1 does not auto-adopt.

**Depends on:** G5, for skill review to mean anything.
