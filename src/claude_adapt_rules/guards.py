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

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atomic import write_text_atomic
from .ledger import Ledger, Rule

# Which part of a tool call a guard reads. Matching the whole serialised input
# would let a pattern fire on an unrelated file path, so each tool names the
# field that carries the thing being asked for.
# MultiEdit is deliberately absent: its input nests the edits under `edits`, so a
# top-level "new_string" key never exists and a guard on it would silently never
# fire. An unmapped tool falls through to scanning every string value, which
# over-matches rather than failing open -- the right direction for a gate.
GUARD_FIELDS: dict[str, tuple[str, ...]] = {
    "Bash": ("command",),
    "PowerShell": ("command",),
    "Edit": ("new_string",),
    "Write": ("content",),
    "NotebookEdit": ("new_source",),
}

ANY_TOOL = "*"

# Longest text a guard pattern is run over. `re` has no timeout, and a
# user-authored pattern with nested quantifiers is quadratic or worse: measured,
# `(a+)+$` took 26 s on 28 characters, which the hook would pay on every call.
# Truncating bounds the damage; BAD_PATTERN_RE below stops it being stored.
MAX_HAYSTACK = 4000

# Nested quantifiers -- `(x+)+`, `(x*)*`, `(x+)*` -- are the classic catastrophic
# backtracking shape. Refused at set time rather than discovered at hook time.
BAD_PATTERN_RE = re.compile(r"\([^)]*[+*][^)]*\)\s*[+*]")


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
    if BAD_PATTERN_RE.search(pattern):
        raise GuardError(
            f"{rule.id}: pattern {pattern!r} nests quantifiers, which can backtrack "
            f"catastrophically and stall every guarded tool call. Rewrite it without "
            f"a repeated group."
        )
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
        except GuardError as exc:
            # Skipping keeps the session alive, but silently skipping means a
            # typo'd pattern stops enforcing and nothing ever says so.
            _log_broken_guard(exc)
    guards.sort(key=lambda g: g.rule_id)
    return guards


def _log_broken_guard(exc: GuardError) -> None:
    """Record a guard that could not be compiled. Never raises."""
    try:
        from datetime import datetime, timezone

        from .extract import data_dir

        target = data_dir()
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        with (target / "hook.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] guard disabled: {exc}\n")
    except OSError:
        pass


def unguarded_enforceable(ledger: Ledger) -> list[Rule]:
    """Rules flagged mechanically enforceable that are still only prose."""
    rules = [
        r
        for r in ledger.rules.values()
        if r.enforceable and not r.guard and r.status != "retired"
    ]
    rules.sort(key=lambda r: r.id)
    return rules


_MAX_DEPTH = 6


def _walk_strings(value: Any, depth: int = 0) -> list[str]:
    """Every string anywhere in a tool input, including nested ones.

    Taking only top-level string values missed nested payloads entirely -- a
    tool whose edits live in ``edits: [{new_string: ...}]`` would be scanned as
    just its file path, so the guard silently never fired.
    """
    if depth > _MAX_DEPTH:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _walk_strings(v, depth + 1)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _walk_strings(v, depth + 1)]
    return []


FIRES_FILENAME = "guard-fires.jsonl"

# The guard hook runs in front of every matched tool call, so this file is on a hot
# path. Capped rather than rotated: the interesting number is "is this guard still
# catching things", which the recent tail answers as well as the whole history.
MAX_FIRES_BYTES = 256_000


def record_fire(violation: Violation, ts: str, out: Path | None = None) -> None:
    """Append one blocked call. Never raises: a telemetry failure must not gate a tool."""
    try:
        from .extract import data_dir

        target = (out or data_dir()) / FIRES_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > MAX_FIRES_BYTES:
            kept = target.read_text(encoding="utf-8", errors="replace").splitlines()
            keep_from = len(kept) // 2
            write_text_atomic(target, "\n".join(kept[keep_from:]) + "\n")
        with target.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"ts": ts, "rule": violation.guard.rule_id,
                     "tool": violation.guard.tool, "matched": violation.matched},
                    ensure_ascii=False,
                )
                + "\n"
            )
    except (OSError, ValueError):
        pass


def fire_counts(out: Path | None = None) -> dict[str, int]:
    """Blocked calls per rule id. A guard that never fires is telling you something."""
    from .extract import data_dir

    target = (out or data_dir()) / FIRES_FILENAME
    counts: dict[str, int] = {}
    if not target.is_file():
        return counts
    with target.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if rule := str(rec.get("rule") or ""):
                counts[rule] = counts.get(rule, 0) + 1
    return counts


def _haystacks(tool_name: str, tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        texts = [str(tool_input)] if tool_input else []
    else:
        fields = GUARD_FIELDS.get(tool_name)
        if fields is None:
            # Unmapped tool: scan everything. Over-matching is the safe direction
            # for a gate; silently never firing is not.
            texts = _walk_strings(tool_input)
        else:
            texts = [tool_input[f] for f in fields if isinstance(tool_input.get(f), str)]
    return [t[:MAX_HAYSTACK] for t in texts]


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
