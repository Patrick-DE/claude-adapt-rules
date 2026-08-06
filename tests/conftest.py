"""Fixtures that build transcripts in the same shape Claude Code writes them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def rec(**kw) -> dict:
    return kw


def user_text(text: str, **kw) -> dict:
    return rec(type="user", message={"role": "user", "content": text}, **kw)


def user_blocks(blocks: list[dict], **kw) -> dict:
    return rec(type="user", message={"role": "user", "content": blocks}, **kw)


def enqueue(text: str, ts: str = "2026-07-01T10:00:00.000Z", **kw) -> dict:
    return rec(type="queue-operation", operation="enqueue", content=text, timestamp=ts, **kw)


def assistant(text: str = "", tools: list[tuple[str, str]] | None = None, **kw) -> dict:
    content: list[dict] = []
    if text:
        content.append({"type": "text", "text": text})
    for name, file_path in tools or []:
        block = {"type": "tool_use", "name": name, "id": f"t-{name}", "input": {}}
        if file_path:
            block["input"] = {"file_path": file_path}
        content.append(block)
    return rec(type="assistant", message={"role": "assistant", "content": content}, **kw)


def tool_result(text: str, **kw) -> dict:
    return user_blocks([{"type": "tool_result", "tool_use_id": "t-1", "content": text}], **kw)


DENIAL = (
    "The user doesn't want to proceed with this tool use. The tool use was rejected "
    "(eg. if it was a file edit, the file was not modified)."
)


@pytest.fixture(autouse=True)
def isolate_state(tmp_path: Path, monkeypatch):
    """No test may touch the real ``~/.claude-adapt-rules``.

    Caught for real: `active_guards` gained a log-on-broken-guard path after its
    test was written, so a test that never mentioned the data directory silently
    appended to the user's live hook.log on every run. Redirecting per test kills
    the whole class of leak rather than the one instance.
    """
    for var in (
        "CLAUDE_ADAPT_RULES_HOME",
        "CLAUDE_ADAPT_RULES_DATA_DIR",
        "CLAUDE_ADAPT_RULES_RULES_DIR",
        "CLAUDE_ADAPT_RULES_LEDGER",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_ADAPT_RULES_HOME", str(tmp_path / "state"))


@pytest.fixture
def make_transcript(tmp_path: Path):
    """Write records to <root>/<project-slug>/<session>.jsonl and return the path."""

    def _make(
        records: list[dict],
        project: str = "C--Users-alice-sources-repos-demo",
        session: str = "11111111-2222-3333-4444-555555555555",
        raw_lines: list[str] | None = None,
    ) -> Path:
        root = tmp_path / "projects"
        (root / project).mkdir(parents=True, exist_ok=True)
        path = root / project / f"{session}.jsonl"
        lines = [json.dumps(r) for r in records]
        if raw_lines:
            lines.extend(raw_lines)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return _make


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    return tmp_path / "projects"
