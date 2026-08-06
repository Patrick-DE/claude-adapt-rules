"""Put learned rules in front of the person writing the next skill or agent.

Rules currently reach *sessions* -- a SessionStart hook injects a project's rules
as context. Nothing reaches *authoring*: a new skill, agent or CLAUDE.md gets
written without the constraints its author already established, so the same
correction gets learned again through the new artifact.

Credit for the idea: Task-Observer by Eoghan Henn (rebelytics) captures
"cross-cutting principles" separately and applies them when skills are written
or updated. https://github.com/rebelytics/one-skill-to-rule-them-all (CC BY 4.0)

Output is a paste-ready block rather than an automatic edit. Writing into
someone's skill file uninvited is the behaviour this project exists to correct.
"""

from __future__ import annotations

from collections.abc import Sequence

from .ledger import Ledger, Rule

# An authoring checklist competes with the spec the author is holding in their
# head. Past this it stops being read.
MAX_RULES = 20


def constraints_for(project: str, ledger: Ledger) -> list[Rule]:
    """Adopted rules that should shape a new artifact for this project.

    Global first: those hold everywhere, so they belong at the top of anything
    being written. Project rules follow, and only when a project is named.
    """
    adopted = [r for r in ledger.rules.values() if r.status == "adopted"]
    globals_ = sorted(
        (r for r in adopted if r.scope == "global"), key=lambda r: (r.category, r.id)
    )
    local = sorted(
        (r for r in adopted if r.scope == f"repo:{project}"),
        key=lambda r: (r.category, r.id),
    )
    return [*globals_, *local]


def render(project: str, rules: Sequence[Rule], limit: int = MAX_RULES) -> str:
    """A block to paste into the skill, agent or instructions file being written."""
    scope = f"{project} and everywhere" if project else "every project"
    lines = [
        f"# Constraints for new work in {scope}",
        "",
        "Distilled from corrections already given. Whatever you are writing -- a skill,",
        "an agent, an instructions file -- must not contradict these, and should not",
        "restate them either: they are already delivered to every session.",
        "",
    ]
    if not rules:
        lines += ["_No adopted rules yet._", ""]
        return "\n".join(lines)

    kept = list(rules[:limit])
    by_category: dict[str, list[Rule]] = {}
    for rule in kept:
        by_category.setdefault(rule.category, []).append(rule)
    for category, group in by_category.items():
        lines.append(f"**{category}**")
        for rule in group:
            tier = "global" if rule.scope == "global" else "this repo"
            lines.append(f"- {rule.id} ({tier}) {rule.rule.rstrip('.')}.")
        lines.append("")
    if len(rules) > limit:
        lines.append(f"_{len(rules) - limit} lower-priority rule(s) omitted._")
        lines.append("")
    return "\n".join(lines)
