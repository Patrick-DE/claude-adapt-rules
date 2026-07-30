"""Extraction outputs and the capture hook's failure behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from claude_adapt_rules import extract as extract_mod
from claude_adapt_rules.cli import main

from .conftest import assistant, enqueue


def test_extract_writes_corpus_bundles_and_report(make_transcript, tmp_path):
    make_transcript(
        [
            enqueue("start"),
            assistant(tools=[("Write", "src/a.py")]),
            enqueue("no, don't put everything in one file, split it"),
        ]
    )
    root = tmp_path / "projects"
    out = tmp_path / "data"
    result = extract_mod.run_extract(root=root, out=out)

    assert result.stats.sessions == 1
    assert result.corpus and result.corpus.exists()
    lines = result.corpus.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["text"].startswith("no, don't")
    assert result.bundles and "don't put everything in one file" in result.bundles[0].read_text(
        encoding="utf-8"
    )
    assert result.report and "Extraction report" in result.report.read_text(encoding="utf-8")


def test_bundle_cap_is_reported_not_silent(make_transcript, tmp_path):
    records = []
    for i in range(5):
        records += [enqueue(f"no, that is wrong, fix approach {i}")]
    make_transcript(records)
    result = extract_mod.run_extract(
        root=tmp_path / "projects", out=tmp_path / "data", max_events=2
    )
    assert result.truncated  # dropped count surfaced to the caller
    assert "events omitted" in result.bundles[0].read_text(encoding="utf-8")


def test_queue_is_idempotent(make_transcript, tmp_path):
    path = make_transcript([enqueue("never use inline styles, it is wrong")])
    out = tmp_path / "data"
    first = extract_mod.queue_transcript(path, out=out)
    second = extract_mod.queue_transcript(path, out=out)
    assert first == 1
    assert second == 0
    queue = (out / "queue" / "queue.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(queue) == 1


def test_pending_excludes_consumed_events(make_transcript, tmp_path):
    path = make_transcript(
        [
            enqueue("no, that is wrong, never do it that way", ts="2026-07-01T10:00:00Z"),
            enqueue("stop mocking the database, it is wrong", ts="2026-07-01T11:00:00Z"),
        ]
    )
    out = tmp_path / "data"
    extract_mod.queue_transcript(path, out=out)
    assert len(extract_mod.pending_events(out)) == 2

    first = extract_mod.pending_events(out)[:1]
    extract_mod.mark_consumed(first, out=out, note="candidates/x.json")

    remaining = extract_mod.pending_events(out)
    assert len(remaining) == 1
    assert remaining[0]["uuid"] != first[0]["uuid"]
    # The queue itself is untouched: consumption is a marker, not a deletion.
    assert len(extract_mod.load_queue(out)) == 2


def test_consume_is_idempotent(make_transcript, tmp_path):
    path = make_transcript([enqueue("don't do that, it is wrong")])
    out = tmp_path / "data"
    extract_mod.queue_transcript(path, out=out)
    records = extract_mod.pending_events(out)

    assert extract_mod.mark_consumed(records, out=out) == 1
    assert extract_mod.mark_consumed(records, out=out) == 0
    assert extract_mod.pending_events(out) == []
    state = extract_mod.load_queue_state(out)
    assert len(state["consumed"]) == 1
    assert len(state["runs"]) == 2  # both attempts recorded


def test_pending_bundle_lists_events_and_next_step(make_transcript, tmp_path, capsys):
    path = make_transcript([enqueue("no, never mock the backend, that is wrong")])
    out = tmp_path / "data"
    extract_mod.queue_transcript(path, out=out)
    bundle = tmp_path / "pending.md"

    assert main(["pending", "--out", str(out), "--bundle", str(bundle)]) == 0
    text = bundle.read_text(encoding="utf-8")
    assert "never mock the backend" in text
    assert "consume" in text
    assert "pending ............. 1" in capsys.readouterr().out

    assert main(["consume", "--out", str(out), "--note", "candidates/x.json"]) == 0
    assert "nothing pending" in _run_pending_again(out)


def _run_pending_again(out) -> str:
    """Second consume run must report nothing left."""
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["consume", "--out", str(out)])
    return buf.getvalue()


def test_hook_payload_with_a_bom_is_accepted(make_transcript, tmp_path, monkeypatch):
    """PowerShell's pipeline prepends a BOM; json.loads rejects it.

    Seen for real in data/hook.log on Windows: every capture through the .ps1 shim
    failed with "Unexpected UTF-8 BOM" while the hook still reported success.
    """
    import io
    import runpy
    import sys

    path = make_transcript([enqueue("no, that is wrong, never do it that way")])
    out = tmp_path / "data"
    monkeypatch.setenv("CLAUDE_ADAPT_RULES_DATA_DIR", str(out))
    payload = json.dumps({"transcript_path": str(path)})
    monkeypatch.setattr(sys, "stdin", io.StringIO("﻿" + payload))

    capture = Path(__file__).resolve().parents[1] / "bin" / "capture.py"
    try:
        runpy.run_path(str(capture), run_name="__main__")
    except SystemExit as exit_code:
        assert exit_code.code == 0

    assert (out / "queue" / "queue.jsonl").exists()
    assert not (out / "hook.log").exists()  # no failure was logged


def test_queue_command_never_fails_the_session(tmp_path, capsys):
    """A capture hook that can fail is a capture hook that breaks unrelated work."""
    out = tmp_path / "data"
    code = main(
        ["queue", "--transcript", str(tmp_path / "does-not-exist.jsonl"), "--out", str(out)]
    )
    assert code == 0
    log = (out / "hook.log").read_text(encoding="utf-8")
    assert "queue failed" in log
    assert not (out / "queue" / "queue.jsonl").exists()


def test_ingest_and_adopt_roundtrip_via_cli(tmp_path, capsys):
    ledger = tmp_path / "ledger.json"
    candidates = tmp_path / "cands.json"
    candidates.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule": "state assumptions instead of asking to confirm scope twice",
                        "why": "user said so repeatedly",
                        "category": "process",
                        "evidence": [
                            {"project": "alpha", "session": "s1", "ts": "2026-07-01", "quote": "a", "uuid": "1"},
                            {"project": "beta", "session": "s2", "ts": "2026-07-02", "quote": "b", "uuid": "2"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(["ingest", str(candidates), "--ledger", str(ledger)]) == 0
    out = capsys.readouterr().out
    assert "R-0001" in out and "global" in out

    target = tmp_path / "CLAUDE.md"
    target.write_text("# Global\n\nexisting content\n", encoding="utf-8")
    assert (
        main(
            [
                "adopt",
                "R-0001",
                "--ledger",
                str(ledger),
                "--apply-global",
                "--claudemd",
                str(target),
            ]
        )
        == 0
    )
    merged = target.read_text(encoding="utf-8")
    assert "existing content" in merged
    assert "R-0001" in merged
    assert (tmp_path / "CLAUDE.md.claude-adapt-rules.bak").exists()
