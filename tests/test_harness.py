"""What was used, not what is installed — and the gap between them."""

from __future__ import annotations

from pathlib import Path

from claude_adapt_rules.harness import (
    agents_visible_from,
    check_agents,
    collect,
    installed_agents,
    installed_skills,
    render,
)

from .conftest import assistant, enqueue


def _skill(name: str) -> dict:
    rec = assistant(tools=[("Skill", "")])
    rec["message"]["content"][0]["input"] = {"skill": name}
    return rec


def _agent(subagent: str | None) -> dict:
    rec = assistant(tools=[("Agent", "")])
    rec["message"]["content"][0]["input"] = {"subagent_type": subagent} if subagent else {}
    return rec


def test_skills_agents_and_tools_are_separated(make_transcript, tmp_path):
    make_transcript(
        [
            enqueue("go"),
            _skill("superpowers:brainstorming"),
            _agent("code-reviewer"),
            assistant(tools=[("Read", "a.py"), ("Bash", "")]),
        ]
    )
    usages = collect(tmp_path / "projects")
    kinds = {(u.kind, u.name) for u in usages}
    assert ("skill", "superpowers:brainstorming") in kinds
    assert ("agent", "code-reviewer") in kinds
    assert ("tool", "Read") in kinds and ("tool", "Bash") in kinds


def test_repeat_use_is_counted_and_the_latest_date_kept(make_transcript, tmp_path):
    records = [enqueue("go")]
    for ts in ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"):
        rec = _skill("update-config")
        rec["timestamp"] = ts
        records.append(rec)
    usages = collect(tmp_path / "projects")
    make_transcript(records)
    usages = collect(tmp_path / "projects")
    skill = next(u for u in usages if u.name == "update-config")
    assert skill.count == 2
    assert skill.last_used.startswith("2026-08-01")


def test_an_unnamed_subagent_is_still_recorded(make_transcript, tmp_path):
    make_transcript([enqueue("go"), _agent(None)])
    usages = collect(tmp_path / "projects")
    assert any(u.kind == "agent" and u.name == "general-purpose" for u in usages)


def test_installed_but_never_used_is_the_finding(make_transcript, tmp_path):
    make_transcript([enqueue("go"), _skill("used-one")])
    skills_root = tmp_path / "skills"
    for name in ("used-one", "never-fired"):
        (skills_root / name).mkdir(parents=True)

    usages = collect(tmp_path / "projects")
    used = {u.name for u in usages if u.kind == "skill"}
    assert installed_skills(skills_root) - used == {"never-fired"}

    text = render(usages, never_fired={"never-fired"})
    assert "never-fired" in text.split("## Installed but never observed")[1]


def test_missing_skills_directory_is_not_an_error(tmp_path):
    assert installed_skills(tmp_path / "nope") == set()


def test_render_states_it_measures_use_not_installation(make_transcript, tmp_path):
    make_transcript([enqueue("go")])
    text = render(collect(tmp_path / "projects"))
    assert "not what is installed" in text


# --------------------------------------------------------------------------- #
# Agent hygiene: used, advertised and installed must agree
#
# Found on the real machine: two agents dispatched 62 times between them were no
# longer loadable -- one renamed to .bak, one gone entirely. Nothing reported it,
# and a failed dispatch reads as a bug in the task rather than a missing file.
# --------------------------------------------------------------------------- #


def _agents_dir(tmp_path, names, shelved=()):
    root = tmp_path / "agents"
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: test agent\n---\n", encoding="utf-8"
        )
    for name in shelved:
        (root / name).write_text("shelved", encoding="utf-8")
    return root


def _roster(tmp_path, names) -> Path:
    path = tmp_path / "CLAUDE.md"
    body = "\n".join(f"- **{n}** — does a thing" for n in names)
    path.write_text(f"# Roster\n\n{body}\n", encoding="utf-8")
    return path


def test_an_agent_used_but_no_longer_installed_is_reported(make_transcript, tmp_path):
    make_transcript([enqueue("go"), _agent("rtt-rust-engineer")])
    usages = collect(tmp_path / "projects")
    hygiene = check_agents(
        usages,
        agents_root=_agents_dir(tmp_path, [], shelved=["rtt-rust-engineer.md.bak"]),
        claudemd=_roster(tmp_path, []),
    )
    assert hygiene.used_but_missing == {"rtt-rust-engineer"}
    assert hygiene.shelved == {"rtt-rust-engineer.md.bak"}
    assert not hygiene.ok


def test_a_roster_entry_with_no_file_is_a_handoff_target_nobody_has(tmp_path):
    hygiene = check_agents(
        [],
        agents_root=_agents_dir(tmp_path, ["real-agent"]),
        claudemd=_roster(tmp_path, ["real-agent", "imaginary-agent"]),
    )
    assert hygiene.advertised_but_missing == {"imaginary-agent"}
    assert not hygiene.ok


