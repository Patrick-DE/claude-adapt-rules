"""Work you keep doing by hand, which no correction signal will ever reveal.

Every signal in ``signals.py`` is corrective -- negation, "wrong", a denied tool
call, an interrupt. That only ever finds things you complained about. A workflow
you drive by hand five times without once complaining produces no signal at all,
so the pipeline is structurally blind to it.

Credit for naming the gap: Task-Observer by Eoghan Henn (rebelytics), which
watches for "coverage gaps" -- manual work that could be systematised -- as a
first-class category alongside corrections.
https://github.com/rebelytics/one-skill-to-rule-them-all (CC BY 4.0)

The detector here is deliberately structural rather than model-driven: it counts
recurring tool sequences. That is evidence of a repeated *shape* of work, which
is a candidate for a skill -- not a conclusion that one is warranted. The
judgement stays with you.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .transcripts import Session

# A sequence shorter than this is a step, not a workflow: every session contains
# "Read, Edit" and reporting it would bury the real repetition.
MIN_SEQUENCE = 3
# Long tails are usually one-off exploration rather than a repeatable procedure.
MAX_SEQUENCE = 8
# Below this it is a coincidence, not a habit.
MIN_OCCURRENCES = 3

# Tools that say nothing about the shape of the work. TodoWrite and friends
# appear in almost every span and would make every sequence look alike.
IGNORED_TOOLS = frozenset(
    {"TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "ToolSearch", "Skill"}
)

# The universal edit loop. Measured on the local corpus, the top sequences were
# all permutations of these -- "Read → Edit → Bash" seven times across four
# projects -- because `Bash` covers `git status` and the test suite alike. That
# is what coding *is*, not a procedure worth capturing, and reporting it buries
# the sequences that are genuinely distinctive. A candidate must therefore reach
# for at least one tool outside this set.
UBIQUITOUS_TOOLS = frozenset({"Read", "Edit", "Write", "Bash", "Grep", "Glob"})


def is_distinctive(shape: Sequence[str]) -> bool:
    """True when the sequence involves something beyond the ordinary edit loop."""
    return any(tool not in UBIQUITOUS_TOOLS for tool in shape)


@dataclass(slots=True)
class Workflow:
    """One recurring tool sequence, and where it was seen."""

    tools: tuple[str, ...]
    occurrences: int = 0
    projects: set[str] = field(default_factory=set)
    sessions: set[str] = field(default_factory=set)
    example_prompt: str = ""

    @property
    def label(self) -> str:
        return " → ".join(self.tools)

    @property
    def spread(self) -> str:
        return f"{len(self.sessions)} session(s), {len(self.projects)} project(s)"


def normalise(tools: Sequence[str]) -> tuple[str, ...]:
    """Collapse a raw tool span into the shape of the work.

    Consecutive repeats become one entry: reading four files then editing one is
    the same procedure as reading two then editing one, and leaving the counts in
    would split one habit into a dozen near-miss sequences.
    """
    shape: list[str] = []
    for tool in tools:
        if tool in IGNORED_TOOLS:
            continue
        if not shape or shape[-1] != tool:
            shape.append(tool)
    return tuple(shape[:MAX_SEQUENCE])


def collect(sessions: Iterable[Session]) -> list[Workflow]:
    """Recurring tool sequences across every session, most repeated first.

    Only spans that were *not* followed by a correction count. A span the user
    complained about is already covered by the corrective signals; counting it
    here would propose a skill for work that went wrong.
    """
    from .signals import LEXICAL

    found: dict[tuple[str, ...], Workflow] = defaultdict(lambda: Workflow(tools=()))
    for session in sessions:
        for prompt in session.prompts:
            if prompt.user_denied or prompt.interrupted:
                continue
            if any(pattern.search(prompt.text) for pattern, _ in LEXICAL.values()):
                continue
            shape = normalise(prompt.prev_tools)
            if len(shape) < MIN_SEQUENCE or not is_distinctive(shape):
                continue
            entry = found[shape]
            entry.tools = shape
            entry.occurrences += 1
            entry.projects.add(prompt.project_name or prompt.project)
            entry.sessions.add(prompt.session)
            if not entry.example_prompt:
                entry.example_prompt = " ".join(prompt.text.split())[:120]

    workflows = [w for w in found.values() if w.occurrences >= MIN_OCCURRENCES]
    workflows.sort(key=lambda w: (-w.occurrences, -len(w.projects), w.label))
    return workflows


def render(workflows: Sequence[Workflow], limit: int = 15) -> str:
    """Report the candidates. Truncation is stated, never silent."""
    lines = [
        "# Skill candidates: work repeated by hand",
        "",
        "Tool sequences you drove repeatedly without correcting the agent. A repeated",
        "shape of work is a candidate for a skill, not proof one is needed -- read the",
        "example prompt before deciding.",
        "",
    ]
    if not workflows:
        lines += [
            f"_None: no sequence of {MIN_SEQUENCE}+ distinct tools reaching beyond the",
            f"ordinary edit loop recurred {MIN_OCCURRENCES}+ times._",
            "",
        ]
        return "\n".join(lines)

    kept = workflows[:limit]
    lines += ["| times | spread | sequence | example prompt |", "| --- | --- | --- | --- |"]
    for w in kept:
        example = w.example_prompt.replace("|", "\\|") or "_(none)_"
        lines.append(f"| {w.occurrences} | {w.spread} | `{w.label}` | {example} |")
    if len(workflows) > limit:
        lines += ["", f"_{len(workflows) - limit} further candidate(s) not shown._"]
    lines.append("")
    return "\n".join(lines)
