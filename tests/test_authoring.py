"""Rules reach sessions; without this they never reach the person authoring.

Idea credited to Task-Observer (rebelytics, CC BY 4.0), which applies its
cross-cutting principles when skills are written, not only when they are run.
"""

from __future__ import annotations

import json

from claude_adapt_rules.authoring import constraints_for, render
from claude_adapt_rules.ledger import Evidence, Ledger, Rule


def _rule(rid: str, scope: str, status: str = "adopted", category: str = "process") -> Rule:
    return Rule(
        id=rid,
        rule=f"Rule body {rid}",
        why="",
        category=category,
        scope=scope,
        evidence=[Evidence(session="s", ts="2026-08-01", quote="q")],
        status=status,
    )


def _ledger(tmp_path, rules) -> Ledger:
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps({"schema": 1, "next_id": 9, "rules": [r.to_dict() for r in rules]}),
        encoding="utf-8",
    )
    return Ledger(path)


def test_global_rules_come_before_this_project_s(tmp_path):
    """Global holds everywhere, so it belongs at the top of anything being written."""
    ledger = _ledger(
        tmp_path, [_rule("R-0002", "repo:app"), _rule("R-0001", "global")]
    )
    assert [r.id for r in constraints_for("app", ledger)] == ["R-0001", "R-0002"]


def test_another_project_s_rules_are_excluded(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0001", "repo:other"), _rule("R-0002", "global")])
    assert [r.id for r in constraints_for("app", ledger)] == ["R-0002"]


def test_unadopted_rules_are_excluded(tmp_path):
    """A proposed global has not been agreed to; it must not constrain new work."""
    ledger = _ledger(
        tmp_path,
        [
            _rule("R-0001", "global", status="proposed"),
            _rule("R-0002", "global", status="retired"),
            _rule("R-0003", "global"),
        ],
    )
    assert [r.id for r in constraints_for("app", ledger)] == ["R-0003"]


def test_no_project_still_yields_the_global_tier(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0001", "global"), _rule("R-0002", "repo:app")])
    assert [r.id for r in constraints_for("", ledger)] == ["R-0001"]


def test_render_marks_tier_and_states_truncation(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0001", "global"), _rule("R-0002", "repo:app")])
    rules = constraints_for("app", ledger)
    text = render("app", rules)
    assert "R-0001 (global)" in text
    assert "R-0002 (this repo)" in text
    assert "1 lower-priority rule(s) omitted" in render("app", rules, limit=1)
    assert "_No adopted rules yet._" in render("app", [])
