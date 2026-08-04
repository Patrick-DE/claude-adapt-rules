"""A rule the machine can check must be checked by the machine, not weighed.

R-0024 ("never commit code that does not build") was flagged enforceable and
adopted as prose anyway, which is exactly the shape the rot report keeps
reporting: adopted, still violated.
"""

from __future__ import annotations

import json

import pytest

from claude_adapt_rules.guards import (
    ANY_TOOL,
    GuardError,
    active_guards,
    build_guard,
    check,
    unguarded_enforceable,
)
from claude_adapt_rules.ledger import Evidence, Ledger, Rule


def _rule(rid: str, **kw) -> Rule:
    base = dict(
        id=rid,
        rule="Never commit with hooks disabled.",
        why="",
        category="process",
        scope="global",
        evidence=[Evidence(session="s", ts="2026-08-01", quote="q")],
        status="adopted",
    )
    return Rule(**{**base, **kw})


def _ledger(tmp_path, rules) -> Ledger:
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps({"schema": 1, "next_id": 99, "rules": [r.to_dict() for r in rules]}),
        encoding="utf-8",
    )
    return Ledger(path)


NO_VERIFY = {"tool": "Bash", "pattern": r"--no-verify", "message": "hooks are the gate"}


def test_a_guarded_rule_refuses_the_call(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0024", guard=NO_VERIFY)])
    violation = check(
        "Bash", {"command": "git commit --no-verify -m wip"}, active_guards(ledger)
    )
    assert violation is not None
    assert violation.guard.rule_id == "R-0024"
    assert "hooks are the gate" in violation.reason
    assert "--no-verify" in violation.reason


def test_an_innocent_call_passes(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0024", guard=NO_VERIFY)])
    assert check("Bash", {"command": "git commit -m wip"}, active_guards(ledger)) is None


def test_a_guard_only_reads_the_field_that_carries_the_request(tmp_path):
    """Otherwise a pattern fires on an unrelated path in the same tool input."""
    ledger = _ledger(tmp_path, [_rule("R-0024", guard=NO_VERIFY)])
    guards = active_guards(ledger)
    assert check("Bash", {"command": "ls", "description": "--no-verify"}, guards) is None


def test_a_guard_is_scoped_to_its_tool(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0024", guard=NO_VERIFY)])
    guards = active_guards(ledger)
    assert check("Write", {"content": "git commit --no-verify"}, guards) is None

    wildcard = dict(NO_VERIFY, tool=ANY_TOOL)
    guards = active_guards(_ledger(tmp_path, [_rule("R-0024", guard=wildcard)]))
    assert check("Write", {"content": "git commit --no-verify"}, guards) is not None


def test_only_adopted_rules_are_enforced(tmp_path):
    """A proposed rule has not been agreed to; it must not block anything yet."""
    ledger = _ledger(tmp_path, [_rule("R-0024", guard=NO_VERIFY, status="proposed")])
    assert active_guards(ledger) == []


def test_an_uncompilable_guard_never_reaches_the_hook(tmp_path):
    """Failing closed here would break every tool call in every project."""
    broken = dict(NO_VERIFY, pattern="(unclosed")
    ledger = _ledger(tmp_path, [_rule("R-0024", guard=broken)])
    assert active_guards(ledger) == []
    with pytest.raises(GuardError):
        build_guard(_rule("R-0024", guard=broken))


def test_guard_without_a_pattern_is_rejected():
    with pytest.raises(GuardError):
        build_guard(_rule("R-0024", guard={"tool": "Bash"}))


def test_enforceable_rules_without_a_guard_are_listed(tmp_path):
    """The gap between "a hook could catch this" and "a hook does" is the work list."""
    ledger = _ledger(
        tmp_path,
        [
            _rule("R-0024", enforceable=True),
            _rule("R-0025", enforceable=True, guard=NO_VERIFY),
            _rule("R-0026", enforceable=False),
            _rule("R-0027", enforceable=True, status="retired"),
        ],
    )
    assert [r.id for r in unguarded_enforceable(ledger)] == ["R-0024"]


def test_old_ledgers_load_without_a_guard_field(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "next_id": 2,
                "rules": [
                    {
                        "id": "R-0001",
                        "rule": "x",
                        "why": "",
                        "category": "process",
                        "scope": "global",
                        "evidence": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert Ledger(path).rules["R-0001"].guard == {}
