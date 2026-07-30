"""Evidence integrity: a rule may only cite words the user actually wrote."""

from __future__ import annotations

from claude_adapt_rules.ledger import Ledger
from claude_adapt_rules.verify import quote_fragments, verify_ledger

from .conftest import enqueue

QUOTE = "why do you always stub the queue? why not run it against the real worker"


def cand(quote: str, session: str = "aaaaaaaa") -> dict:
    return {
        "rule": "Do not mock the system under test.",
        "why": "user asked for real tests",
        "category": "verification",
        "evidence": [
            {"project": "demo", "session": session, "ts": "2026-07-07", "uuid": "u1", "quote": quote}
        ],
    }


def build(make_transcript, tmp_path, quote: str, session: str = "aaaaaaaa"):
    make_transcript([enqueue(QUOTE)], session="aaaaaaaa-1111-2222-3333-444444444444")
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.ingest([cand(quote, session)])
    return verify_ledger(ledger, root=tmp_path / "projects")


def test_verbatim_quote_passes(make_transcript, tmp_path):
    result = build(make_transcript, tmp_path, "why do you always stub the queue?")
    assert result.ok
    assert result.exact == 1


def test_paraphrased_quote_fails(make_transcript, tmp_path):
    """The first real run produced exactly this: word order changed while trimming."""
    result = build(make_transcript, tmp_path, "why do you stub the queue always?")
    assert not result.ok
    assert result.problems[0].kind == "not_found"


def test_case_change_fails(make_transcript, tmp_path):
    result = build(make_transcript, tmp_path, "Why do you always stub the queue?")
    assert not result.ok


def test_quote_attributed_to_the_wrong_session_is_flagged(make_transcript, tmp_path):
    result = build(make_transcript, tmp_path, "why do you always stub the queue?", session="bbbbbbbb")
    assert not result.ok
    assert result.problems[0].kind == "wrong_session"


def test_elided_quote_checks_each_fragment(make_transcript, tmp_path):
    assert quote_fragments("a b … c d") == ["a b", "c d"]
    assert quote_fragments("one ... two") == ["one", "two"]

    good = build(make_transcript, tmp_path, "why do you always stub the queue? … against the real worker")
    assert good.ok

    bad = build(make_transcript, tmp_path, "why do you always stub the queue? … against the fake worker")
    assert not bad.ok


def test_escaped_quotes_in_transcripts_are_decoded(make_transcript, tmp_path):
    """Raw JSONL stores inner quotes escaped; comparing file bytes gives false failures."""
    make_transcript(
        [enqueue('Avoid writing "smart" helpers that hide control flow')],
        session="cccccccc-1111-2222-3333-444444444444",
    )
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.ingest([cand('Avoid writing "smart" helpers', session="cccccccc")])
    result = verify_ledger(ledger, root=tmp_path / "projects")
    assert result.ok
