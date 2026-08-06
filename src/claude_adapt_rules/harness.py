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
import re
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
    # Real working directories, not slugs. Needed because an agent resolves from
    # the project's own `.claude/agents/` before the global one, so "is this
    # installed" has no answer until you know where it was used.
    cwds: set[str] = field(default_factory=set)

    def record(self, ts: str, project: str, cwd: str = "") -> None:
        self.count += 1
        if ts > self.last_used:
            self.last_used = ts
        if project:
            self.projects.add(project)
        if cwd:
            self.cwds.add(cwd)


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
        cwd = ""
        for rec in _records(path):
            if not cwd and isinstance(rec.get("cwd"), str):
                cwd = rec["cwd"]
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
                    entry(skill, "skill").record(ts, project, cwd)
                elif tool == AGENT_TOOL:
                    agent = str(args.get("subagent_type") or "general-purpose")
                    entry(agent, "agent").record(ts, project, cwd)
                elif tool:
                    entry(tool, "tool").record(ts, project, cwd)
    return sorted(seen.values(), key=lambda u: (u.kind, -u.count, u.name))


AGENT_SUFFIX = ".md"
# Files people leave behind when disabling something rather than deleting it.
DISABLED_SUFFIXES = (".bak", ".disabled", ".old", ".orig", ".save")


_FRONTMATTER_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)


def _agent_name(path: Path) -> str:
    """The name an agent is dispatched by.

    Frontmatter `name:` wins over the filename: that is what a project entry
    matches on when shadowing a global one, so a file whose stem and name differ
    is dispatchable only under the latter.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return path.stem
    match = _FRONTMATTER_NAME.search(head)
    return match.group(1) if match else path.stem


def installed_agents(agents_root: Path | None = None) -> set[str]:
    """Agent names loadable from one agents directory."""
    root = agents_root or (Path.home() / ".claude" / "agents")
    if not root.is_dir():
        return set()
    return {_agent_name(p) for p in root.glob(f"*{AGENT_SUFFIX}") if p.is_file()}


def agents_visible_from(cwd: str, global_root: Path | None = None) -> set[str]:
    """Every agent dispatchable from a working directory.

    A project's own `.claude/agents/` is searched as well as the global one, and a
    project entry shadows a global of the same name. Checking only the global set
    reports a project agent as missing — measured: two agents dispatched 62 times
    between them were flagged as broken handoffs when both were installed, just
    not globally.
    """
    names = installed_agents(global_root)
    if cwd:
        names |= installed_agents(Path(cwd) / ".claude" / "agents")
    return names


def shelved_files(agents_root: Path | None = None) -> set[str]:
    """Files parked next to the agents but not loadable as one.

    Disabling an agent by renaming it leaves something that looks installed to a
    human reading the directory and is invisible to the loader. Worth naming,
    because the roster it belongs to may still advertise it.
    """
    root = agents_root or (Path.home() / ".claude" / "agents")
    if not root.is_dir():
        return set()
    return {
        p.name
        for p in root.iterdir()
        if p.is_file() and p.suffix in DISABLED_SUFFIXES
    }


def roster_names(claudemd: Path | None = None) -> set[str]:
    """Agent names advertised in the global instructions.

    A roster entry with no file behind it is worse than no guidance: the agent is
    offered, dispatch fails, and the failure looks like a bug in the task rather
    than in the roster.
    """
    path = claudemd or (Path.home() / ".claude" / "CLAUDE.md")
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"^\s*-\s+\*\*([a-z][a-z0-9-]{2,})\*\*", text, re.MULTILINE))


@dataclass(slots=True)
class Hygiene:
    """Disagreements between what is used, advertised, and installed."""

    used_but_missing: set[str] = field(default_factory=set)
    advertised_but_missing: set[str] = field(default_factory=set)
    installed_but_unadvertised: set[str] = field(default_factory=set)
    shelved: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not (
            self.used_but_missing or self.advertised_but_missing or self.shelved
        )


# Dispatchable without a file on disk, so absence is not a fault.
BUILTIN_AGENTS = frozenset(
    {"general-purpose", "Explore", "Plan", "claude", "statusline-setup"}
)


def check_agents(
    usages: Iterable[Usage],
    agents_root: Path | None = None,
    claudemd: Path | None = None,
) -> Hygiene:
    """Disagreements between what was used, what is advertised, and what is installed.

    Resolution is per working directory, because "installed" is not a global fact:
    the same name can be a project agent in one repo and absent in another.
    """
    usages = list(usages)
    global_agents = installed_agents(agents_root)
    advertised = roster_names(claudemd)

    missing: set[str] = set()
    for usage in usages:
        if usage.kind != "agent" or usage.name in BUILTIN_AGENTS:
            continue
        if ":" in usage.name:
            continue  # plugin agent; lives in the plugin cache, not an agents dir
        # Resolvable anywhere it was actually used is enough. Flagging a name that
        # resolves in the project that used it would be a false alarm.
        if any(usage.name in agents_visible_from(cwd, agents_root) for cwd in usage.cwds):
            continue
        if not usage.cwds and usage.name in global_agents:
            continue
        missing.add(usage.name)

    return Hygiene(
        used_but_missing=missing,
        # The roster in the *global* file advertises globally, so it is checked
        # against the global set only.
        advertised_but_missing=advertised - global_agents,
        installed_but_unadvertised=global_agents - advertised,
        shelved=shelved_files(agents_root),
    )


def installed_skills(skills_root: Path | None = None) -> set[str]:
    """Skill directory names under ``~/.claude/skills``, if that is where they live.

    Only a partial view: plugin skills live under the plugin cache and are named
    ``plugin:skill``. Reported as such rather than pretending to be exhaustive.
    """
    root = skills_root or (Path.home() / ".claude" / "skills")
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir()}


def _hygiene_lines(hygiene: Hygiene) -> list[str]:
    lines = ["## Agent hygiene", ""]
    if hygiene.ok and not hygiene.installed_but_unadvertised:
        return [*lines, "_Used, advertised and installed all agree._", ""]

    sections = [
        (
            hygiene.used_but_missing,
            "**Used but no longer installed** — dispatch will fail, and the failure will "
            "look like a bug in the task rather than a missing file:",
        ),
        (
            hygiene.advertised_but_missing,
            "**Advertised in the roster but absent on disk** — a handoff target nobody has:",
        ),
        (
            hygiene.shelved,
            "**Parked next to the agents but not loadable** — renaming to disable leaves "
            "something that reads as installed and is invisible to the loader:",
        ),
        (
            hygiene.installed_but_unadvertised,
            "Installed but not in the roster (fine if deliberate):",
        ),
    ]
    for names, heading in sections:
        if not names:
            continue
        lines += [heading, "", *[f"- {n}" for n in sorted(names)], ""]
    return lines


def render(
    usages: Iterable[Usage],
    never_fired: Iterable[str] = (),
    hygiene: Hygiene | None = None,
) -> str:
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

    if hygiene is not None:
        lines += _hygiene_lines(hygiene)
    return "\n".join(lines)
