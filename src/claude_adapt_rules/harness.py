"""What the harness actually consists of, and which parts of it ever fire.

`doctor` reports on the pipeline. Nothing reported on the thing the pipeline
exists to improve: the skills, agents and hooks installed around it. An unused
skill is context cost with no return, and a skill nobody knows is unused keeps
being maintained.

Everything here is extracted from transcripts already on disk — no new capture,
and nothing is inferred from what is *installed*, only from what was *used*. A
skill that exists but never appears here has never fired, which is the finding.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .transcripts import iter_session_files, projects_root

# Tool calls that name another part of the harness rather than doing work directly.
SKILL_TOOL = "Skill"
AGENT_TOOL = "Agent"


@dataclass(slots=True)
class Usage:
    name: str
    kind: str  # "skill" | "agent" | "tool"
    count: int = 0
    last_used: str = ""
    projects: set[str] = field(default_factory=set)

    def record(self, ts: str, project: str) -> None:
        self.count += 1
        if ts > self.last_used:
            self.last_used = ts
        if project:
            self.projects.add(project)


def _records(path: Path) -> Iterator[dict]:
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
                yield rec


def _blocks(content: object) -> list[dict]:
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def collect(root: Path | None = None) -> list[Usage]:
    """Every skill, agent and tool observed in the transcript store."""
    seen: dict[tuple[str, str], Usage] = {}

    def entry(name: str, kind: str) -> Usage:
        key = (kind, name)
        if key not in seen:
            seen[key] = Usage(name=name, kind=kind)
        return seen[key]

    for path in iter_session_files(root or projects_root()):
        project = path.parent.name
        for rec in _records(path):
            if rec.get("type") != "assistant":
                continue
            ts = str(rec.get("timestamp") or "")
            message = rec.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in _blocks(content):
                if block.get("type") != "tool_use":
                    continue
                tool = str(block.get("name") or "")
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                if tool == SKILL_TOOL and (skill := str(args.get("skill") or "")):
                    entry(skill, "skill").record(ts, project)
                elif tool == AGENT_TOOL:
                    agent = str(args.get("subagent_type") or "general-purpose")
                    entry(agent, "agent").record(ts, project)
                elif tool:
                    entry(tool, "tool").record(ts, project)
    return sorted(seen.values(), key=lambda u: (u.kind, -u.count, u.name))


def installed_skills(skills_root: Path | None = None) -> set[str]:
    """Skill directory names under ``~/.claude/skills``, if that is where they live.

    Only a partial view: plugin skills live under the plugin cache and are named
    ``plugin:skill``. Reported as such rather than pretending to be exhaustive.
    """
    root = skills_root or (Path.home() / ".claude" / "skills")
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir()}


def render(usages: Iterable[Usage], never_fired: Iterable[str] = ()) -> str:
    usages = list(usages)
    lines = [
        "# Harness inventory",
        "",
        "Observed in the transcript store — what was *used*, not what is installed.",
        "",
    ]
    for kind, title in (("skill", "Skills"), ("agent", "Agents"), ("tool", "Tools")):
        group = [u for u in usages if u.kind == kind]
        lines += [f"## {title} ({len(group)})", ""]
        if not group:
            lines += ["_None observed._", ""]
            continue
        lines += ["| name | uses | projects | last used |", "| --- | --- | --- | --- |"]
        for u in group:
            lines.append(
                f"| {u.name} | {u.count} | {len(u.projects)} | {u.last_used[:10] or '?'} |"
            )
        lines.append("")

    never = sorted(never_fired)
    lines += ["## Installed but never observed", ""]
    if never:
        lines += [
            "Context cost with no return so far — or simply not needed yet:",
            "",
            *[f"- {name}" for name in never],
            "",
        ]
    else:
        lines += ["_None, or the installed set could not be read._", ""]
    return "\n".join(lines)
