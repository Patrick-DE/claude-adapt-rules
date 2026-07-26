"""Check that every rule's evidence is really in the transcripts.

A rule is only worth obeying if the quote behind it is real. Two failure modes
this catches, both hit on the first run of this pipeline:

* a quote paraphrased while being trimmed ("can we get" for "we can get")
* a quote that exists somewhere but not in the session it is attributed to

Comparison is against *decoded* message text. Raw JSONL escapes inner quotes, so
grepping the file bytes reports false failures.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .ledger import Ledger, Rule
from .transcripts import iter_session_files, projects_root

ELLIPSIS = "…"


def _normalise(text: str) -> str:
    return " ".join(text.split())


def decoded_session_text(path: Path) -> str:
    """All human-authored text in one transcript, decoded and whitespace-normalised."""
    parts: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get("type") == "queue-operation" and isinstance(rec.get("content"), str):
                parts.append(rec["content"])
            message = rec.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    parts.extend(
                        b["text"]
                        for b in content
                        if isinstance(b, dict) and isinstance(b.get("text"), str)
                    )
    return _normalise(" ".join(parts))


def quote_fragments(quote: str) -> list[str]:
    """Split a trimmed quote into the fragments an ellipsis joins.

    Each fragment must appear verbatim in the source; the elided middle need not.
    """
    text = quote.replace("...", ELLIPSIS)
    return [f for f in (_normalise(part) for part in text.split(ELLIPSIS)) if f]


@dataclass(slots=True)
class Problem:
    rule_id: str
    session: str
    kind: str  # "not_found" | "wrong_session"
    quote: str


@dataclass(slots=True)
class VerifyResult:
    checked: int = 0
    exact: int = 0
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def load_sessions(root: Path | None = None, exclude: Iterable[str] = ()) -> dict[str, str]:
    """Map session-id prefix -> decoded text. Prefix keys match short ids in evidence."""
    excluded = {e[:8] for e in exclude}
    sessions: dict[str, str] = {}
    for path in iter_session_files(root or projects_root()):
        sid = path.stem[:8]
        if sid in excluded:
            continue
        sessions[sid] = decoded_session_text(path)
    return sessions


def verify_rules(rules: Iterable[Rule], sessions: dict[str, str]) -> VerifyResult:
    everything = " ".join(sessions.values())
    result = VerifyResult()
    for rule in rules:
        for ev in rule.evidence:
            result.checked += 1
            fragments = quote_fragments(ev.quote)
            cited = sessions.get(ev.session[:8], "")
            if fragments and all(f in cited for f in fragments):
                result.exact += 1
            elif fragments and all(f in everything for f in fragments):
                result.problems.append(Problem(rule.id, ev.session, "wrong_session", ev.quote))
            else:
                result.problems.append(Problem(rule.id, ev.session, "not_found", ev.quote))
    return result


def verify_ledger(
    ledger: Ledger, root: Path | None = None, exclude: Iterable[str] = ()
) -> VerifyResult:
    return verify_rules(ledger.rules.values(), load_sessions(root, exclude))
