"""Render the ledger into the two tiers that actually reach a future session.

Tier 1 - repo rules: written automatically. Blast radius is one project and the
files are git-tracked, so a bad rule is a diff away from gone.

Tier 2 - global rules: proposed only. `~/.claude/CLAUDE.md` is loaded into every
session of every project, so each line there is a permanent token cost and an
unreviewed line is a permanent wrong instruction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from .atomic import write_text_atomic
from .extract import rules_dir
from .ledger import Ledger, Rule

BEGIN_MARKER = "<!-- claude-adapt-rules:begin -->"
END_MARKER = "<!-- claude-adapt-rules:end -->"

# Marker pairs this tool wrote under earlier names. A CLAUDE.md written by one of
# those still carries its block, and the splice below only recognises the current
# pair -- so without this the new block lands *alongside* the old one and every
# rule adopted before the rename is loaded twice in every session of every
# project. Observed on the 2026-08-04 upgrade.
LEGACY_MARKERS: tuple[tuple[str, str], ...] = (
    ("<!-- claude-learn:begin -->", "<!-- claude-learn:end -->"),
)

# Soft cap on the always-on global block. Above this, rules belong in a memory
# file (recall on demand) or a skill rather than in every prompt.
GLOBAL_BLOCK_MAX_LINES = 120


def _rule_line(rule: Rule) -> str:
    return f"- **{rule.id}** {rule.rule.rstrip('.')}."


def _evidence_lines(rule: Rule, limit: int = 3) -> list[str]:
    lines = []
    for ev in rule.evidence[:limit]:
        quote = ev.quote.replace("\n", " ").strip()
        stamp = ev.ts[:10] or "?"
        where = ev.project or "?"
        lines.append(f'  - `{stamp}` {where} · "{quote}"')
    if len(rule.evidence) > limit:
        lines.append(f"  - … {len(rule.evidence) - limit} more occurrence(s)")
    return lines


def render_proposed_global(ledger: Ledger) -> str:
    rules = [r for r in ledger.by_scope("global") if r.status == "proposed"]
    rules.sort(key=lambda r: (-len(r.sessions), -len(r.projects), r.id))
    lines = [
        "# Proposed global rules",
        "",
        "Candidates that cleared the promotion gate (evidence in ≥2 projects or",
        "≥3 sessions). Nothing here is active yet.",
        "",
        "Accept:  `python -m claude_adapt_rules.cli adopt R-0001 R-0007 --apply-global`",
        "Reject:  `python -m claude_adapt_rules.cli retire R-0002`",
        "",
    ]
    if not rules:
        lines += ["_No pending global candidates._", ""]
        return "\n".join(lines)

    for rule in rules:
        enforce = " · **mechanically enforceable → prefer a hook**" if rule.enforceable else ""
        lines += [
            f"## {rule.id} · {rule.category}{enforce}",
            "",
            f"**Rule:** {rule.rule}",
            "",
            f"**Why:** {rule.why or '_not stated_'}",
            "",
            f"**Evidence** ({rule.confidence}):",
            *_evidence_lines(rule),
            "",
        ]
    return "\n".join(lines)


def render_repo_rules(ledger: Ledger, scope: str) -> str:
    project = scope.split(":", 1)[1] if ":" in scope else scope
    rules = [r for r in ledger.by_scope(scope) if r.status != "retired"]
    rules.sort(key=lambda r: (r.category, r.id))
    lines = [
        f"# Learned rules: {project}",
        "",
        "Distilled from this project's own sessions by `claude-adapt-rules`. Auto-written —",
        "edit the ledger (`rules/ledger.json`) or retire a rule rather than hand-editing.",
        "",
    ]
    if not rules:
        lines += ["_No rules yet._", ""]
        return "\n".join(lines)

    by_category: dict[str, list[Rule]] = {}
    for rule in rules:
        by_category.setdefault(rule.category, []).append(rule)
    for category, group in by_category.items():
        lines += [f"## {category}", ""]
        for rule in group:
            lines.append(_rule_line(rule))
            if rule.why:
                lines.append(f"  - why: {rule.why}")
            lines += _evidence_lines(rule, limit=2)
        lines.append("")
    return "\n".join(lines)


def render_global_block(ledger: Ledger) -> str:
    """The block that gets spliced into ``~/.claude/CLAUDE.md``."""
    rules = [r for r in ledger.by_scope("global") if r.status == "adopted"]
    rules.sort(key=lambda r: (r.category, r.id))
    lines = [BEGIN_MARKER, "", "# Learned rules (claude-adapt-rules)", ""]
    by_category: dict[str, list[Rule]] = {}
    for rule in rules:
        by_category.setdefault(rule.category, []).append(rule)
    for category, group in by_category.items():
        lines.append(f"**{category}**")
        lines += [_rule_line(r) for r in group]
        lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def _block_re(begin: str, end: str, *, eat_blanks: bool = False) -> re.Pattern[str]:
    body = re.escape(begin) + r".*?" + re.escape(end)
    if eat_blanks:
        body = r"\n*" + body + r"\n*"
    return re.compile(body, re.DOTALL)


def drop_legacy_blocks(existing: str) -> str:
    """Remove blocks this tool wrote under an earlier name.

    Surrounding blank lines go with the block so removal leaves one separator
    rather than a growing gap. Text outside the markers is never touched.
    """
    for begin, end in LEGACY_MARKERS:
        existing = _block_re(begin, end, eat_blanks=True).sub("\n\n", existing)
    return existing


def splice_block(existing: str, block: str) -> str:
    """Replace the marked block, or append it if absent. Idempotent."""
    existing = drop_legacy_blocks(existing)
    pattern = _block_re(BEGIN_MARKER, END_MARKER)
    if pattern.search(existing):
        return pattern.sub(block.rstrip("\n"), existing)
    sep = "" if existing.endswith("\n\n") or not existing else "\n"
    return f"{existing}{sep}\n{block}"


def block_line_count(block: str) -> int:
    return sum(1 for line in block.splitlines() if line.strip())


def write_tier_files(ledger: Ledger, out: Path | None = None) -> list[Path]:
    """Write repo rule files and the global proposal file.

    Defaults to the ledger's own directory so a ledger pointed elsewhere (tests,
    a second machine) never writes into this repo.
    """
    root = out or ledger.path.parent or rules_dir()
    written: list[Path] = []

    global_dir = root / "global"
    global_dir.mkdir(parents=True, exist_ok=True)
    proposed = global_dir / "PROPOSED.md"
    write_text_atomic(proposed, render_proposed_global(ledger))
    written.append(proposed)

    adopted = global_dir / "ADOPTED.md"
    write_text_atomic(adopted, render_global_block(ledger))
    written.append(adopted)

    for scope in ledger.scopes():
        if not scope.startswith("repo:"):
            continue
        project = scope.split(":", 1)[1] or "unknown"
        safe = re.sub(r"[^A-Za-z0-9._-]", "-", project)
        target_dir = root / "repos" / safe
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "rules.md"
        write_text_atomic(path, render_repo_rules(ledger, scope))
        written.append(path)
    return written


def claudemd_pointer(project: str, rules_path: str) -> str:
    """Short block for a project's own CLAUDE.md - a pointer, not a copy."""
    return (
        f"{BEGIN_MARKER}\n\n"
        f"## Learned rules ({project})\n\n"
        f"Rules distilled from past sessions in this repo: `{rules_path}`.\n"
        f"Read it before changing code here; it records corrections already given.\n\n"
        f"{END_MARKER}\n"
    )


def summarize(rules: Sequence[Rule]) -> str:
    if not rules:
        return "none"
    return ", ".join(r.id for r in rules)
