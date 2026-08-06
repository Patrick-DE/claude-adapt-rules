"""The gate that replaces the human reader once distillation runs unattended.

`verify` checks the ledger — by then a bad quote is already a rule. This checks
the candidates file, which is the last point at which discarding is free.
"""

from __future__ import annotations

import json

from claude_adapt_rules import cli
from claude_adapt_rules.candidates import check, load_candidates

from .conftest import enqueue

QUOTE = "never key the cache on the process id, only on the build version"
SESSION = "aaaaaaaa-1111-2222-3333-444444444444"


def _cand(quote: str = QUOTE, session: str = "aaaaaaaa", **kw) -> dict:
    base = {
        "rule": "Key the cache on the build version, never the process id.",
        "why": "pid-keyed entries broke on every restart",
        "category": "expectation",
        "evidence": [
            {"project": "demo", "session": session, "ts": "2026-08-01", "uuid": "u1", "quote": quote}
        ],
    }
    return {**base, **kw}


def test_a_verbatim_candidate_is_accepted(make_transcript, tmp_path):
    make_transcript([enqueue(QUOTE)], session=SESSION)
    result = check([_cand()], root=tmp_path / "projects")
    assert result.ok and len(result.accepted) == 1


def test_a_paraphrased_quote_is_rejected(make_transcript, tmp_path):
    """The failure mode an unattended run cannot be trusted not to produce."""
    make_transcript([enqueue(QUOTE)], session=SESSION)
    result = check([_cand(quote="never key the cache on the pid, only the build version")],
                   root=tmp_path / "projects")
    assert not result.ok
    assert "evidence" in result.rejected[0][1]


def test_a_quote_from_another_session_is_rejected(make_transcript, tmp_path):
    make_transcript([enqueue(QUOTE)], session=SESSION)
    result = check([_cand(session="bbbbbbbb")], root=tmp_path / "projects")
    assert not result.ok


def test_evidence_whose_transcript_is_gone_is_rejected(tmp_path):
    """Unlike `verify`, which tolerates expiry: there is no rule to protect yet,
    and admitting an uncheckable quote is how unverifiable rules are born."""
    (tmp_path / "projects").mkdir()
    result = check([_cand()], root=tmp_path / "projects")
    assert not result.ok


def test_structural_faults_are_caught_before_any_transcript_is_read(tmp_path):
    bad = [
        {"category": "process", "evidence": [{"session": "s", "quote": "q"}]},
        _cand(category="nonsense"),
        {"rule": "x", "category": "process", "evidence": []},
        {"rule": "x", "category": "process", "evidence": [{"session": "s"}]},
    ]
    result = check(bad, root=tmp_path / "projects")
    reasons = [why for _, why in result.rejected]
    assert result.total == 4 and not result.accepted
    assert "missing 'rule'" in reasons
    assert any("bad category" in r for r in reasons)
    assert "no evidence" in reasons
    assert "evidence entry has no quote" in reasons


def test_good_and_bad_are_separated_not_all_or_nothing(make_transcript, tmp_path):
    make_transcript([enqueue(QUOTE)], session=SESSION)
    result = check([_cand(), _cand(quote="words nobody said")], root=tmp_path / "projects")
    assert len(result.accepted) == 1 and len(result.rejected) == 1


def test_load_accepts_both_file_shapes(tmp_path):
    listed = tmp_path / "a.json"
    listed.write_text(json.dumps([_cand()]), encoding="utf-8")
    wrapped = tmp_path / "b.json"
    wrapped.write_text(json.dumps({"rules": [_cand()]}), encoding="utf-8")
    assert len(load_candidates(listed)) == 1
    assert len(load_candidates(wrapped)) == 1


def test_cli_exits_nonzero_so_a_scheduled_job_can_branch(make_transcript, tmp_path, capsys):
    make_transcript([enqueue(QUOTE)], session=SESSION)
    path = tmp_path / "cands.json"
    path.write_text(json.dumps({"rules": [_cand(), _cand(quote="invented")]}), encoding="utf-8")

    kept = tmp_path / "accepted.json"
    code = cli.main(
        ["check-candidates", str(path), "--root", str(tmp_path / "projects"),
         "--out", str(tmp_path / "data"), "--write-accepted", str(kept)]
    )
    assert code == 1  # something was rejected
    assert "1/2 candidate(s) usable" in capsys.readouterr().out
    assert len(json.loads(kept.read_text(encoding="utf-8"))["rules"]) == 1


def test_cli_reports_an_unreadable_file(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    assert cli.main(["check-candidates", str(path)]) == 2
    assert "unreadable" in capsys.readouterr().out
