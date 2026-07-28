"""Rules only matter if a session sees them."""

from __future__ import annotations

from claude_learn import inject
from claude_learn.ledger import Ledger


def cand(rule: str, project: str, category: str = "expectation", why: str = "because") -> dict:
    return {
        "rule": rule,
        "why": why,
        "category": category,
        "evidence": [
            {"project": project, "session": "s1", "ts": "2026-07-21", "uuid": "u1", "quote": "q"}
        ],
    }


def ledger_with(tmp_path, *candidates) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.ingest(list(candidates))
    return ledger


def test_project_rules_are_rendered_for_that_cwd(tmp_path):
    ledger = ledger_with(
        tmp_path,
        cand("Key the cache on the build version, never the pid.", "my-app"),
        cand("Use pnpm, never npm.", "other-app", category="tooling"),
    )
    result = inject.build(r"C:\Users\alice\src\my-app", ledger)

    assert result is not None
    assert result.project == "my-app"
    assert "Key the cache on the build version" in result.text
    assert "pnpm" not in result.text  # another project's rule must not leak in


def test_silent_when_the_project_has_no_rules(tmp_path):
    ledger = ledger_with(tmp_path, cand("Use pnpm, never npm.", "other-app"))
    assert inject.build(r"C:\Users\alice\src\my-app", ledger) is None
    assert inject.session_start_payload(r"C:\Users\alice\src\my-app", ledger) is None


def test_worktree_session_sees_the_repository_rules(tmp_path):
    ledger = ledger_with(tmp_path, cand("Throw and log; never swallow errors.", "my-app"))
    cwd = r"C:\Users\alice\src\my-app\.claude-worktrees\brave-newton-a1b2c3"
    result = inject.build(cwd, ledger)

    assert result is not None
    assert result.project == "my-app"


def test_payload_shape_matches_the_hook_contract(tmp_path):
    ledger = ledger_with(tmp_path, cand("Throw and log; never swallow errors.", "my-app"))
    payload = inject.session_start_payload(r"/home/alice/src/my-app", ledger)

    assert payload is not None
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Throw and log" in payload["hookSpecificOutput"]["additionalContext"]
    assert payload["suppressOutput"] is True


# Rule texts must be genuinely different: the ledger merges candidates whose wording
# overlaps past DUPLICATE_THRESHOLD, so near-identical fixtures collapse into one rule.
DISTINCT_RULES = [
    "Stream output unbuffered and honour Ctrl+C.",
    "Bill from provider-reported token usage.",
    "Ship a standalone binary, not a source checkout.",
    "Return structured JSON from every tool.",
    "Prefer the GPU path when a device is present.",
    "Keep migrations reversible.",
]


def test_reasons_are_dropped_before_rules_when_over_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(inject, "MAX_CHARS", 500)
    long_why = "a reason long enough to blow the budget on its own " * 3
    ledger = ledger_with(
        tmp_path, *[cand(text, "my-app", why=long_why) for text in DISTINCT_RULES]
    )
    result = inject.build(r"C:\Users\alice\src\my-app", ledger)

    assert result is not None
    assert len(result.rules) == len(DISTINCT_RULES)
    assert "why:" not in result.text  # reasons dropped
    for text in DISTINCT_RULES:
        assert text.rstrip(".") in result.text  # every rule survives


def test_rule_overflow_is_reported_not_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(inject, "MAX_RULES", 3)
    ledger = ledger_with(tmp_path, *[cand(text, "my-app") for text in DISTINCT_RULES[:5]])
    result = inject.build(r"C:\Users\alice\src\my-app", ledger)

    assert result is not None
    assert result.truncated == 2
    assert "2 further rule(s) omitted" in result.text


def test_retired_rules_are_not_injected(tmp_path):
    ledger = ledger_with(tmp_path, cand("Old habit nobody wants.", "my-app"))
    rule_id = next(iter(ledger.rules))
    ledger.retire(rule_id)
    assert inject.build(r"C:\Users\alice\src\my-app", ledger) is None
