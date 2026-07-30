"""What counts as a human prompt, and what must never count as one."""

from __future__ import annotations

from claude_adapt_rules.transcripts import (
    canonical_project,
    friendly_project_name,
    is_machine_prompt,
    parse_session,
)

from .conftest import (
    DENIAL,
    assistant,
    enqueue,
    tool_result,
    user_blocks,
    user_text,
)


def texts(session) -> list[str]:
    return [p.text for p in session.prompts]


def test_queue_enqueue_is_the_human_channel(make_transcript):
    path = make_transcript([enqueue("use the repository pattern here")])
    session = parse_session(path)
    assert texts(session) == ["use the repository pattern here"]
    assert session.prompts[0].source == "queue"


def test_tool_results_are_not_prompts(make_transcript):
    path = make_transcript([tool_result("file contents here")])
    session = parse_session(path)
    assert session.prompts == []
    assert session.raw_user_records == 1


def test_subagent_prompts_excluded(make_transcript):
    path = make_transcript(
        [
            user_text("review this branch", promptSource="sdk"),
            user_text("locate the handler", isSidechain=True),
        ]
    )
    assert parse_session(path).prompts == []


def test_machine_pseudo_prompts_excluded(make_transcript):
    path = make_transcript(
        [
            enqueue("Continue from where you left off."),
            enqueue("This session is being continued from a previous conversation that ran out"),
            enqueue("Base directory for this skill: C:\\x\\y"),
            enqueue("Stop hook feedback: [checker] do more"),
            enqueue("<task-notification> <task-id>abc</task-id> </task-notification>"),
        ]
    )
    assert parse_session(path).prompts == []


def test_injected_skill_body_is_not_a_prompt(make_transcript):
    """A slash command pastes the whole SKILL.md in; unfiltered it outscores real corrections."""
    body = (
        "# Update Config Skill\n\nModify Claude Code configuration by updating "
        "settings.json files.\n\n## CRITICAL: Read Before Write\n\nAlways read first."
    )
    path = make_transcript([enqueue(body)])
    assert parse_session(path).prompts == []


def test_slash_command_arguments_are_the_human_part(make_transcript):
    body = (
        "# How claude-mem works\n\nEvery Read, Edit and Bash becomes an observation.\n\n"
        "ARGUMENTS: do we keep track of what was already ingested so we do not double ingest?"
    )
    path = make_transcript([enqueue(body)])
    assert texts(parse_session(path)) == [
        "do we keep track of what was already ingested so we do not double ingest?"
    ]


def test_bare_slash_command_dropped_but_trailing_request_kept(make_transcript):
    path = make_transcript(
        [enqueue("/claude-mem:how-it-works"), enqueue("/simplify never inline styles here")]
    )
    assert texts(parse_session(path)) == ["never inline styles here"]


def test_system_reminder_stripped_but_human_text_kept(make_transcript):
    path = make_transcript(
        [enqueue("<system-reminder>be careful</system-reminder>\nsplit that file")]
    )
    assert texts(parse_session(path)) == ["split that file"]


def test_malformed_line_tolerated(make_transcript):
    path = make_transcript([enqueue("keep going")], raw_lines=["{not json", ""])
    session = parse_session(path)
    assert texts(session) == ["keep going"]
    assert session.bad_lines == 1


def test_same_prompt_on_both_channels_counted_once(make_transcript):
    path = make_transcript(
        [
            enqueue("never use mocks in integration tests"),
            user_text("never use mocks in integration tests"),
        ]
    )
    session = parse_session(path)
    assert texts(session) == ["never use mocks in integration tests"]
    assert session.duplicate_records == 1


def test_cli_style_user_prompt_still_captured(make_transcript):
    """Sessions without a queue (plain CLI) must still yield prompts."""
    path = make_transcript([user_text("add a test for the parser")])
    session = parse_session(path)
    assert texts(session) == ["add a test for the parser"]
    assert session.prompts[0].source == "user"


def test_context_captures_preceding_agent_activity(make_transcript):
    path = make_transcript(
        [
            enqueue("first"),
            assistant("editing now", tools=[("Edit", "src/app.py"), ("Bash", "")]),
            enqueue("no, not like that"),
        ]
    )
    second = parse_session(path).prompts[1]
    assert second.prev_tools == ("Edit", "Bash")
    assert second.prev_files == ("src/app.py",)
    assert "editing now" in second.prev_assistant_text
    assert second.turn == 1


def test_denied_tool_call_flags_the_next_prompt(make_transcript):
    path = make_transcript(
        [
            enqueue("go"),
            assistant(tools=[("Bash", "")]),
            tool_result(DENIAL),
            enqueue("use the test runner instead"),
        ]
    )
    prompts = parse_session(path).prompts
    assert prompts[1].user_denied is True
    assert prompts[0].user_denied is False


def test_classifier_denial_is_distinct_from_user_denial(make_transcript):
    path = make_transcript(
        [
            enqueue("go"),
            assistant(tools=[("Bash", "")]),
            tool_result(
                "Permission for this action was denied by the Claude Code auto mode "
                "classifier. Reason: [Credential Exploration]"
            ),
            enqueue("fine, skip it"),
        ]
    )
    prompt = parse_session(path).prompts[1]
    assert prompt.classifier_denied is True
    assert prompt.user_denied is False


def test_interrupt_marker_flags_but_is_not_a_prompt(make_transcript):
    path = make_transcript(
        [
            enqueue("start"),
            assistant("working"),
            user_blocks([{"type": "text", "text": "[Request interrupted by user]"}]),
            enqueue("stop rewriting the config"),
        ]
    )
    prompts = parse_session(path).prompts
    assert [p.text for p in prompts] == ["start", "stop rewriting the config"]
    assert prompts[1].interrupted is True


def test_friendly_project_name():
    assert friendly_project_name("C--Users-alice-sources-repos-web-api") == "web-api"
    assert friendly_project_name("F--Tools-SomeMcpServer") == "Tools-SomeMcpServer"
    # cwd is only a fallback: the slug is authoritative so one project keeps one name.
    assert friendly_project_name("C--Users-alice-sources-repos-app", cwd=r"C:\x\other") == "app"
    assert friendly_project_name("C--Users-alice-", cwd=r"C:\a\b\my-app") == "my-app"


def test_worktrees_collapse_onto_their_repository(make_transcript):
    """Otherwise a worktree counts as a second project and fakes a global rule."""
    slug = "C--Users-alice-sources-repos-app--claude-worktrees-brave-newton-a1b2c3"
    assert canonical_project(slug) == "C--Users-alice-sources-repos-app"
    assert friendly_project_name(slug) == "app"

    path = make_transcript([enqueue("never do that here")], project=slug)
    session = parse_session(path)
    assert session.project == "C--Users-alice-sources-repos-app"
    assert session.prompts[0].project_name == "app"


def test_is_machine_prompt_only_matches_harness_text():
    assert is_machine_prompt("Continue from where you left off.")
    assert not is_machine_prompt("continue from the failing test and fix it")