def test_installed_but_unadvertised_is_noted_without_failing(tmp_path):
    """Deliberate often enough that it must not be an error."""
    hygiene = check_agents(
        [],
        agents_root=_agents_dir(tmp_path, ["listed", "unlisted"]),
        claudemd=_roster(tmp_path, ["listed"]),
    )
    assert hygiene.installed_but_unadvertised == {"unlisted"}
    assert hygiene.ok


def test_builtin_agents_are_not_reported_as_missing(make_transcript, tmp_path):
    """They dispatch without a file on disk, so absence is not a fault."""
    make_transcript([enqueue("go"), _agent("general-purpose"), _agent("Explore")])
    hygiene = check_agents(
        collect(tmp_path / "projects"),
        agents_root=_agents_dir(tmp_path, []),
        claudemd=_roster(tmp_path, []),
    )
    assert hygiene.used_but_missing == set()
    assert hygiene.ok


def test_plugin_agents_are_not_reported_as_missing(make_transcript, tmp_path):
    """`plugin:agent` lives in the plugin cache, not the agents directory."""
    make_transcript([enqueue("go"), _agent("caveman:cavecrew-builder")])
    hygiene = check_agents(
        collect(tmp_path / "projects"),
        agents_root=_agents_dir(tmp_path, []),
        claudemd=_roster(tmp_path, []),
    )
    assert hygiene.used_but_missing == set()


def test_a_healthy_harness_says_so(tmp_path, make_transcript):
    make_transcript([enqueue("go"), _agent("rtt-reviewer-agent")])
    hygiene = check_agents(
        collect(tmp_path / "projects"),
        agents_root=_agents_dir(tmp_path, ["rtt-reviewer-agent"]),
        claudemd=_roster(tmp_path, ["rtt-reviewer-agent"]),
    )
    assert hygiene.ok
    assert "all agree" in render([], hygiene=hygiene)


def test_missing_directories_are_not_an_error(tmp_path):
    hygiene = check_agents([], agents_root=tmp_path / "nope", claudemd=tmp_path / "nope.md")
    assert hygiene.ok


def test_a_project_agent_is_not_a_broken_handoff(make_transcript, tmp_path):
    """The false positive this check shipped with.

    rtt-re-memory-engineer and rtt-rust-engineer were dispatched 62 times between
    them and reported as missing, because only the global directory was searched.
    Both were installed — in the project's own .claude/agents/.
    """
    project_dir = tmp_path / "myrepo"
    _agents_dir(project_dir / ".claude", ["project-only-agent"])
    rec = _agent("project-only-agent")
    rec["cwd"] = str(project_dir)
    make_transcript([enqueue("go"), rec])

    hygiene = check_agents(
        collect(tmp_path / "projects"),
        agents_root=_agents_dir(tmp_path, []),  # empty global
        claudemd=_roster(tmp_path, []),
    )
    assert hygiene.used_but_missing == set()
    assert hygiene.ok


def test_an_agent_missing_from_both_scopes_is_still_reported(make_transcript, tmp_path):
    project_dir = tmp_path / "myrepo"
    _agents_dir(project_dir / ".claude", ["something-else"])
    rec = _agent("nowhere-agent")
    rec["cwd"] = str(project_dir)
    make_transcript([enqueue("go"), rec])

    hygiene = check_agents(
        collect(tmp_path / "projects"),
        agents_root=_agents_dir(tmp_path, []),
        claudemd=_roster(tmp_path, []),
    )
    assert hygiene.used_but_missing == {"nowhere-agent"}


def test_frontmatter_name_wins_over_the_filename(tmp_path):
    """Shadowing matches on `name:`, so a file is dispatchable only under that."""
    root = tmp_path / "agents"
    root.mkdir(parents=True)
    (root / "some-filename.md").write_text(
        "---\nname: actual-dispatch-name\ndescription: x\n---\n", encoding="utf-8"
    )
    assert installed_agents(root) == {"actual-dispatch-name"}


def test_an_agent_without_frontmatter_falls_back_to_its_filename(tmp_path):
    root = tmp_path / "agents"
    root.mkdir(parents=True)
    (root / "bare-agent.md").write_text("no frontmatter here\n", encoding="utf-8")
    assert installed_agents(root) == {"bare-agent"}


def test_agents_visible_from_unions_project_and_global(tmp_path):
    project_dir = tmp_path / "repo"
    _agents_dir(project_dir / ".claude", ["local"])
    global_root = _agents_dir(tmp_path, ["shared"])
    assert agents_visible_from(str(project_dir), global_root) == {"local", "shared"}
    assert agents_visible_from("", global_root) == {"shared"}
