"""Promotion gate, dedup-as-violation, rot buckets, and the global block splice."""

from __future__ import annotations

from claude_learn.ledger import (
    Evidence,
    Ledger,
    decide_scope,
)
from claude_learn.render import (
    BEGIN_MARKER,
    END_MARKER,
    render_global_block,
    render_proposed_global,
    splice_block,
)


def ev(project: str, session: str, ts: str = "2026-07-01T00:00:00+00:00", quote: str = "q"):
    return {"project": project, "session": session, "ts": ts, "quote": quote, "uuid": f"{session}-1"}


def cand(rule: str, evidence: list[dict], **kw) -> dict:
    return {"rule": rule, "why": "because", "category": "process", "evidence": evidence, **kw}


def test_two_projects_promotes_to_global():
    assert (
        decide_scope([Evidence("s1", "t", "q", "alpha"), Evidence("s2", "t", "q", "beta")])
        == "global"
    )


def test_three_sessions_one_project_promotes_to_global():
    evidence = [Evidence(f"s{i}", "t", "q", "alpha") for i in range(3)]
    assert decide_scope(evidence) == "global"


def test_single_project_stays_repo_scoped():
    assert decide_scope([Evidence("s1", "t", "q", "alpha")]) == "repo:alpha"


def test_repo_rules_are_adopted_on_ingest_so_rot_tracks_them(tmp_path):
    """They are written and injected immediately; 'proposed' hid them from rot."""
    ledger = Ledger(tmp_path / "ledger.json")
    repo_rule = ledger.ingest([cand("use pnpm in this repo", [ev("alpha", "s1")])]).created[0]
    assert repo_rule.scope == "repo:alpha"
    assert repo_rule.status == "adopted"
    assert repo_rule.adopted

    global_rule = ledger.ingest(
        [cand("verify before claiming done", [ev("alpha", "s2"), ev("beta", "s3")])]
    ).created[0]
    assert global_rule.scope == "global"
    assert global_rule.status == "proposed"  # global still needs a human yes


def test_model_cannot_promote_past_the_gate(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    result = ledger.ingest(
        [cand("do the thing", [ev("alpha", "s1")], scope="global")]
    )
    assert result.created[0].scope == "repo:alpha"


def test_duplicate_of_adopted_rule_is_recorded_as_violation(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    created = ledger.ingest(
        [cand("never mock the backend in integration tests", [ev("alpha", "s1")])]
    ).created[0]
    ledger.adopt(created.id)

    again = ledger.ingest(
        [
            cand(
                "never mock backend during integration tests",
                [ev("alpha", "s9", ts="2027-01-01T00:00:00+00:00")],
            )
        ]
    )
    assert again.created == []
    assert [r.id for r in again.violations] == [created.id]
    assert ledger.rules[created.id].violation_count == 1


def test_merge_moves_evidence_and_retires_the_duplicate(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    keeper = ledger.ingest(
        [cand("Fix the root cause instead of stacking workarounds", [ev("alpha", "s1")])]
    ).created[0]
    dupe = ledger.ingest(
        [cand("Keep it simple; avoid unnecessary complexity", [ev("beta", "s2")])]
    ).created[0]

    source, target = ledger.merge(dupe.id, keeper.id)
    assert source.status == "retired"
    assert source.evidence == []
    assert {e.session for e in target.evidence} == {"s1", "s2"}
    # Merged evidence spans two projects, so the gate now promotes the survivor.
    assert target.scope == "global"


def test_merge_rejects_unknown_or_self(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    rule = ledger.ingest([cand("do a thing", [ev("alpha", "s1")])]).created[0]
    assert ledger.merge(rule.id, rule.id) is None
    assert ledger.merge(rule.id, "R-9999") is None


def test_near_duplicates_surface_below_the_merge_threshold(tmp_path):
    """The real pair that slipped through: these two score 0.50, just under 0.6."""
    global_text = (
        "Fix the root cause and keep the solution as simple as the problem allows: no "
        "workarounds stacked on workarounds, no clever code that is hard to audit."
    )
    repo_text = (
        "Fix the root cause and keep the solution as simple as the problem allows; "
        "avoid unnecessary complexity."
    )
    ledger = Ledger(tmp_path / "ledger.json")
    first = ledger.ingest([cand(global_text, [ev("alpha", "s1")])]).created[0]
    created = ledger.ingest([cand(repo_text, [ev("beta", "s2")])]).created
    assert created, "0.50 is below the merge threshold, so a second rule is created"

    matches = ledger.near_duplicates(created[0])
    assert [other.id for _, other in matches] == [first.id]
    assert 0.4 <= matches[0][0] < 0.6


def test_candidate_without_evidence_rejected(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    result = ledger.ingest([{"rule": "no evidence here", "category": "style", "evidence": []}])
    assert result.created == []
    assert result.rejected and "no evidence" in result.rejected[0][1]


def test_ledger_roundtrip(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    ledger.ingest([cand("keep files under 500 lines", [ev("alpha", "s1")])])
    ledger.save()

    reloaded = Ledger(path)
    assert [r.rule for r in reloaded.rules.values()] == ["keep files under 500 lines"]
    assert reloaded.next_id == ledger.next_id


def test_rot_report_buckets(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    stale = ledger.ingest([cand("rule a", [ev("alpha", "s1")])]).created[0]
    noisy = ledger.ingest([cand("rule b totally different words", [ev("beta", "s2")])]).created[0]
    ledger.adopt(stale.id)
    ledger.adopt(noisy.id)
    ledger.rules[stale.id].adopted = "2020-01-01T00:00:00+00:00"
    ledger.rules[noisy.id].last_violated = "2999-01-01T00:00:00+00:00"
    ledger.rules[noisy.id].violation_count = 3

    buckets = ledger.rot_report(quiet_days=30)
    assert [r.id for r in buckets["escalate"]] == [noisy.id]
    assert [r.id for r in buckets["quiet"]] == [stale.id]


def test_splice_is_idempotent():
    doc = "# My rules\n\nkeep this\n"
    block = f"{BEGIN_MARKER}\nrules v1\n{END_MARKER}\n"
    once = splice_block(doc, block)
    twice = splice_block(once, f"{BEGIN_MARKER}\nrules v2\n{END_MARKER}\n")
    assert once.count(BEGIN_MARKER) == 1
    assert twice.count(BEGIN_MARKER) == 1
    assert "rules v1" not in twice
    assert "keep this" in twice


def test_global_block_only_contains_adopted_global_rules(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    glob_rule = ledger.ingest(
        [cand("verify before claiming done", [ev("alpha", "s1"), ev("beta", "s2")])]
    ).created[0]
    repo_rule = ledger.ingest([cand("use pnpm in this repo", [ev("alpha", "s3")])]).created[0]
    ledger.adopt(glob_rule.id)
    ledger.adopt(repo_rule.id)

    block = render_global_block(ledger)
    assert glob_rule.id in block
    assert repo_rule.id not in block
    # Adopted rules leave the proposal list. (Assert on the listing, not the
    # whole document: the usage header shows example ids.)
    assert "_No pending global candidates._" in render_proposed_global(ledger)
    assert f"## {glob_rule.id}" not in render_proposed_global(ledger)
