# Vision: a harness that improves itself through use

**Status:** living document · last reviewed 2026-08-06 · owner: Patrick Eisenschmidt

## The goal

Every correction the user gives should cost them once. The second time the agent
would make the same mistake, something in the harness should already have changed —
without the user having to notice, remember, or run anything.

That is the whole ambition. Everything below is measured against it.

## Principles already earned

These are not aspirations; each was paid for by a defect in this repo.

1. **Capture is deterministic, judgement is the model's, application is tiered.**
   Parsing and scoring never call a model, so the expensive step reads a few hundred
   focused events instead of a transcript store.
2. **Blast radius decides the policy.** A repo rule is auto-written because it is one
   project and a `git diff` from gone. A global rule is loaded into every session of
   every project, so it waits for an explicit yes.
3. **Evidence is verbatim or it is nothing.** A rule cites words the user actually
   wrote, greppable back to the transcript, re-checked by `verify`, preserved by
   `archive` against the 30-day cleanup. Decay must never look like fabrication.
4. **Generality is judged, not counted.** "Never commit code that does not build" is
   universal after being said once. A local quirk repeated fifty times is still local.
   A `universal` claim naming a path or identifier is vetoed automatically.
5. **A rule broken after adoption is a fact about the rule, not the agent.** That is
   what `ingest`'s violation path and `rot` exist to surface.
6. **Prose is for judgement calls.** Anything a regex can decide belongs in a hook,
   where it is refused rather than weighed against everything else in context.
7. **Never silently degrade.** The hooks fail open *and log*, because they sit in
   front of every session. Everything else fails loudly. A truncated ledger is a
   fault, not an empty install.

## What the loop covers today

```
SessionEnd hook ──► queue ──► [human runs the skill] ──► ledger
                                                          │
                    repo rules ──► SessionStart inject ◄───┤
                    global rules ──► CLAUDE.md block   ◄───┤
                    guarded rules ──► PreToolUse refusal ◄─┘
```

Plus `workflows` (work repeated by hand), `constraints` (rules for what you write
next), and `doctor` / `rot` / `verify` for hygiene.

## Where this still fails the vision

Ranked by how much they block "without the user having to run anything".

### 1. The loop is not a loop — a human closes it

Capture is automatic. Everything after it is not. The queue fills silently until
someone remembers, which is why `doctor` now reports the *age* of the oldest pending
event rather than just a count. Until distillation runs unattended, this is a
semi-automatic system with an automatic front end.

### 2. Nothing measures whether a rule worked

`rot` counts violations, but a violation is only recorded when a *new candidate*
matches an adopted rule — which requires the manual step to run. The feedback signal
is coupled to the thing that isn't automatic.

A direct measure is computable from data already on disk: corrective-event density
per prompt, over time, split before and after each rule's adoption date. Measured
2026-08-06:

| month | corrections / prompts | density |
| --- | --- | --- |
| 2026-06 | 1 / 11 | 9.1% |
| 2026-07 | 125 / 654 | 19.1% |
| 2026-08 | 27 / 130 | 20.8% |

**This currently proves nothing** and must not be presented as if it did. June is 11
prompts. Global rules were adopted 2026-08-04, so there is no post-adoption window
yet. Density is also confounded by project mix and by task difficulty. The mechanism
is buildable now; the signal needs weeks, and a control for which projects were
active.

### 3. Only one artifact improves

The system produces *rules*. It does not produce or improve *skills*, *agents*, or
*hooks*. `workflows` finds work repeated by hand — the input to a skill — but nothing
turns a candidate into a draft, and nothing reviews an existing skill against what
sessions later revealed.

### 4. Two tiers, and the top one only grows

A rule is either always-on (`CLAUDE.md`, a permanent token cost in every session of
every project) or nothing. Guards are the only exit: a rule a regex can decide leaves
the block. Everything else accumulates. Missing is a **recall-on-demand tier** for
rules that are valuable but situational — too specific to pay for in every prompt,
too useful to retire.

### 5. The harness itself is unmeasured

`doctor` reports on the pipeline. Nothing reports on the harness the pipeline is
meant to improve: which skills actually fire, which never do, which agents get used,
whether a rule contradicts an existing instruction elsewhere.

## Constraints any addition must respect

- **Stdlib-only runtime.** The SessionEnd hook imports this package on every session
  exit; a dependency here breaks unrelated work in unrelated projects.
- **Hooks fail open and log.** Anything placed in front of a session or a tool call
  must not be able to brick either.
- **State lives in `~/.claude-adapt-rules/`,** never the install directory — a plugin
  update replaces that directory.
- **Always-on text is the scarcest resource.** Adding to `CLAUDE.md` competes for
  attention with everything else there. Prefer a hook, then on-demand recall, then
  prose — in that order.
- **Skill files stay short.** The instructions the model loads should be the trigger
  and the decision procedure; depth belongs in files loaded on demand.
- **Nothing writes into the user's other repositories.** Rules reach a session through
  injected context, so teammates never see a diff.

## Related

- [roadmap.md](roadmap.md) — the checklist derived from the gaps above
- [../README.md](../README.md) — what the system does today
- [../skills/claude-adapt-rules/SKILL.md](../skills/claude-adapt-rules/SKILL.md) — the
  model-facing distillation procedure
