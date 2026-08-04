"""Renaming the tool must not lose the state written under its old name.

The rename shipped without this and orphaned a real install: 31 rules, the
adopted-global block, 88 archived transcripts and the consumed-event markers all
stayed under the previous root while the new one started empty.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_adapt_rules import render as render_mod
from claude_adapt_rules.migrate import migrate_legacy_home, needs_migration

LEDGER = {"schema": 1, "next_id": 32, "rules": [{"id": "R-0031", "rule": "x"}]}


def _event(session: str, uuid: str, ts: str) -> str:
    return json.dumps({"session": session, "uuid": uuid, "ts": ts, "text": "t"})


def _legacy_root(home: Path) -> Path:
    old = home / ".claude-learn"
    (old / "rules").mkdir(parents=True)
    (old / "rules" / "ledger.json").write_text(json.dumps(LEDGER), encoding="utf-8")
    (old / "rules" / "repos" / "app").mkdir(parents=True)
    (old / "rules" / "repos" / "app" / "rules.md").write_text("# app", encoding="utf-8")
    (old / "data" / "archive" / "app").mkdir(parents=True)
    (old / "data" / "archive" / "app" / "s1.jsonl").write_text("{}", encoding="utf-8")
    (old / "data" / "queue").mkdir(parents=True)
    (old / "data" / "queue" / "queue.jsonl").write_text(
        _event("s1", "a", "2026-07-01") + "\n", encoding="utf-8"
    )
    (old / "data" / "queue" / "queue.state.json").write_text(
        json.dumps({"consumed": ["s1:a"], "runs": []}), encoding="utf-8"
    )
    return old


def _install_home(monkeypatch, tmp_path) -> Path:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path / ".claude-adapt-rules"


def test_legacy_state_is_adopted(monkeypatch, tmp_path):
    home = _install_home(monkeypatch, tmp_path)
    old = _legacy_root(tmp_path)

    assert needs_migration(home) is True
    assert migrate_legacy_home(home)

    assert json.loads((home / "rules" / "ledger.json").read_text())["next_id"] == 32
    assert (home / "rules" / "repos" / "app" / "rules.md").exists()
    assert (home / "data" / "archive" / "app" / "s1.jsonl").exists()
    assert json.loads((home / "data" / "queue" / "queue.state.json").read_text())[
        "consumed"
    ] == ["s1:a"]
    # Copy, not move: the old root survives as a rollback and is marked as read.
    assert (old / "rules" / "ledger.json").exists()
    assert list(old.glob("MIGRATED-*.txt"))


def test_queues_from_both_roots_are_merged(monkeypatch, tmp_path):
    """Neither side is authoritative: one holds pre-rename events, one post."""
    home = _install_home(monkeypatch, tmp_path)
    _legacy_root(tmp_path)
    queue = home / "data" / "queue" / "queue.jsonl"
    queue.parent.mkdir(parents=True)
    # Captured after the rename; the legacy root holds s1:a from before it.
    queue.write_text(_event("s2", "b", "2026-08-01") + "\n", encoding="utf-8")

    migrate_legacy_home(home)

    records = [json.loads(line) for line in queue.read_text().splitlines() if line]
    assert [(r["session"], r["uuid"]) for r in records] == [("s1", "a"), ("s2", "b")]


def test_never_overwrites_newer_state(monkeypatch, tmp_path):
    home = _install_home(monkeypatch, tmp_path)
    _legacy_root(tmp_path)
    archived = home / "data" / "archive" / "app" / "s1.jsonl"
    archived.parent.mkdir(parents=True)
    archived.write_text('{"fresher": true}', encoding="utf-8")

    migrate_legacy_home(home)

    assert archived.read_text() == '{"fresher": true}'


def test_is_idempotent_and_skips_an_established_install(monkeypatch, tmp_path):
    home = _install_home(monkeypatch, tmp_path)
    _legacy_root(tmp_path)

    assert migrate_legacy_home(home)
    assert needs_migration(home) is False
    assert migrate_legacy_home(home) == []


def test_no_legacy_root_is_not_an_error(monkeypatch, tmp_path):
    home = _install_home(monkeypatch, tmp_path)
    assert needs_migration(home) is False
    assert migrate_legacy_home(home) == []


# --------------------------------------------------------------------------- #
# The same rename, in CLAUDE.md
# --------------------------------------------------------------------------- #

LEGACY_BLOCK = (
    "<!-- claude-learn:begin -->\n\n"
    "# Learned rules (claude-learn)\n\n"
    "- **R-0001** Test against the real system.\n\n"
    "<!-- claude-learn:end -->"
)


def test_block_from_the_old_name_is_replaced_not_duplicated():
    """Otherwise every pre-rename rule is loaded twice in every session."""
    existing = f"# My rules\n\nBe careful.\n\n\n{LEGACY_BLOCK}\n"
    block = (
        f"{render_mod.BEGIN_MARKER}\n\n"
        "# Learned rules (claude-adapt-rules)\n\n"
        "- **R-0001** Test against the real system.\n\n"
        f"{render_mod.END_MARKER}\n"
    )
    result = render_mod.splice_block(existing, block)

    assert "claude-learn:begin" not in result
    assert result.count("R-0001") == 1
    assert result.count(render_mod.BEGIN_MARKER) == 1
    assert "Be careful." in result  # text outside the markers is untouched


def test_splice_stays_idempotent():
    block = f"{render_mod.BEGIN_MARKER}\n\n- **R-0001** x.\n\n{render_mod.END_MARKER}\n"
    once = render_mod.splice_block("# Mine\n", block)
    assert render_mod.splice_block(once, block) == once
