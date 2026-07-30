"""Put a project's learned rules in front of the session that needs them.

Distilling rules is worthless if nothing reads them. Measured 2026-07-28: 15 repo
rules existed and not one project's CLAUDE.md mentioned them, so 23 distilled rules
were changing exactly zero sessions.

This renders the current project's rules as SessionStart context. Nothing is written
into other repositories: the rules stay in user state, teammates never see a diff, and
a reworded rule takes effect in the next session without touching any project.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ledger import Ledger, Rule
from .transcripts import project_name_from_cwd

# Injected on every session start, so it is a permanent per-session token cost.
# Rules first, reasons only while there is room.
MAX_RULES = 25
MAX_CHARS = 2500
MAX_WHY_CHARS = 110


@dataclass(slots=True)
class Injection:
    project: str
    rules: list[Rule]
    text: str
    truncated: int = 0


def rules_for_project(project: str, ledger: Ledger) -> list[Rule]:
    scope = f"repo:{project}"
    rules = [r for r in ledger.by_scope(scope) if r.status != "retired"]
    rules.sort(key=lambda r: (r.category, r.id))
    return rules


def _render(project: str, rules: list[Rule], include_why: bool) -> str:
    lines = [
        f"# Learned rules for {project} (claude-learn)",
        "",
        "Distilled from corrections the user already gave in this repository. Follow them",
        "as you would the project's own instructions; if one looks wrong, say so instead of",
        "silently ignoring it.",
        "",
    ]
    by_category: dict[str, list[Rule]] = {}
    for rule in rules:
        by_category.setdefault(rule.category, []).append(rule)
    for category, group in by_category.items():
        lines.append(f"**{category}**")
        for rule in group:
            lines.append(f"- {rule.id} {rule.rule.rstrip('.')}.")
            if include_why and rule.why:
                why = rule.why.strip()
                if len(why) > MAX_WHY_CHARS:
                    why = why[:MAX_WHY_CHARS].rstrip() + "…"
                lines.append(f"  - why: {why}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build(cwd: str, ledger: Ledger | None = None) -> Injection | None:
    """Context for this working directory, or None when there is nothing to say."""
    project = project_name_from_cwd(cwd)
    if not project:
        return None
    ledger = ledger or Ledger()
    rules = rules_for_project(project, ledger)
    if not rules:
        return None

    truncated = max(0, len(rules) - MAX_RULES)
    kept = rules[:MAX_RULES]
    text = _render(project, kept, include_why=True)
    if len(text) > MAX_CHARS:
        # Drop the reasons before dropping rules: a rule the agent never sees cannot
        # be followed, while a rule without its reason still can.
        text = _render(project, kept, include_why=False)
    if truncated:
        text += (
            f"\n{truncated} further rule(s) omitted; see "
            f"~/.claude-learn/rules/repos/{project}/rules.md\n"
        )
    return Injection(project=project, rules=kept, text=text, truncated=truncated)


def session_start_payload(cwd: str, ledger: Ledger | None = None) -> dict | None:
    """The JSON a SessionStart hook prints to add context, or None to stay silent."""
    injection = build(cwd, ledger)
    if injection is None:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": injection.text,
        },
        "suppressOutput": True,
    }


def rules_file(project: str, root: Path | None = None) -> Path:
    from .extract import rules_dir

    return (root or rules_dir()) / "repos" / project / "rules.md"
