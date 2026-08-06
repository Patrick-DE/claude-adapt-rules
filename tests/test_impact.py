"""The measurement must refuse to conclude far more often than it concludes.

A number that looks like a verdict gets read as one. Measured on the real corpus
the correction rate *rose* while rules were being adopted, which says nothing —
the windows were tiny and the rules two days old.
"""

from __future__ import annotations

import json

from claude_adapt_rules.impact import (
    MIN_MEANINGFUL_DELTA,
    MIN_PROMPTS_PER_WINDOW,
    ProjectImpact,
    Window,
    for_rule,
    render,
)
from claude_adapt_rules.ledger import Evidence, Ledger, Rule

CUT = "2026-08-01T00:00:00+00:00"


def _rule(rid: str = "R-0001", adopted: str = CUT) -> Rule:
    return Rule(
        id=rid,
        rule="Never commit code that does not build.",
        why="w",
        category="process",
        scope="global",
        evidence=[Evidence(session="s", ts="2026-07-01", quote="q")],
        status="adopted",
        adopted=adopted,
    )


def _rows(project: str, before: tuple[int, int], after: tuple[int, int]):
    """(total, corrective) counts either side of the cut."""
    rows = []
    for total, corrective, ts in ((*before, "2026-07-15"), (*after, "2026-08-15")):
        for i in range(total):
            rows.append((f"{ts}T00:00:00+00:00", project, i < corrective))
    return rows


def test_a_big_drop_is_reported_as_a_drop():
    rows = _rows("app", (200, 40), (200, 10))  # 20% -> 5%
    impact = for_rule(_rule(), rows)[0]
    assert impact.verdict == "corrections fell"
    assert impact.delta < -MIN_MEANINGFUL_DELTA


def test_a_small_change_is_not_a_finding():
    rows = _rows("app", (200, 40), (200, 44))  # 20% -> 22%
    assert for_rule(_rule(), rows)[0].verdict == "no measurable change"


def test_a_thin_window_refuses_to_conclude_however_large_the_swing():
    """The real data's worst row: 100% -> 20% on n=2 and n=40."""
    rows = _rows("app", (2, 2), (40, 8))
    impact = for_rule(_rule(), rows)[0]
    assert impact.underpowered
    assert impact.verdict == "no conclusion (too few prompts)"
    assert abs(impact.delta) > 50  # the swing is huge and still says nothing


def test_no_data_after_adoption_is_never_a_success():
    rows = _rows("app", (200, 60), (0, 0))
    assert for_rule(_rule(), rows)[0].verdict == "no conclusion (too few prompts)"


def test_projects_are_reported_separately_not_pooled():
    """Pooling hides the dominant confound; stratifying exposes empty cells."""
    rows = _rows("easy", (200, 10), (200, 10)) + _rows("hard", (200, 80), (200, 80))
    impacts = for_rule(_rule(), rows)
    assert [i.project for i in impacts] == ["easy", "hard"]
    assert impacts[0].before.density != impacts[1].before.density


def test_an_unadopted_rule_has_no_impact_to_measure():
    assert for_rule(_rule(adopted=""), _rows("app", (200, 40), (200, 10))) == []


def test_thresholds_are_actually_applied():
    thin = ProjectImpact("p", Window(MIN_PROMPTS_PER_WINDOW - 1, 0), Window(999, 0))
    assert thin.underpowered
    fat = ProjectImpact("p", Window(999, 500), Window(999, 500 - int(MIN_MEANINGFUL_DELTA * 9)))
    assert not fat.underpowered


def test_render_says_plainly_when_nothing_is_conclusive(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps({"schema": 1, "next_id": 2, "rules": [_rule().to_dict()]}), encoding="utf-8"
    )
    text = render(Ledger(path), [])
    assert "Nothing here is conclusive yet" in text
    assert str(MIN_PROMPTS_PER_WINDOW) in text
