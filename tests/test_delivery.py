"""A rule must be able to leave the always-on block without being retired.

Before this, a rule was CLAUDE.md or nothing. Guards were the only exit and they
only take the subset a regex can decide, so the always-on block -- loaded into
every prompt of every project -- could only grow.
"""

from __future__ import annotations

import json

from claude_adapt_rules import cli
from claude_adapt_rules import render as render_mod
from claude_adapt_rules.ledger import ALWAYS, ON_DEMAND, Evidence, Ledger, Rule


def _rule(rid: str, category: str = "style", **kw) -> Rule:
    base = dict(
        id=rid,
        rule=f"Body of {rid}",
        why=f"reason for {rid}",
        category=category,
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


def test_a_deferred_rule_leaves_the_block_but_stays_adopted(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0001"), _rule("R-0002")])
    assert ledger.defer("R-0002", "building UI components") is not None

    block = render_mod.render_global_block(ledger)
    assert "R-0001" in block
    assert "R-0002" not in block  # gone from the always-on cost
    assert ledger.rules["R-0002"].status == "adopted"  # but not retired
    assert ledger.rules["R-0002"].delivery == ON_DEMAND


def test_the_block_names_the_trigger_so_recall_is_possible(tmp_path):
    """A pointer that only says "more rules elsewhere" is never followed."""
    ledger = _ledger(tmp_path, [_rule("R-0001"), _rule("R-0002")])
    ledger.defer("R-0002", "building UI components")

    block = render_mod.render_global_block(ledger)
    assert "building UI components" in block
    assert render_mod.ON_DEMAND_FILENAME in block


def test_the_deferred_rule_is_reachable_in_full(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0002")])
    ledger.defer("R-0002", "building UI components")

    text = render_mod.render_on_demand(ledger)
    assert "## When: building UI components" in text
    assert "Body of R-0002" in text
    assert "reason for R-0002" in text


def test_deferring_never_makes_the_block_longer(tmp_path):
    """The pointer costs one line, so deferring one rule is at worst neutral.

    A two-line pointer took the real block from 30 to 31 lines when a single rule
    was deferred, which defeats the mechanism entirely.
    """
    rules = [_rule(f"R-{i:04d}", category=f"cat{i}") for i in range(1, 6)]
    ledger = _ledger(tmp_path, rules)
    before = render_mod.block_line_count(render_mod.render_global_block(ledger))

    ledger.defer("R-0005", "a narrow situation")
    one = render_mod.block_line_count(render_mod.render_global_block(ledger))
    assert one <= before

    for rule in rules[1:4]:
        ledger.defer(rule.id, "a narrow situation")
    many = render_mod.block_line_count(render_mod.render_global_block(ledger))
    assert many < before


def test_rules_sharing_a_trigger_are_listed_once(tmp_path):
    """The pointer must not repeat a trigger per rule, or it grows with the tier."""
    rules = [_rule(f"R-{i:04d}", category=f"cat{i}") for i in range(1, 5)]
    ledger = _ledger(tmp_path, rules)
    for rule in rules:
        ledger.defer(rule.id, "building UI")
    block = render_mod.render_global_block(ledger)
    assert block.count("building UI") == 1


def test_a_rule_cannot_be_deferred_without_a_trigger(tmp_path):
    """Unreachable is worse than retired: it still looks live in the ledger."""
    ledger = _ledger(tmp_path, [_rule("R-0001")])
    assert ledger.defer("R-0001", "   ") is None
    assert ledger.rules["R-0001"].delivery == ALWAYS


def test_promoting_brings_a_rule_back(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0001")])
    ledger.defer("R-0001", "some trigger")
    assert "R-0001" not in render_mod.render_global_block(ledger)

    ledger.promote_delivery("R-0001")
    assert "R-0001" in render_mod.render_global_block(ledger)


def test_no_pointer_line_when_nothing_is_deferred(tmp_path):
    ledger = _ledger(tmp_path, [_rule("R-0001")])
    assert "on demand" not in render_mod.render_global_block(ledger)


def test_old_ledgers_default_to_always_on(tmp_path):
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
    rule = Ledger(path).rules["R-0001"]
    assert rule.delivery == ALWAYS and rule.trigger == ""


def test_cli_defer_refuses_without_a_trigger(tmp_path, capsys):
    ledger = _ledger(tmp_path, [_rule("R-0001")])
    assert cli.main(["defer", "R-0001", "--ledger", str(ledger.path)]) == 2
    assert "--trigger is required" in capsys.readouterr().out


def test_cli_defer_writes_both_tiers(tmp_path, capsys):
    ledger = _ledger(tmp_path, [_rule("R-0001"), _rule("R-0002")])
    code = cli.main(
        ["defer", "R-0002", "--trigger", "designing a schema", "--ledger", str(ledger.path)]
    )
    assert code == 0

    block = (tmp_path / "global" / "ADOPTED.md").read_text(encoding="utf-8")
    on_demand = (tmp_path / "global" / render_mod.ON_DEMAND_FILENAME).read_text(encoding="utf-8")
    assert "R-0002" not in block and "designing a schema" in block
    assert "Body of R-0002" in on_demand
