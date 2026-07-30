"""Score human prompts by how much correction signal they carry. Stdlib only.

Two families of signal:

*Lexical*  - the words used ("don't", "wrong", "always", "nicht"). Cheap, noisy.
*Structural* - what happened around the turn (a tool call was denied, the same
instruction was repeated, the agent had just edited a file). Harder to fake and
therefore weighted higher.

Baseline lexical hit counts over the 1446 local main-thread prompts, measured
before this module existed: negation_en 408, scope 343, wrong 259,
verify_demand 191, style_pref 170, negation_de 17, why_do_you 1.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .transcripts import Prompt

# --------------------------------------------------------------------------- #
# Lexical signals
# --------------------------------------------------------------------------- #

LEXICAL: dict[str, tuple[re.Pattern[str], int]] = {
    # Explicit meta-complaint about a habit. Rare and the highest-value signal
    # there is: the user is describing the rule they want, not just the defect.
    "why_do_you": (
        re.compile(
            r"\bwhy (?:do|did|are|is|would) you\b|"
            r"\bwarum (?:hast|machst|tust|bist) du\b|"
            r"\byou (?:always|keep|never) \w+",
            re.IGNORECASE,
        ),
        5,
    ),
    "wrong": (
        re.compile(
            r"\b(?:wrong|incorrect|broken|bullshit|nonsense)\b|"
            r"\bstill (?:fails?|failing|not|doesn'?t|broken)\b|"
            r"\b(?:immer noch|geht nicht|klappt nicht|funktioniert nicht|falsch|quatsch)\b",
            re.IGNORECASE,
        ),
        3,
    ),
    "negation_en": (
        re.compile(
            r"\b(?:don'?t|do not|never|stop|instead of|rather than|revert|undo|rollback)\b|"
            r"\bno,|\bnot like that\b",
            re.IGNORECASE,
        ),
        2,
    ),
    "negation_de": (
        re.compile(
            r"\b(?:nicht|nie|niemals|kein|keine|keinen|stattdessen|zurücknehmen|nein)\b",
            re.IGNORECASE,
        ),
        2,
    ),
    "verify_demand": (
        re.compile(
            r"\b(?:verify|prove|actually (?:check|test|run)|run the tests?|"
            r"did you (?:run|test|check)|beweis|teste?n? es|nachweis)\b",
            re.IGNORECASE,
        ),
        2,
    ),
    "scope": (
        re.compile(
            r"\b(?:only|just do|don'?t touch|out of scope|keep it simple|minimal|"
            r"nur|nicht anfassen|einfach halten)\b",
            re.IGNORECASE,
        ),
        2,
    ),
    "style_pref": (
        re.compile(
            r"\b(?:always|prefer|convention|idiomatic|use \w+ instead|"
            r"immer|bevorzuge|konvention)\b",
            re.IGNORECASE,
        ),
        2,
    ),
    # Rules the user states as rules. Distinct from style_pref: imperative form.
    "explicit_rule": (
        re.compile(
            r"\b(?:rule|from now on|going forward|remember (?:that|to)|"
            r"add (?:this|it) to claude\.?md|regel|ab jetzt|merke dir)\b",
            re.IGNORECASE,
        ),
        4,
    ),
}

# --------------------------------------------------------------------------- #
# Structural signals
# --------------------------------------------------------------------------- #

STRUCTURAL_WEIGHTS = {
    "repeated_instruction": 6,  # had to say it twice in one session
    "user_denied": 5,  # rejected a tool call outright
    "interrupted": 3,  # escape key
    # Context, not signal. 407 of 778 local prompts follow an edit -- scoring it
    # would rank "commit and push" alongside a real correction. It only earns a
    # point when the words are corrective too (see CORRECTIVE_AFTER_EDIT_BONUS).
    "after_edit": 0,
    # The auto-mode classifier blocked the call, not the human. Worth recording,
    # never worth treating as a preference.
    "classifier_denied": 0,
}

# Structural signals strong enough to select an event on their own.
SELECTING_STRUCTURAL = frozenset({"repeated_instruction", "user_denied", "interrupted"})

# "don't"/"wrong" immediately after the agent edited files is likelier to be
# about the edit than about anything else.
CORRECTIVE_AFTER_EDIT_BONUS = 1
_CORRECTIVE_LEXICAL = frozenset({"negation_en", "negation_de", "wrong", "why_do_you"})

_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Acknowledgements carry no rule content, and there are a lot of them.
_ACK_RE = re.compile(
    r"^(?:ok(?:ay)?|yes|yep|ja|jo|nice|thanks|thx|danke|go|go on|continue|weiter|"
    r"proceed|do it|mach|mach weiter|next|sure|good|perfect|passt|\+?\d+k?|"
    r"y|n|approved?)\W*$",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    """a an the and or but if then than that this these those is are was were be been
    being do does did doing to of in on for with as at by from it its i you we they
    he she not no so all can could should would will just now here there what which
    who how why when where der die das und oder aber wenn dann als ist sind war waren
    sein zu von in auf für mit bei durch es ich du wir sie ihr nicht kein so alle
    kann könnte sollte würde wird jetzt hier da was wer wie warum wann wo""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


