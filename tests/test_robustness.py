"""Regressions for the bug hunt of 2026-08-06.

Each of these was reproduced against the real install before it was fixed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from claude_adapt_rules import cli
from claude_adapt_rules.atomic import write_text_atomic
from claude_adapt_rules.guards import (
    GUARD_FIELDS,
    MAX_HAYSTACK,
    GuardError,
    active_guards,
    build_guard,
    check,
)
from claude_adapt_rules.ledger import Evidence, Ledger, LedgerError, Rule

FULL_LEDGER = {
    "schema": 1,
    "next_id": 44,
    "rules": [
        {
            "id": f"R-{i:04d}",
            "rule": f"rule {i}",
            "why": "",
            "category": "process",
            "scope": "global",
            "evidence": [],
        }
        for i in range(1, 44)
    ],
}


def _guarded(pattern: str, tool: str = "Bash") -> Rule:
    return Rule(
        id="R-0024",
        rule="Never commit with hooks disabled.",
        why="",
        category="process",
        scope="global",
        evidence=[Evidence(session="s", ts="2026-08-01", quote="q")],
        status="adopted",
        guard={"tool": tool, "pattern": pattern, "message": "m"},
    )


# --------------------------------------------------------------------------- #
# 1 + 6: a truncated state file must not read as "empty"
# --------------------------------------------------------------------------- #


def test_a_truncated_ledger_is_a_fault_not_an_empty_install(tmp_path):
    """Silently loading 0 rules reset next_id to 1 and the next save made it stick."""
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(FULL_LEDGER)[:400], encoding="utf-8")
    with pytest.raises(LedgerError):
        Ledger(path)


def test_a_missing_ledger_is_still_a_fresh_install(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    assert ledger.rules == {} and ledger.next_id == 1


def test_cli_reports_an_unreadable_ledger_instead_of_crashing(tmp_path, capsys):
    path = tmp_path / "ledger.json"
    path.write_text("{ broken", encoding="utf-8")
    assert cli.main(["guards", "--ledger", str(path)]) == 3
    assert "error:" in capsys.readouterr().out


def test_saving_leaves_no_half_written_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(FULL_LEDGER), encoding="utf-8")
    Ledger(path).save()
    assert len(Ledger(path).rules) == 43
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_keeps_the_old_file_when_it_fails(tmp_path, monkeypatch):
    """A failure part-way through must leave the previous state readable."""
    path = tmp_path / "state.json"
    path.write_text("original", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("claude_adapt_rules.atomic.os.replace", boom)
    with pytest.raises(OSError):
        write_text_atomic(path, "replacement")
    assert path.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob("*.tmp"))


# --------------------------------------------------------------------------- #
# 2: a pattern that backtracks would stall every guarded call
# --------------------------------------------------------------------------- #


def test_nested_quantifier_patterns_are_refused(tmp_path):
    """Measured before the fix: `(a+)+$` took 26 s on 28 characters."""
    for pattern in ("(a+)+$", "(x*)*", "(ab+)*"):
        with pytest.raises(GuardError, match="backtrack"):
            build_guard(_guarded(pattern))


def test_a_guard_never_scans_an_unbounded_string(tmp_path):
    guard = build_guard(_guarded(r"needle"))
    haystack = "a" * (MAX_HAYSTACK * 2) + "needle"
    started = time.perf_counter()
    assert check("Bash", {"command": haystack}, [guard]) is None
    assert time.perf_counter() - started < 1.0


# --------------------------------------------------------------------------- #
# 4 + 5: silent non-enforcement
# --------------------------------------------------------------------------- #


def test_multiedit_is_not_mapped_to_a_key_it_does_not_have(tmp_path):
    """Its edits nest under `edits`, so a top-level new_string never fires."""
    assert "MultiEdit" not in GUARD_FIELDS
    guard = build_guard(_guarded("secret", tool="MultiEdit"))
    nested = {"file_path": "a.py", "edits": [{"new_string": "secret"}]}
    assert check("MultiEdit", nested, [guard]) is not None


def test_a_broken_guard_is_logged_not_silently_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ADAPT_RULES_DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ledger.json"
    rule = _guarded("(unclosed")
    path.write_text(
        json.dumps({"schema": 1, "next_id": 2, "rules": [rule.to_dict()]}),
        encoding="utf-8",
    )
    assert active_guards(Ledger(path)) == []
    log = (tmp_path / "data" / "hook.log").read_text(encoding="utf-8")
    assert "guard disabled" in log and "R-0024" in log


# --------------------------------------------------------------------------- #
# 3: the health command must survive the mess it exists to report
# --------------------------------------------------------------------------- #


def test_adopt_never_half_writes_claude_md(tmp_path, monkeypatch, capsys):
    """It is loaded into every session of every project; a truncated write is global."""
    ledger = tmp_path / "ledger.json"
    candidates = tmp_path / "cands.json"
    candidates.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule": "state assumptions instead of asking twice",
                        "why": "w",
                        "category": "process",
                        "applies": "universal",
                        "evidence": [
                            {"project": "a", "session": "s1", "ts": "2026-08-01", "quote": "q", "uuid": "1"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["ingest", str(candidates), "--ledger", str(ledger)]) == 0

    target = tmp_path / "CLAUDE.md"
    target.write_text("# Global\n\nexisting content\n", encoding="utf-8")

    # Fail only the CLAUDE.md replace. Patching every replace would raise inside
    # write_tier_files first, and the test would pass without ever exercising the
    # write it is about -- which is exactly what a mutation check caught.
    real_replace = os.replace

    def boom(src, dst, *args, **kwargs):
        if Path(dst).name == "CLAUDE.md":
            raise OSError("disk full")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("claude_adapt_rules.atomic.os.replace", boom)
    with pytest.raises(OSError):
        cli.main(
            ["adopt", "R-0001", "--ledger", str(ledger), "--apply-global",
             "--claudemd", str(target)]
        )
    assert target.read_text(encoding="utf-8") == "# Global\n\nexisting content\n"
    assert not list(tmp_path.glob("CLAUDE.md.tmp"))


def test_reset_log_can_run_twice(tmp_path, monkeypatch, capsys):
    """rename() onto an existing target raises on Windows; the second run crashed."""
    monkeypatch.setenv("CLAUDE_ADAPT_RULES_HOME", str(tmp_path))
    log = tmp_path / "data" / "hook.log"
    log.parent.mkdir(parents=True)
    for line in ("first failed", "second failed"):
        log.write_text(f"[2026-08-06T00:00:00+00:00] {line}\n", encoding="utf-8")
        cli.main(["doctor", "--reset-log"])
    reviewed = (tmp_path / "data" / "hook.log.reviewed").read_text(encoding="utf-8")
    # Both batches survive: discarding the earlier one would hide those failures.
    assert "first failed" in reviewed and "second failed" in reviewed
    assert not log.exists()


def test_doctor_survives_a_malformed_queue_timestamp(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_ADAPT_RULES_HOME", str(tmp_path))
    queue = tmp_path / "data" / "queue" / "queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps({"session": "s", "uuid": "u", "ts": "not-a-date", "score": 5}) + "\n",
        encoding="utf-8",
    )
    assert cli.main(["doctor"]) in (0, 1)
    assert "unparseable" in capsys.readouterr().out
