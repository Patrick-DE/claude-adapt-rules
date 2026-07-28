"""Generality is judged, not counted."""

from __future__ import annotations

from claude_learn.classify import PROJECT, UNIVERSAL, looks_project_specific, resolve_applies
from claude_learn.ledger import Evidence, Ledger, decide_scope


def one(project: str = "alpha", session: str = "s1") -> list[Evidence]:
    return [Evidence(session=session, ts="2026-07-28", quote="q", project=project, uuid="u1")]


def test_universal_rule_said_once_still_goes_global():
    """The case that motivated this: 'dont commit broken stuff', one session, one project."""
    scope = decide_scope(one(), applies=UNIVERSAL)
    assert scope == "global"


def test_project_rule_said_often_stays_local():
    evidence = [
        Evidence(session=f"s{i}", ts="2026-07-28", quote="q", project="alpha", uuid=f"u{i}")
        for i in range(5)
    ]
    assert decide_scope(evidence, applies=PROJECT) == "repo:alpha"


def test_unjudged_rules_fall_back_to_the_count_gate():
    assert decide_scope(one(), applies="") == "repo:alpha"
    two_projects = one() + one(project="beta", session="s2")
    assert decide_scope(two_projects, applies="") == "global"


def test_paths_and_filenames_veto_a_universal_claim():
    applies, veto = resolve_applies(
        "Never read releases/canvas-debug.log whole; tail it instead.", UNIVERSAL
    )
    assert applies == PROJECT
    assert veto and "path" in veto or "extension" in veto


def test_identifiers_veto_a_universal_claim():
    for text in (
        "Start the backend through start_debug.bat",
        "Call patchApplyGate before writing",
        "PINNED_PUBLISHER_THUMBPRINT must not be empty",
    ):
        applies, veto = resolve_applies(text, UNIVERSAL)
        assert applies == PROJECT, text
        assert veto


def test_project_name_vetoes_a_universal_claim():
    applies, veto = resolve_applies(
        "Always run the suite before pushing to unrealengine-debugger",
        UNIVERSAL,
        project_names=("unrealengine-debugger", "web-api"),
    )
    assert applies == PROJECT
    assert veto and "project name" in veto


def test_genuinely_universal_text_survives():
    for text in (
        "Never commit code that does not build or whose tests fail.",
        "Reproduce and measure a bug before changing anything.",
        "Before blaming your change for a failing test, confirm it on a clean tree.",
    ):
        applies, veto = resolve_applies(text, UNIVERSAL)
        assert applies == UNIVERSAL, text
        assert veto is None
        assert looks_project_specific(text) is None


def test_a_project_claim_is_never_widened():
    applies, veto = resolve_applies("Always write tests.", PROJECT)
    assert applies == PROJECT  # narrow is the safe default
    assert veto is None


def test_ingest_reports_the_veto(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    result = ledger.ingest(
        [
            {
                "rule": "Never read releases/canvas-debug.log whole.",
                "why": "it is huge",
                "category": "tooling",
                "applies": "universal",
                "evidence": [
                    {"project": "alpha", "session": "s1", "ts": "2026-07-28", "quote": "q", "uuid": "u1"}
                ],
            }
        ]
    )
    assert result.created[0].scope == "repo:alpha"
    assert result.created[0].applies == PROJECT
    assert result.vetoed and "canvas-debug.log" in result.vetoed[0][1]


def test_reclassify_keeps_an_already_global_adopted_rule_adopted(tmp_path, capsys):
    """Resetting those to 'proposed' left the ledger disagreeing with CLAUDE.md."""
    from claude_learn.cli import main

    ledger_path = tmp_path / "ledger.json"
    ledger = Ledger(ledger_path)
    already_global = ledger.ingest(
        [
            {
                "rule": "Verify before claiming a task is done.",
                "why": "asked repeatedly",
                "category": "verification",
                "applies": "universal",
                "evidence": [
                    {"project": "alpha", "session": "s1", "ts": "2026-07-28", "quote": "q", "uuid": "u1"}
                ],
            }
        ]
    ).created[0]
    ledger.adopt(already_global.id)
    promoted = ledger.ingest(
        [
            {
                "rule": "Stream long-running output unbuffered.",
                "why": "no progress visible",
                "category": "expectation",
                "applies": "project",
                "evidence": [
                    {"project": "alpha", "session": "s2", "ts": "2026-07-28", "quote": "q2", "uuid": "u2"}
                ],
            }
        ]
    ).created[0]
    assert promoted.status == "adopted"  # repo rules auto-adopt
    ledger.save()

    main(
        [
            "reclassify",
            f"{already_global.id}=universal",
            f"{promoted.id}=universal",
            "--ledger",
            str(ledger_path),
            "--apply",
        ]
    )

    reloaded = Ledger(ledger_path)
    assert reloaded.rules[already_global.id].status == "adopted"  # untouched
    assert reloaded.rules[promoted.id].scope == "global"
    assert reloaded.rules[promoted.id].status == "proposed"  # needs a yes


def test_universal_candidate_goes_global_and_waits_for_approval(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    rule = ledger.ingest(
        [
            {
                "rule": "Never commit code that does not build.",
                "why": "a broken commit was pushed",
                "category": "process",
                "applies": "universal",
                "evidence": [
                    {"project": "alpha", "session": "s1", "ts": "2026-07-28", "quote": "q", "uuid": "u1"}
                ],
            }
        ]
    ).created[0]
    assert rule.scope == "global"
    assert rule.status == "proposed"  # global never auto-adopts
