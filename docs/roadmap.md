# Roadmap

**Status:** active · last reviewed 2026-08-06 · derived from [vision.md](vision.md)
**Build order and rationale:** [plan.md](plan.md) — it differs from the impact order below.

Ordered below by how much each closes the gap between "captures automatically" and
"improves automatically". **That is impact order, not build order** — see
[plan.md](plan.md), which builds B1 first because everything that produces more rules
makes the always-on tier worse until it has an exit.

Each item states the acceptance test, because a feature here is only done when it changes
a session — not when it merges.

## A · Close the loop (blocks the vision directly)

- [x] **A1 · Unattended distillation** (v0.1.8). `weekly_extract` already re-extracts and
  archives on a schedule; it stops short of distilling because that needs a model.
  Add a headless step that runs the skill against the pending bundle and writes a
  candidates file for review — not straight into the ledger.
  *Why not auto-ingest:* a bad rule reaches every session, and the whole design says
  global text waits for a human yes. Auto-drafting is safe; auto-adopting is not.
  Opt-in via `CLAUDE_ADAPT_RULES_DISTIL=1` in the weekly job; drafts candidates and
  stops. `check-candidates` is the gate that replaces the human reader — it rejects any
  candidate whose quote is not verbatim in the session it cites, including one whose
  transcript has expired. *Caveat:* needs the `claude` CLI on PATH, which this machine
  does not currently have, so the branch is verified to skip cleanly rather than to run.

- [x] **A2 · Adherence metric** (v0.1.8). Corrective-event density per prompt, split before and
  after each rule's adoption date, controlled for which projects were active.
  *Care required:* the raw numbers currently rise over time (9.1% → 19.1% → 20.8%) and
  mean nothing yet — see vision.md §2. Ship the measurement with its confounds stated
  in the output, or it will be read as a verdict.
  `impact` reports per project rather than pooling, always prints n, and refuses to
  conclude under 50 prompts a side. *Live result: every window refuses* — including a
  100% → 20% swing on n=2, which is exactly the misreading the refusal exists to stop.

- [x] **A3 · Guard telemetry into `rot`** (v0.1.8). A guard firing is the one unambiguous signal
  that a rule was about to be broken, and it needs no distillation run to observe.
  Log fires, feed the count into `rot` alongside violations.
  `rot` now leads with blocked calls. Fires are capped (the hook is on a hot path) and a
  telemetry failure can never gate a tool call. Currently 0 blocks — honest, since one
  guard covers one rare flag.

## B · Improve more than rules

- [x] **B1 · A recall-on-demand tier** (v0.1.7). `defer R-00XX --trigger "..."` moves a
  rule out of the always-on block while it stays adopted; the block keeps one line naming
  the triggers and pointing at `rules/global/ON-DEMAND.md`. A trigger is mandatory,
  because an on-demand rule with no stated condition is one nothing will ever read.
  *Verified live:* R-0008 (UI theming) deferred, block 30 → 28 lines, rule still reachable.

- [ ] **B2 · Draft a skill from a workflow candidate.** `workflows` already finds work
  repeated by hand. Turn a candidate into a `SKILL.md` draft: trigger description
  first (that is what decides whether it ever fires), procedure second, depth in
  reference files loaded on demand.
  **Done when:** a candidate produces a draft the user edits and installs, and the
  sequence stops recurring in the next `workflows` run.

- [ ] **B3 · Review existing skills against later evidence.** A skill written in June
  may contradict a rule learned in August. Nothing checks.
  **Done when:** a command reports skills whose instructions conflict with an adopted
  rule.

## C · Harness hygiene

- [ ] **C1 · Consistency lint.** Rules can duplicate or contradict `CLAUDE.md`, a
  project's own instructions, or each other. `near_duplicates` covers rule-vs-rule
  only, and only at ingest.
  **Done when:** one command reports contradictions and duplication across the ledger,
  the global block, and project instruction files.

- [x] **C2 · Harness inventory** (v0.1.8). Which skills exist, which ever fire, which agents get
  used, how long each hook takes. An unused skill is context cost with no return; a
  slow hook is paid on every call (the guard hook measured ~209 ms, which is why it is
  scoped to one tool).
  `harness` reports skills, agents and tools by use count, project spread and last-used,
  plus installed-but-never-observed. *Live: 9 skills and 13 agents ever fired.*

## Done

- [x] **Two-tier delivery** — repo rules auto-written and injected at SessionStart;
  global rules proposed, adopted by name, spliced into `CLAUDE.md`.
- [x] **Evidence integrity** — verbatim quotes, `verify` against decoded text,
  `archive` against the 30-day cleanup, expiry distinguished from fabrication.
- [x] **Generality judged, not counted** — `applies` with an automatic veto; scope is
  never widened by evidence count once judged.
- [x] **Guards** — the regex-decidable subset enforced by a `PreToolUse` hook instead
  of weighed as prose (v0.1.2).
- [x] **Coverage gaps** — `workflows` finds work repeated by hand, which no corrective
  signal can reach (v0.1.2).
- [x] **Authoring constraints** — `constraints` puts adopted rules in front of the next
  skill or agent file written (v0.1.2).
- [x] **Cadence pressure** — `doctor` reports the age of the oldest undistilled event,
  not just the count (v0.1.2).
- [x] **State integrity** — atomic whole-file writes; a truncated ledger is a fault,
  not an empty install (v0.1.4, v0.1.5).
