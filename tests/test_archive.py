"""Transcripts expire; rules must not become unverifiable when they do."""

from __future__ import annotations

from claude_adapt_rules import archive as archive_mod
from claude_adapt_rules.ledger import Ledger
from claude_adapt_rules.verify import verify_ledger

from .conftest import enqueue

SESSION = "aaaaaaaa-1111-2222-3333-444444444444"
QUOTE = "never key the cache on the process id, only on the build version"


def a_rule(session: str = "aaaaaaaa") -> dict:
    return {
        "rule": "Key the cache on the build version, never on the process id.",
        "why": "pid-keyed entries broke on every restart",
        "category": "expectation",
        "evidence": [
            {"project": "demo", "session": session, "ts": "2026-07-21", "uuid": "u1", "quote": QUOTE}
        ],
    }


def test_archive_copies_only_cited_sessions(make_transcript, tmp_path):
    make_transcript([enqueue(QUOTE)], session=SESSION)
    make_transcript([enqueue("something unrelated entirely")], session="bbbbbbbb-1-2-3-4")
    out = tmp_path / "data"
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.ingest([a_rule()])

    result = archive_mod.archive(
        sessions=archive_mod.cited_sessions(ledger, corpus=tmp_path / "none.jsonl"),
        root=tmp_path / "projects",
        out=out,
    )
    assert result.copied == 1
    archived = [p.name for p in archive_mod.archived_files(out)]
    assert archived == [f"{SESSION}.jsonl"]


def test_archive_is_idempotent(make_transcript, tmp_path):
    make_transcript([enqueue(QUOTE)], session=SESSION)
    out = tmp_path / "data"
    root = tmp_path / "projects"
    first = archive_mod.archive(sessions={"aaaaaaaa"}, root=root, out=out)
    second = archive_mod.archive(sessions={"aaaaaaaa"}, root=root, out=out)
    assert (first.copied, first.skipped) == (1, 0)
    assert (second.copied, second.skipped) == (0, 1)


def test_evidence_still_verifies_after_the_transcript_is_deleted(make_transcript, tmp_path):
    """The real 2026-07-26 failure: cleanup removed sessions three rules cited."""
    path = make_transcript([enqueue(QUOTE)], session=SESSION)
    out = tmp_path / "data"
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.ingest([a_rule()])

    archive_mod.archive(sessions={"aaaaaaaa"}, root=tmp_path / "projects", out=out)
    path.unlink()  # transcript cleanup

    without = verify_ledger(ledger, root=tmp_path / "projects")
    assert without.ok  # expired evidence is decay, not a failed check
    assert without.expired and without.exact == 0

    with_archive = verify_ledger(
        ledger,
        root=tmp_path / "projects",
        archive=list(archive_mod.archived_files(out)),
    )
    assert with_archive.ok
    assert with_archive.exact == 1


def test_deleted_transcript_is_reported_as_expired_not_fabricated(make_transcript, tmp_path):
    make_transcript([enqueue("unrelated")], session="cccccccc-1-2-3-4")
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.ingest([a_rule(session="dddddddd")])

    result = verify_ledger(ledger, root=tmp_path / "projects")
    assert [p.kind for p in result.problems] == ["session_gone"]
    assert result.failures == []
    assert result.ok  # a vanished transcript must not read as a bad quote


def test_missing_and_unarchived_sessions_are_named(make_transcript, tmp_path):
    make_transcript([enqueue("kept")], session=SESSION)
    result = archive_mod.archive(
        sessions={"aaaaaaaa", "eeeeeeee"}, root=tmp_path / "projects", out=tmp_path / "data"
    )
    assert result.missing == ["eeeeeeee"]
