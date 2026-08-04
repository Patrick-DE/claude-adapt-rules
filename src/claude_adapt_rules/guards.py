"""Rules the machine can check, checked by the machine.

A rule in ``CLAUDE.md`` is a suggestion the model weighs against everything else
in context, and the rot report exists precisely because some rules keep getting
broken after adoption. For the subset a regex can decide -- ``--no-verify``, a
banned import, a forbidden command -- weighing is the wrong mechanism: a
PreToolUse hook simply refuses the call.

That subset is already flagged in the ledger as ``enforceable``. What was missing
is the check itself, so a rule stayed prose no matter how often it was violated.
A rule with a ``guard`` is enforced and can then leave the always-on block, which
is the only way that block stops growing.

Guards are read from the ledger at hook time rather than compiled into a
generated script: a generated script goes stale the moment a rule is reworded or
retired, and a stale gate that blocks a legitimate command is worse than no gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .ledger import Ledger, Rule

# Which part of a tool call a guard reads. Matching the whole serialised input
# would let a pattern fire on an unrelated file path, so each tool names the
# field that carries the thing being asked for.
GUARD_FIELDS: dict[str, tuple[str, ...]] = {
    "Bash": ("command",),
    "PowerShell": ("command",),
    "Edit": ("new_string",),
    "MultiEdit": ("new_string",),
    "Write": ("content",),
    "NotebookEdit": ("new_source",),
}

ANY_TOOL = "*"


@dataclass(slots=True)
class Guard:
    rule_id: str
    tool: str
    pattern: re.Pattern[str]
    message: str

    def matches_tool(self, tool_name: str) -> bool:
        return self.tool == ANY_TOOL or self.tool == tool_name


@dataclass(slots=True)
class Violation:
    guard: Guard
    matched: str

    @property
    def reason(self) -> str:
        return f"{self.guard.rule_id}: {self.guard.message} (matched {self.matched!r})"


class GuardError(ValueError):
    """A guard that cannot be compiled. Raised at set time, never at hook time."""


def build_guard(rule: Rule) -> Guard:
    """Compile one rule's guard. Raises GuardError when the spec is unusable."""
    spec = rule.guard or {}
    pattern = str(spec.get("pattern") or "")
    if not pattern:
        raise GuardError(f"{rule.id}: guard has no 'pattern'")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise GuardError(f"{rule.id}: bad pattern {pattern!r} ({exc})") from exc
    return Guard(
        rule_id=rule.id,
        tool=str(spec.get("tool") or ANY_TOOL),
        pattern=compiled,
        message=str(spec.get("message") or rule.rule),
    )


def active_guards(ledger: Ledger) -> list[Guard]:
    """Compiled guards for every adopted rule that has one.

    A guard whose pattern no longer compiles is skipped rather than allowed to
    break every tool call in every project; ``cli guards --set`` validates at
    write time so this stays a theoretical case.
    """
    guards: list[Guard] = []
    for rule in ledger.rules.values():
        if rule.status != "adopted" or not rule.guard:
            continue
        try:
            guards.append(build_guard(rule))
        except GuardError:
            continue
    guards.sort(key=lambda g: g.rule_id)
    return guards


def unguarded_enforceable(ledger: Ledger) -> list[Rule]:
    """Rules flagged mechanically enforceable that are still only prose."""
    rules = [
        r
        for r in ledger.rules.values()
        if r.enforceable and not r.guard and r.status != "retired"
    ]
    rules.sort(key=lambda r: r.id)
    return rules


def _haystacks(tool_name: str, tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        return [str(tool_input)] if tool_input else []
    fields = GUARD_FIELDS.get(tool_name)
    if fields is None:
        return [v for v in tool_input.values() if isinstance(v, str)]
    return [tool_input[f] for f in fields if isinstance(tool_input.get(f), str)]


def check(tool_name: str, tool_input: Any, guards: list[Guard]) -> Violation | None:
    """First guard this call trips, or None. Order is by rule id, so it is stable."""
    texts = _haystacks(tool_name, tool_input)
    for guard in guards:
        if not guard.matches_tool(tool_name):
            continue
        for text in texts:
            if m := guard.pattern.search(text):
                return Violation(guard=guard, matched=m.group(0))
    return None
