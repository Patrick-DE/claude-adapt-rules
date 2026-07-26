"""Extraction outputs and the capture hook's failure behaviour."""

from __future__ import annotations

import json

from claude_learn import extract as extract_mod
from claude_learn.cli import main

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
    assert (tmp_path / "CLAUDE.md.claude-learn.bak").exists()
