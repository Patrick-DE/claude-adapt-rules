"""Did adopting a rule change anything?

`rot` answers this only indirectly: a violation is recorded when a *new candidate*
matches an adopted rule, which requires the manual distil step to have run. The
feedback signal is coupled to the thing that is not automatic.

This measures directly instead: the share of human prompts that carried correction
signal, before and after a rule's adoption date.

**It is very easy to over-read.** Measured 2026-08-06 the density *rose* across
three months (9.1% -> 19.1% -> 20.8%) while rules were being adopted, which says
nothing about the rules: June held 11 prompts, and the global block was adopted
two days before the measurement. Density also moves with project mix, task
difficulty, and how willing the user is to correct at all — a better-behaved agent
can raise measured corrections by making correction feel worthwhile.

So the module reports per project rather than pooling, always states sample size,
and refuses to draw a conclusion below `MIN_PROMPTS_PER_WINDOW`. A number that
looks like a verdict will be read as one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from .ledger import Ledger, Rule
from .signals import score_session, select
from .transcripts import Session

# Below this, a window is an anecdote. Chosen so a fortnight of ordinary use in one
# project clears it; deliberately not tuned to make the current data look decisive.
MIN_PROMPTS_PER_WINDOW = 50

# A difference smaller than this is noise at any sample size this system will see.
MIN_MEANINGFUL_DELTA = 5.0


@dataclass(slots=True)
class Window:
    prompts: int = 0
    corrections: int = 0

    @property
    def density(self) -> float:
        return 100.0 * self.corrections / self.prompts if self.prompts else 0.0


@dataclass(slots=True)
class ProjectImpact:
    project: str
    before: Window
    after: Window

    @property
    def underpowered(self) -> bool:
        return min(self.before.prompts, self.after.prompts) < MIN_PROMPTS_PER_WINDOW

    @property
    def delta(self) -> float:
        return self.after.density - self.before.density

    @property
    def verdict(self) -> str:
        """Deliberately refuses more often than it concludes."""
        if self.underpowered:
            return "no conclusion (too few prompts)"
        if abs(self.delta) < MIN_MEANINGFUL_DELTA:
            return "no measurable change"
        return "corrections fell" if self.delta < 0 else "corrections rose"


def _prompt_rows(sessions: Iterable[Session]) -> list[tuple[str, str, bool]]:
    """(timestamp, project, was_corrective) for every human prompt."""
    rows: list[tuple[str, str, bool]] = []
    for session in sessions:
        corrective = {e.prompt.uuid for e in select(score_session(session.prompts))}
        for prompt in session.prompts:
            if not prompt.ts:
                continue
            rows.append(
                (prompt.ts, prompt.project_name or prompt.project, prompt.uuid in corrective)
            )
    return rows


def for_rule(rule: Rule, rows: Sequence[tuple[str, str, bool]]) -> list[ProjectImpact]:
    """Per-project before/after for one adopted rule.

    Pooling across projects would hide the dominant confound; stratifying exposes
    that most cells are empty, which is the honest result.
    """
    if not rule.adopted:
        return []
    cut = rule.adopted
    per_project: dict[str, ProjectImpact] = {}
    for ts, project, corrective in rows:
        entry = per_project.setdefault(project, ProjectImpact(project, Window(), Window()))
        window = entry.before if ts < cut else entry.after
        window.prompts += 1
        window.corrections += int(corrective)
    return sorted(per_project.values(), key=lambda e: e.project)


def render(ledger: Ledger, sessions: Iterable[Session], rule_ids: Sequence[str] = ()) -> str:
    rows = _prompt_rows(sessions)
    rules = [
        r
        for r in ledger.rules.values()
        if r.status == "adopted" and r.adopted and (not rule_ids or r.id in rule_ids)
    ]
    rules.sort(key=lambda r: r.id)

    lines = [
        "# Rule impact",
        "",
        f"Generated {datetime.now(tz=timezone.utc).date()} · "
        f"{len(rows)} human prompt(s) across the transcript store.",
        "",
        "Share of prompts carrying correction signal, before and after each rule was",
        "adopted, per project. Confounded by project mix, task difficulty, and by the",
        "fact that a more useful agent can *raise* measured corrections by making them",
        f"worth giving. Windows under {MIN_PROMPTS_PER_WINDOW} prompts draw no conclusion.",
        "",
    ]
    if not rules:
        lines += ["_No adopted rules with an adoption date._", ""]
        return "\n".join(lines)

    conclusive = 0
    for rule in rules:
        impacts = for_rule(rule, rows)
        usable = [i for i in impacts if not i.underpowered]
        conclusive += len(usable)
        lines += [f"## {rule.id} · adopted {rule.adopted[:10]}", "", f"_{rule.rule[:100]}_", ""]
        if not impacts:
            lines += ["No prompts on either side of the adoption date.", ""]
            continue
        lines += [
            "| project | before | after | change | verdict |",
            "| --- | --- | --- | --- | --- |",
        ]
        for i in impacts:
            b, a = i.before, i.after
            lines.append(
                f"| {i.project} | {b.density:.1f}% (n={b.prompts}) | "
                f"{a.density:.1f}% (n={a.prompts}) | {i.delta:+.1f}pp | {i.verdict} |"
            )
        lines.append("")

    if not conclusive:
        lines += [
            "**Nothing here is conclusive yet.** Every window is below the minimum, which",
            "is expected while the rules are young — the measurement will only start",
            "saying something after weeks of use on both sides of an adoption date.",
            "",
        ]
    return "\n".join(lines)