REPEAT_THRESHOLD = 0.5
MIN_REPEAT_TOKENS = 4


@dataclass(slots=True)
class Event:
    """A scored human prompt: candidate evidence for one or more rules."""

    prompt: Prompt
    score: int
    lexical: tuple[str, ...]
    structural: tuple[str, ...]
    repeat_of: str | None = None  # record uuid of the earlier, similar prompt

    @property
    def signals(self) -> tuple[str, ...]:
        return self.lexical + self.structural

    def to_dict(self) -> dict:
        p = self.prompt
        return {
            "score": self.score,
            "lexical": list(self.lexical),
            "structural": list(self.structural),
            "repeat_of": self.repeat_of,
            "project": p.project,
            "project_name": p.project_name,
            "session": p.session,
            "uuid": p.uuid,
            "ts": p.ts,
            "git_branch": p.git_branch,
            "turn": p.turn,
            "text": p.text,
            "prev_tools": list(p.prev_tools),
            "prev_files": list(p.prev_files),
            "prev_assistant_text": p.prev_assistant_text,
        }


def is_acknowledgement(text: str) -> bool:
    return bool(_ACK_RE.match(text.strip()))


def score_prompt(
    prompt: Prompt, earlier: Sequence[Prompt] = ()
) -> Event:
    """Score one prompt. ``earlier`` = same-session prompts that preceded it."""
    lexical = tuple(
        name for name, (pattern, _) in LEXICAL.items() if pattern.search(prompt.text)
    )
    structural: list[str] = []
    repeat_of: str | None = None

    if prompt.user_denied:
        structural.append("user_denied")
    if prompt.classifier_denied:
        structural.append("classifier_denied")
    if prompt.interrupted:
        structural.append("interrupted")
    if _EDIT_TOOLS.intersection(prompt.prev_tools):
        structural.append("after_edit")

    own = _tokens(prompt.text)
    if len(own) >= MIN_REPEAT_TOKENS:
        for prior in earlier:
            if _jaccard(own, _tokens(prior.text)) >= REPEAT_THRESHOLD:
                structural.append("repeated_instruction")
                repeat_of = prior.uuid
                break

    score = sum(LEXICAL[name][1] for name in lexical)
    score += sum(STRUCTURAL_WEIGHTS[name] for name in structural)
    if "after_edit" in structural and _CORRECTIVE_LEXICAL.intersection(lexical):
        score += CORRECTIVE_AFTER_EDIT_BONUS

    return Event(
        prompt=prompt,
        score=score,
        lexical=lexical,
        structural=tuple(structural),
        repeat_of=repeat_of,
    )


def score_session(prompts: Sequence[Prompt]) -> list[Event]:
    """Score every prompt in one session, skipping bare acknowledgements."""
    events: list[Event] = []
    for i, prompt in enumerate(prompts):
        if is_acknowledgement(prompt.text):
            continue
        events.append(score_prompt(prompt, prompts[:i]))
    return events


MIN_KEEP_SCORE = 3


def select(events: Iterable[Event], min_score: int = MIN_KEEP_SCORE) -> list[Event]:
    """Keep strong structural hits plus lexical hits at or above ``min_score``.

    A denied or interrupted turn is evidence even when the user said nothing
    quotable. Merely following an edit is not.
    """
    kept = [
        e
        for e in events
        if SELECTING_STRUCTURAL.intersection(e.structural) or e.score >= min_score
    ]
    kept.sort(key=lambda e: (-e.score, e.prompt.ts))
    return kept


@dataclass(slots=True)
class Stats:
    sessions: int = 0
    projects: set[str] = field(default_factory=set)
    raw_user_records: int = 0
    queued_records: int = 0
    duplicate_records: int = 0
    prompts: int = 0
    acknowledgements: int = 0
    dropped_synthetic: int = 0
    bad_lines: int = 0
    scored: int = 0
    selected: int = 0
    by_signal: dict[str, int] = field(default_factory=dict)

    def bump(self, names: Iterable[str]) -> None:
        for name in names:
            self.by_signal[name] = self.by_signal.get(name, 0) + 1
