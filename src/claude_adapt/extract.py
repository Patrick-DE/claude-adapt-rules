"""Turn transcripts into a scored corpus plus per-project evidence bundles.

Deterministic: no model calls here. The LLM step (`/learn-rules`) reads the
bundles this produces. Keeping extraction model-free means the expensive step
sees a few hundred focused events instead of 660 MB of transcripts, and the
same input always yields the same corpus.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .signals import Event, Stats, is_acknowledgement, score_session, select
from .transcripts import Session, parse_all, parse_session

# Per-project bundle caps. Truncation is reported, never silent.
MAX_EVENTS_PER_PROJECT = 80
MAX_TEXT_CHARS = 1500
MAX_CONTEXT_CHARS = 600


def repo_root() -> Path:
    """The installation directory. NOT a place to keep state.

    When claude-learn runs as a plugin this is
    ``~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`` — a new version
    means a new directory, so anything stored here is orphaned on every update.
    """
    return Path(__file__).resolve().parents[2]


def home_dir() -> Path:
    """Where state lives: ledger, corpus, queue, archive. Survives updates."""
    if env := os.environ.get("CLAUDE_LEARN_HOME"):
        return Path(env)
    return Path.home() / ".claude-learn"


def data_dir() -> Path:
    if env := os.environ.get("CLAUDE_LEARN_DATA_DIR"):
        return Path(env)
    return home_dir() / "data"


def rules_dir() -> Path:
    if env := os.environ.get("CLAUDE_LEARN_RULES_DIR"):
        return Path(env)
    return home_dir() / "rules"


@dataclass(slots=True)
class ExtractResult:
    stats: Stats
    events: list[Event]
    bundles: list[Path]
    corpus: Path | None
    report: Path | None
    truncated: dict[str, int]


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n… [+{len(text) - limit} chars truncated]"


def collect(
    sessions: Iterable[Session], min_score: int = 3
) -> tuple[list[Event], Stats]:
    stats = Stats()
    all_events: list[Event] = []
    for session in sessions:
        stats.sessions += 1
        stats.projects.add(session.project)
        stats.raw_user_records += session.raw_user_records
        stats.queued_records += session.queued_records
        stats.duplicate_records += session.duplicate_records
        stats.dropped_synthetic += session.dropped_synthetic
        stats.bad_lines += session.bad_lines
        stats.prompts += len(session.prompts)
        stats.acknowledgements += sum(
            1 for p in session.prompts if is_acknowledgement(p.text)
        )
        events = score_session(session.prompts)
        stats.scored += len(events)
        for event in events:
            stats.bump(event.signals)
        all_events.extend(select(events, min_score=min_score))
    stats.selected = len(all_events)
    all_events.sort(key=lambda e: (-e.score, e.prompt.ts))
    return all_events, stats


def _bundle_markdown(
    project: str, project_name: str, events: Sequence[Event], dropped: int
) -> str:
    sessions = sorted({e.prompt.session for e in events})
    lines = [
        f"# Evidence bundle: {project_name}",
        "",
        f"- project slug: `{project}`",
        f"- sessions represented: {len(sessions)}",
        f"- events in this bundle: {len(events)}",
    ]
    if dropped:
        lines.append(
            f"- **{dropped} lower-scoring events omitted** (cap "
            f"{MAX_EVENTS_PER_PROJECT}/project); re-run with --max-events to include them"
        )
    lines += [
        "",
        "Each event is one human turn that carried correction signal, plus what the",
        "agent had just done. Quote verbatim from `User said` only.",
        "",
    ]
    for i, event in enumerate(events, start=1):
        p = event.prompt
        signals = ", ".join(event.signals) or "none"
        lines += [
            f"## E{i} · score {event.score} · {signals}",
            "",
            f"- session `{p.session}` · record `{p.uuid}` · {p.ts} · branch `{p.git_branch or '-'}`",
        ]
        if p.prev_tools:
            tools = ", ".join(dict.fromkeys(p.prev_tools))
            lines.append(f"- agent had just used: {tools}")
        if p.prev_files:
            lines.append(f"- touching: {', '.join(p.prev_files[:6])}")
        if event.repeat_of:
            lines.append(f"- repeats earlier prompt `{event.repeat_of}` in same session")
        lines += ["", "**User said:**", ""]
        lines += [
            "> " + line for line in _truncate(p.text, MAX_TEXT_CHARS).splitlines()
        ]
        if p.prev_assistant_text:
            lines += [
                "",
                "<details><summary>agent context</summary>",
                "",
                "```text",
                _truncate(p.prev_assistant_text, MAX_CONTEXT_CHARS),
                "```",
                "",
                "</details>",
            ]
        lines.append("")
    return "\n".join(lines) + "\n"


def _report_markdown(stats: Stats, events: Sequence[Event]) -> str:
    per_project: dict[str, int] = defaultdict(int)
    for e in events:
        per_project[e.prompt.project_name] += 1
    signal_rows = sorted(stats.by_signal.items(), key=lambda kv: -kv[1])
    lines = [
        "# Extraction report",
        "",
        f"Generated {datetime.now(tz=timezone.utc).isoformat(timespec='seconds')}",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| sessions parsed | {stats.sessions} |",
        f"| projects | {len(stats.projects)} |",
        f"| raw `type:user` records | {stats.raw_user_records} |",
        f"| `queue-operation` enqueues (desktop submits) | {stats.queued_records} |",
        f"| duplicate prompts seen on both channels | {stats.duplicate_records} |",
        f"| human prompts after noise strip | {stats.prompts} |",
        f"| of those, bare acknowledgements | {stats.acknowledgements} |",
        f"| synthetic/tool-result records dropped | {stats.dropped_synthetic} |",
        f"| malformed jsonl lines tolerated | {stats.bad_lines} |",
        f"| prompts scored | {stats.scored} |",
        f"| events selected as evidence | {stats.selected} |",
        "",
        "## Signal frequency",
        "",
        "| signal | prompts |",
        "| --- | --- |",
    ]
    lines += [f"| {name} | {count} |" for name, count in signal_rows]
    lines += ["", "## Selected events per project", "", "| project | events |", "| --- | --- |"]
    lines += [
        f"| {name} | {count} |"
        for name, count in sorted(per_project.items(), key=lambda kv: -kv[1])
    ]
    return "\n".join(lines) + "\n"


def write_outputs(
    events: Sequence[Event],
    stats: Stats,
    out: Path | None = None,
    max_events: int = MAX_EVENTS_PER_PROJECT,
) -> ExtractResult:
    out = out or data_dir()
    corpus_dir = out / "corpus"
    bundle_dir = corpus_dir / "by-project"
    report_dir = out / "reports"
    for d in (bundle_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)

    corpus = corpus_dir / "events.jsonl"
    with corpus.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        grouped[event.prompt.project].append(event)

    bundles: list[Path] = []
    truncated: dict[str, int] = {}
    for project, project_events in grouped.items():
        project_events.sort(key=lambda e: (-e.score, e.prompt.ts))
        dropped = max(0, len(project_events) - max_events)
        if dropped:
            truncated[project] = dropped
        kept = project_events[:max_events]
        name = kept[0].prompt.project_name or project
        path = bundle_dir / f"{project}.md"
        path.write_text(
            _bundle_markdown(project, name, kept, dropped), encoding="utf-8"
        )
        bundles.append(path)

    report = report_dir / "extract.md"
    report.write_text(_report_markdown(stats, events), encoding="utf-8")

    return ExtractResult(
        stats=stats,
        events=list(events),
        bundles=bundles,
        corpus=corpus,
        report=report,
        truncated=truncated,
    )


def run_extract(
    root: Path | None = None,
    since: datetime | None = None,
    out: Path | None = None,
    min_score: int = 3,
    max_events: int = MAX_EVENTS_PER_PROJECT,
) -> ExtractResult:
    events, stats = collect(parse_all(root, since), min_score=min_score)
    return write_outputs(events, stats, out=out, max_events=max_events)


# --------------------------------------------------------------------------- #
# Session-end capture
# --------------------------------------------------------------------------- #


def queue_transcript(transcript: Path, out: Path | None = None) -> int:
    """Append one session's selected events to the pending queue.

    Called by the SessionEnd hook. Idempotent: re-running for the same session
    never duplicates events, so a replayed hook is harmless.
    """
    out = out or data_dir()
    queue_dir = out / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue = queue_dir / "queue.jsonl"

    seen: set[str] = set()
    if queue.exists():
        with queue.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                seen.add(f"{rec.get('session')}:{rec.get('uuid')}")

    session = parse_session(transcript)
    events = select(score_session(session.prompts))
    written = 0
    with queue.open("a", encoding="utf-8") as fh:
        for event in events:
            if event.prompt.key in seen:
                continue
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            written += 1
    return written


# --------------------------------------------------------------------------- #
# Queue consumption
#
# The queue is append-only, so without a consumed marker every distillation run
# re-reads every event ever captured. The ledger would absorb the repeats (they
# merge into existing rules), but the model pays to re-read old evidence and
# cannot tell what arrived since last time.
# --------------------------------------------------------------------------- #


def queue_path(out: Path | None = None) -> Path:
    return (out or data_dir()) / "queue" / "queue.jsonl"


def queue_state_path(out: Path | None = None) -> Path:
    return (out or data_dir()) / "queue" / "queue.state.json"


def load_queue(out: Path | None = None) -> list[dict]:
    path = queue_path(out)
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict):
                records.append(rec)
    return records


def _record_key(rec: dict) -> str:
    return f"{rec.get('session')}:{rec.get('uuid')}"


def load_queue_state(out: Path | None = None) -> dict:
    path = queue_state_path(out)
    if not path.exists():
        return {"consumed": [], "runs": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return {"consumed": [], "runs": []}
    state.setdefault("consumed", [])
    state.setdefault("runs", [])
    return state


def pending_events(out: Path | None = None) -> list[dict]:
    """Queue entries not yet marked consumed, newest scoring first."""
    consumed = set(load_queue_state(out).get("consumed", []))
    pending = [r for r in load_queue(out) if _record_key(r) not in consumed]
    pending.sort(key=lambda r: (-int(r.get("score") or 0), str(r.get("ts") or "")))
    return pending


def mark_consumed(
    records: Sequence[dict], out: Path | None = None, note: str = ""
) -> int:
    """Record these queue entries as distilled. Idempotent."""
    state = load_queue_state(out)
    consumed: list[str] = list(state.get("consumed", []))
    known = set(consumed)
    added = 0
    for rec in records:
        key = _record_key(rec)
        if key in known:
            continue
        consumed.append(key)
        known.add(key)
        added += 1
    state["consumed"] = consumed
    state["runs"] = [
        *state.get("runs", []),
        {
            "at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "consumed": added,
            "note": note,
        },
    ]
    path = queue_state_path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return added


def render_pending_bundle(records: Sequence[dict]) -> str:
    """Evidence bundle for the queue, same reading order as a project bundle."""
    lines = [
        "# Pending evidence (session-end queue)",
        "",
        f"- events awaiting distillation: {len(records)}",
        "",
        "Quote verbatim from `User said`. After filing candidates, run",
        "`python -m claude_learn.cli consume` so these are not re-read next time.",
        "",
    ]
    for i, rec in enumerate(records, start=1):
        signals = ", ".join(
            list(rec.get("lexical") or []) + list(rec.get("structural") or [])
        )
        lines += [
            f"## Q{i} · score {rec.get('score')} · {signals or 'none'}",
            "",
            f"- project `{rec.get('project_name') or rec.get('project')}` · "
            f"session `{rec.get('session')}` · {rec.get('ts')}",
        ]
        if rec.get("prev_tools"):
            tools = ", ".join(dict.fromkeys(rec["prev_tools"]))
            lines.append(f"- agent had just used: {tools}")
        lines += ["", "**User said:**", ""]
        text = _truncate(str(rec.get("text") or ""), MAX_TEXT_CHARS)
        lines += ["> " + line for line in text.splitlines()]
        lines.append("")
    return "\n".join(lines) + "\n"
