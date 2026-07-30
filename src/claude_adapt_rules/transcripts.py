"""Locate and parse Claude Code session transcripts. Stdlib only.

On-disk layout (verified 2026-07-26):

    ~/.claude/projects/<project-slug>/<session-uuid>.jsonl              main thread
    ~/.claude/projects/<project-slug>/<session-uuid>/subagents/**.jsonl subagent threads

Where the human text actually lives -- measured, not assumed. In this install
(Claude Code desktop) prompts are submitted through a queue and recorded as::

    {"type": "queue-operation", "operation": "enqueue", "content": "<what you typed>"}

1325 such records exist locally. The ``type: "user"`` records are overwhelmingly
tool results and machine continuations ("Continue from where you left off.",
compaction summaries, skill payloads): of 17209 of them, only 64 survive noise
filtering and *all* of those are machine-generated. A parser that mines
``type: "user"`` alone learns nothing about the user. Both sources are read here,
with queue records preferred and overlapping text de-duplicated.

Subagent prompts (``promptSource == "sdk"``, 1217 records) are excluded: the main
thread wrote them, so mining them would learn the agent's words back as the
user's.

This module is deliberately dependency-free: the session-end capture hook imports
it on every session exit, and a missing dependency there would surface as a hook
failure in an unrelated project.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Synthetic content
#
# Not every ``type: "user"`` record is something a human typed. Claude Code
# injects tool results, hook output, slash-command expansions and background
# task notifications through the same channel. Counts below are occurrences
# measured across the 69 local main-thread transcripts and are what these
# filters were written against.
# --------------------------------------------------------------------------- #

# Whole message is machine-generated when it opens with one of these tags.
SYNTHETIC_LEADING_TAGS: tuple[str, ...] = (
    "task-notification",  # 334 - background task/workflow completion
    "local-command-stdout",  # 38 - slash command output
    "local-command-stderr",
    "local-command-caveat",  # 38
    "command-name",  # 38 - slash command expansion
    "command-message",  # 2
    "command-args",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "ide_selection",
    "user-prompt-submit-hook",
    "system-reminder",
)

# Injected context that wraps *around* human text and must be stripped, not dropped.
_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_LEADING_TAG_RE = re.compile(r"^<([A-Za-z0-9_-]+)>")

# SessionStart / UserPromptSubmit hooks prepend their payload to the first user
# message of a session (caveman mode banner, Vercel context, superpowers block).
_HOOK_PAYLOAD_RE = re.compile(
    r"^.*?hook (?:success|feedback|additional context)[^\n]*\n",
    re.IGNORECASE | re.DOTALL,
)

# Machine-authored text that arrives on the human channel. Every one of these
# was observed in the local transcripts; without them the corpus is 100% noise.
_MACHINE_PROMPT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Continue from where you left off\.?\s*$", re.IGNORECASE),
    re.compile(r"^This session is being continued from a previous conversation"),
    re.compile(r"^Base directory for this skill:"),
    re.compile(r"^(?:Stop|SessionStart|PreToolUse|PostToolUse|SessionEnd)\s+hook"),
    re.compile(r"^Caveat: The messages below were generated"),
    re.compile(r"^\s*<(?:task-notification|local-command|command-)"),
    re.compile(r"^Your task is to create a detailed summary of the conversation"),
    re.compile(r"^Please continue the conversation from where"),
    # A slash command injects the whole SKILL.md body on the human channel. Its
    # H1 is the skill title; scored raw it outranks every real correction.
    re.compile(r"^#\s+.*\bskill\b", re.IGNORECASE),
    re.compile(r"^---\s*\nname:\s", re.MULTILINE),
)

# `/name` or `/plugin:name`, optionally followed by the real request.
_SLASH_COMMAND_RE = re.compile(r"^/[A-Za-z0-9][\w.:-]*\s*")

# When a slash command carries arguments, the injected body ends with the user's
# own words after this marker. That text is the only human part of the message.
_ARGUMENTS_RE = re.compile(r"^ARGUMENTS:\s*(.*)$", re.MULTILINE | re.DOTALL)

# Exact strings, taken from real transcripts.
_USER_DENIAL_RE = re.compile(
    r"The user doesn't want to proceed with this tool use|"
    r"The user (?:rejected|denied) (?:this|the) (?:tool use|edit|operation)|"
    r"user doesn't want to take this action",
    re.IGNORECASE,
)
# Distinct signal: the sandbox/auto-mode classifier blocked it, not the human.
_CLASSIFIER_DENIAL_RE = re.compile(
    r"Permission for this action was denied by the Claude Code auto mode classifier",
    re.IGNORECASE,
)
_INTERRUPT_RE = re.compile(r"\[Request interrupted by user")


@dataclass(frozen=True, slots=True)
class Prompt:
    """One human turn, plus what the agent did immediately before it.

    The context fields are the point: "no, not like that" is only distillable
    into a rule when you can see the action it rejected.
    """

    project: str  # project slug (directory name under projects/)
    project_name: str  # friendly name, from cwd
    session: str  # session uuid
    uuid: str  # record uuid
    ts: str  # ISO timestamp
    git_branch: str
    text: str  # cleaned human text
    turn: int  # 0-based index among human prompts in the session
    prev_assistant_text: str  # truncated
    prev_tools: tuple[str, ...]  # tools used since the previous human prompt
    prev_files: tuple[str, ...]  # files written/edited since previous prompt
    user_denied: bool  # human rejected a tool call in that span
    classifier_denied: bool  # auto-mode classifier blocked a call
    interrupted: bool  # human hit escape
    source: str = "queue"  # "queue" (desktop submit) or "user" (cli record)

    @property
    def key(self) -> str:
        return f"{self.session}:{self.uuid}"


@dataclass(slots=True)
class Session:
    path: Path
    project: str
    project_name: str
    session: str
    cwd: str
    git_branch: str
    prompts: list[Prompt] = field(default_factory=list)
    raw_user_records: int = 0  # every type=="user" record, incl. tool results
    queued_records: int = 0  # queue-operation/enqueue records seen
    dropped_synthetic: int = 0  # records rejected as machine-generated
    duplicate_records: int = 0  # same prompt seen on both channels
    bad_lines: int = 0
    mtime: float = 0.0

    @property
    def started(self) -> str:
        return self.prompts[0].ts if self.prompts else ""


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def projects_root() -> Path:
    """Transcript root. Overridable for tests and for non-default installs."""
    if env := os.environ.get("CLAUDE_ADAPT_RULES_PROJECTS_ROOT"):
        return Path(env)
    if env := os.environ.get("CLAUDE_CONFIG_DIR"):
        return Path(env) / "projects"
    return Path.home() / ".claude" / "projects"


def iter_session_files(
    root: Path | None = None, since: datetime | None = None
) -> Iterator[Path]:
    """Yield main-thread transcripts, oldest first.

    ``projects/*/*.jsonl`` matches main threads only; subagent logs live one
    level deeper under ``<session-uuid>/subagents/``.
    """
    root = root or projects_root()
    if not root.is_dir():
        return
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)
    for path in files:
        if since is not None:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < since:
                continue
        yield path


def cutoff(days: int) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


# Slugs are the cwd with separators flattened:
# "C:\Users\alice\src\my-app" -> "C--Users-alice-src-my-app"
_SLUG_PREFIX_RE = re.compile(
    r"^[A-Za-z]--(?:Users-[^-]+-)?(?:sources-)?(?:repos-)?", re.IGNORECASE
)

# Worktrees get their own slug:
#   ...src-my-app--claude-worktrees-brave-newton-a1b2c3
# They are the same repository. Left un-normalised, a worktree counts as a second
# project and wrongly promotes that repo's quirks to global scope.
_WORKTREE_RE = re.compile(r"--claude-worktrees-.*$|[\\/]\.claude-worktrees[\\/].*$")


def canonical_project(slug: str) -> str:
    """Collapse worktree slugs onto the repository they branch from."""
    return _WORKTREE_RE.sub("", slug) or slug


def project_name_from_cwd(cwd: str) -> str:
    """Project name for a working directory, collapsing worktree paths.

    A session started inside a worktree belongs to the repository it branches from,
    so it must see that repository's rules.
    """
    return Path(_WORKTREE_RE.sub("", str(cwd))).name


def friendly_project_name(slug: str, cwd: str = "") -> str:
    """Human-readable project name.

    Derived from the canonical slug, not from cwd: cwd differs between a repo and
    its worktrees and subdirectories, which would give one project two names and
    split its evidence. cwd is only a fallback for slugs that trim to nothing.
    """
    trimmed = _SLUG_PREFIX_RE.sub("", canonical_project(slug)).strip("-")
    if trimmed:
        return trimmed
    if cwd:
        name = Path(_WORKTREE_RE.sub("", cwd)).name
        if name:
            return name
    return slug


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #


def _blocks(content: object) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _joined_text(content: object) -> str:
    return "\n".join(
        b.get("text") or "" for b in _blocks(content) if b.get("type") == "text"
    ).strip()


def clean_prompt_text(text: str) -> str:
    """Strip injected wrappers. Returns "" when nothing human remains."""
    text = _SYSTEM_REMINDER_RE.sub("", text).strip()
    if not text:
        return ""
    # Hook payloads are prepended; keep whatever follows the last hook line.
    if "hook success" in text.lower() or "hook additional context" in text.lower():
        parts = _HOOK_PAYLOAD_RE.split(text)
        text = parts[-1].strip() if parts else ""
    while (m := _LEADING_TAG_RE.match(text)) and m.group(1) in SYNTHETIC_LEADING_TAGS:
        tag = m.group(1)
        closing = f"</{tag}>"
        end = text.find(closing)
        if end == -1:
            return ""  # unterminated synthetic block: nothing trustworthy left
        text = (text[: m.start()] + text[end + len(closing) :]).strip()
    if _INTERRUPT_RE.match(text):
        return ""
    # A slash command with arguments: everything before ARGUMENTS: is injected
    # skill text, everything after it is what the user actually typed.
    if (m := _ARGUMENTS_RE.search(text)) and m.group(1).strip():
        text = m.group(1).strip()
    if is_machine_prompt(text):
        return ""
    # Bare `/command` carries no preference; `/command do the thing` does.
    stripped = _SLASH_COMMAND_RE.sub("", text, count=1).strip()
    if stripped != text:
        text = stripped
    return text


def is_machine_prompt(text: str) -> bool:
    """True for text the harness wrote on the human channel."""
    stripped = text.lstrip()
    return any(pattern.match(stripped) for pattern in _MACHINE_PROMPT_RES)


def _dedup_head(text: str) -> str:
    """Normalised prefix used to spot the same prompt arriving twice."""
    return " ".join(text.split())[:80].lower()


def _tool_result_flags(content: object) -> tuple[bool, bool]:
    """(user_denied, classifier_denied) for one user record's tool results."""
    user_denied = classifier_denied = False
    for b in _blocks(content):
        if b.get("type") != "tool_result":
            continue
        payload = b.get("content")
        text = payload if isinstance(payload, str) else json.dumps(payload)
        if _USER_DENIAL_RE.search(text):
            user_denied = True
        if _CLASSIFIER_DENIAL_RE.search(text):
            classifier_denied = True
    return user_denied, classifier_denied


def _has_tool_result(content: object) -> bool:
    return any(b.get("type") == "tool_result" for b in _blocks(content))


_FILE_ARG_KEYS = ("file_path", "notebook_path", "path")


def _tool_uses(content: object) -> tuple[list[str], list[str]]:
    names: list[str] = []
    files: list[str] = []
    for b in _blocks(content):
        if b.get("type") != "tool_use":
            continue
        names.append(str(b.get("name") or "?"))
        args = b.get("input")
        if isinstance(args, dict):
            for k in _FILE_ARG_KEYS:
                if isinstance(args.get(k), str):
                    files.append(args[k])
                    break
    return names, files


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_MAX_PREV_TEXT = 1200


def parse_session(path: Path) -> Session:
    """Parse one main-thread transcript. Tolerates truncated/corrupt lines."""
    slug = canonical_project(path.parent.name)
    sess = Session(
        path=path,
        project=slug,
        project_name=friendly_project_name(slug),
        session=path.stem,
        cwd="",
        git_branch="",
        mtime=path.stat().st_mtime,
    )

    # Accumulated agent activity since the last human prompt.
    prev_text: list[str] = []
    prev_tools: list[str] = []
    prev_files: list[str] = []
    user_denied = classifier_denied = interrupted = False
    turn = 0
    queued_heads: set[str] = set()  # dedup: queue record vs its type:user twin

    def emit(text: str, *, uuid: str, ts: str, branch: str, source: str) -> None:
        nonlocal turn, prev_text, prev_tools, prev_files
        nonlocal user_denied, classifier_denied, interrupted
        sess.prompts.append(
            Prompt(
                project=slug,
                project_name=sess.project_name,
                session=sess.session,
                uuid=uuid,
                ts=ts,
                git_branch=branch,
                text=text,
                turn=turn,
                prev_assistant_text="\n".join(prev_text)[-_MAX_PREV_TEXT:],
                prev_tools=tuple(prev_tools),
                prev_files=tuple(dict.fromkeys(prev_files)),
                user_denied=user_denied,
                classifier_denied=classifier_denied,
                interrupted=interrupted,
                source=source,
            )
        )
        turn += 1
        prev_text, prev_tools, prev_files = [], [], []
        user_denied = classifier_denied = interrupted = False

    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                sess.bad_lines += 1
                continue
            if not isinstance(rec, dict):
                sess.bad_lines += 1
                continue

            rtype = rec.get("type")
            if not sess.cwd and isinstance(rec.get("cwd"), str):
                sess.cwd = rec["cwd"]
                sess.project_name = friendly_project_name(slug, sess.cwd)
            if not sess.git_branch and rec.get("gitBranch"):
                sess.git_branch = str(rec["gitBranch"])

            message = rec.get("message")
            content = message.get("content") if isinstance(message, dict) else None

            # Primary human channel on desktop: the prompt queue.
            if rtype == "queue-operation":
                if rec.get("operation") != "enqueue":
                    continue
                sess.queued_records += 1
                text = clean_prompt_text(str(rec.get("content") or ""))
                if not text:
                    sess.dropped_synthetic += 1
                    continue
                queued_heads.add(_dedup_head(text))
                ts = str(rec.get("timestamp") or "")
                emit(
                    text,
                    uuid=f"q-{ts}-{turn}",
                    ts=ts,
                    branch=sess.git_branch,
                    source="queue",
                )
                continue

            if rtype == "assistant":
                if rec.get("isSidechain"):
                    continue
                text = _joined_text(content)
                if text:
                    prev_text.append(text)
                names, files = _tool_uses(content)
                prev_tools.extend(names)
                prev_files.extend(files)
                continue

            if rtype != "user":
                continue
            sess.raw_user_records += 1

            if rec.get("isSidechain") or rec.get("promptSource") == "sdk":
                sess.dropped_synthetic += 1
                continue

            if _has_tool_result(content):
                denied, classifier = _tool_result_flags(content)
                user_denied |= denied
                classifier_denied |= classifier
                sess.dropped_synthetic += 1
                continue

            raw = _joined_text(content)
            if _INTERRUPT_RE.search(raw):
                interrupted = True
            text = clean_prompt_text(raw)
            if not text:
                sess.dropped_synthetic += 1
                continue
            # The queue record for this prompt already produced an event.
            if _dedup_head(text) in queued_heads:
                sess.duplicate_records += 1
                continue

            emit(
                text,
                uuid=str(rec.get("uuid") or ""),
                ts=str(rec.get("timestamp") or ""),
                branch=str(rec.get("gitBranch") or sess.git_branch),
                source="user",
            )

    return sess


def parse_all(
    root: Path | None = None, since: datetime | None = None
) -> Iterator[Session]:
    for path in iter_session_files(root, since):
        try:
            yield parse_session(path)
        except OSError:
            continue


def all_prompts(sessions: Sequence[Session]) -> list[Prompt]:
    return [p for s in sessions for p in s.prompts]
