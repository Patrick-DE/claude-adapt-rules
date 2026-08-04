"""Command line entry point.

    python -m claude_adapt_rules.cli status              # what's in the transcripts
    python -m claude_adapt_rules.cli extract             # build corpus + bundles
    python -m claude_adapt_rules.cli queue --transcript  # SessionEnd hook target
    python -m claude_adapt_rules.cli ingest cands.json   # apply distilled candidates
    python -m claude_adapt_rules.cli adopt R-0001 --apply-global
    python -m claude_adapt_rules.cli rot                 # which rules aren't working
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import extract as extract_mod
from . import guards as guards_mod
from . import render as render_mod
from .ledger import Ledger, Rule
from .migrate import migrate_legacy_home
from .signals import score_session, select
from .transcripts import cutoff, iter_session_files, parse_all, projects_root


def _since(days: int | None) -> datetime | None:
    return cutoff(days) if days else None


def _print_stats(stats, title: str) -> None:
    print(f"{title}")
    print(f"  sessions parsed .............. {stats.sessions}")
    print(f"  projects ..................... {len(stats.projects)}")
    print(f"  raw type:user records ........ {stats.raw_user_records}")
    print(f"  queue enqueues (human submits)  {stats.queued_records}")
    print(f"  duplicates across channels ... {stats.duplicate_records}")
    print(f"  human prompts (noise removed)  {stats.prompts}")
    print(f"    of which acknowledgements .. {stats.acknowledgements}")
    print(f"  synthetic records dropped .... {stats.dropped_synthetic}")
    print(f"  malformed lines tolerated .... {stats.bad_lines}")
    print(f"  events selected as evidence .. {stats.selected}")
    if stats.by_signal:
        print("  signals:")
        for name, count in sorted(stats.by_signal.items(), key=lambda kv: -kv[1]):
            print(f"    {count:6d}  {name}")


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else projects_root()
    events, stats = extract_mod.collect(
        parse_all(root, _since(args.since)), min_score=args.min_score
    )
    _print_stats(stats, f"transcripts: {root}")
    if args.top:
        print(f"\n  top {args.top} events:")
        for event in events[: args.top]:
            text = " ".join(event.prompt.text.split())[:110]
            print(
                f"    [{event.score:3d}] {event.prompt.ts[:10]} "
                f"{event.prompt.project_name[:24]:24s} {text}"
            )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    result = extract_mod.run_extract(
        root=root,
        since=_since(args.since),
        out=Path(args.out) if args.out else None,
        min_score=args.min_score,
        max_events=args.max_events,
    )
    _print_stats(result.stats, "extraction complete")
    print(f"\n  corpus ....... {result.corpus}")
    print(f"  report ....... {result.report}")
    print(f"  bundles ...... {len(result.bundles)} in {result.bundles[0].parent if result.bundles else '-'}")
    for project, dropped in sorted(result.truncated.items()):
        print(f"    ! {project}: {dropped} lower-scoring events omitted (cap reached)")
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    """Hook target. Never fails loudly: a capture step must not break a session."""
    out = Path(args.out) if args.out else extract_mod.data_dir()
    try:
        transcript = Path(args.transcript)
        if not transcript.is_file():
            raise FileNotFoundError(transcript)
        written = extract_mod.queue_transcript(transcript, out=out)
        if not args.quiet:
            print(f"queued {written} event(s) from {transcript.name}")
    except Exception:  # noqa: BLE001 - deliberate: hooks must not raise
        try:
            out.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
            with (out / "hook.log").open("a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] queue failed for {args.transcript}\n")
                fh.write(traceback.format_exc())
        except OSError:
            pass
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    """Show queue events not yet distilled; optionally write them as a bundle."""
    out = Path(args.out) if args.out else None
    records = extract_mod.pending_events(out)
    total = len(extract_mod.load_queue(out))
    print(f"queued events ....... {total}")
    print(f"already distilled ... {total - len(records)}")
    print(f"pending ............. {len(records)}")
    if args.bundle:
        path = Path(args.bundle)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(extract_mod.render_pending_bundle(records), encoding="utf-8")
        print(f"bundle .............. {path}")
    for rec in records[: args.top]:
        text = " ".join(str(rec.get("text") or "").split())[:100]
        print(f"  [{rec.get('score'):>3}] {str(rec.get('ts'))[:10]} {text}")
    return 0


def cmd_consume(args: argparse.Namespace) -> int:
    """Mark pending queue events as distilled so they are not re-read."""
    out = Path(args.out) if args.out else None
    records = extract_mod.pending_events(out)
    if not records:
        print("nothing pending")
        return 0
    added = extract_mod.mark_consumed(records, out=out, note=args.note or "")
    print(f"marked {added} event(s) consumed; {len(records) - added} were already marked")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    candidates = payload.get("rules", payload) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        print("error: expected a JSON list of candidates, or {\"rules\": [...]}")
        return 2

    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    result = ledger.ingest(candidates)
    ledger.save()
    written = render_mod.write_tier_files(ledger)

    print(f"created ..... {len(result.created)}: {render_mod.summarize(result.created)}")
    print(f"merged ...... {len(result.merged)}")
    print(f"violations .. {len(result.violations)}: {render_mod.summarize(result.violations)}")
    for cand, why in result.rejected:
        print(f"  rejected: {why} :: {str(cand.get('rule'))[:70]}")
    for rule in result.created:
        print(f"  {rule.id} [{rule.scope}] {rule.rule[:80]}")
    # Similar-but-not-identical rules are where duplicates hide: below the merge
    # threshold nothing happens automatically, so surface them for a decision.
    for rule in result.created:
        for score, other in ledger.near_duplicates(rule)[:1]:
            print(
                f"  ? {rule.id} is {score:.0%} similar to {other.id} [{other.scope}] — "
                f"consider `merge {rule.id} {other.id}`"
            )
    print(f"\nwrote {len(written)} file(s); ledger: {ledger.path}")
    if result.violations:
        print("\nRules broken again after adoption — reword, hoist, or convert to a hook:")
        for rule in result.violations:
            print(f"  {rule.id} (x{rule.violation_count}) {rule.rule[:70]}")
    return 0


def cmd_reclassify(args: argparse.Namespace) -> int:
    """Apply judged generality to existing rules.

    Rules distilled before the `applies` field were scoped by evidence count alone, so
    a universal practice stated once stayed local. Pass judgements as ID=universal or
    ID=project; a universal claim naming something project-specific is still vetoed.
    """
    from .classify import resolve_applies
    from .ledger import decide_scope

    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    moves: list[tuple[Rule, str, str]] = []
    for token in args.judgements:
        rule_id, _, claimed = token.partition("=")
        rule = ledger.rules.get(rule_id)
        if rule is None:
            print(f"unknown id: {rule_id}")
            continue
        applies, veto = resolve_applies(rule.rule, claimed, ledger.project_names())
        if not applies:
            print(f"  {rule_id}: '{claimed}' is not universal|project — skipped")
            continue
        if veto:
            print(f"  {rule_id}: 'universal' vetoed — text names {veto}")
        new_scope = decide_scope(rule.evidence, fallback_project="", applies=applies)
        promoted = new_scope == "global" and rule.scope != new_scope
        if new_scope != rule.scope:
            moves.append((rule, rule.scope, new_scope))
        rule.applies = applies
        rule.scope = new_scope
        # A rule *promoted* out of repo scope loses its automatic adoption, because
        # global text needs an explicit yes. A rule that was already global and already
        # adopted keeps its adoption — it is in CLAUDE.md, and un-adopting it here would
        # leave the ledger disagreeing with the file.
        if promoted and rule.status == "adopted" and not args.keep_adopted:
            rule.status = "proposed"
            rule.adopted = ""

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to keep these moves:")
        for rule, old, new in moves:
            print(f"  {rule.id} {old} -> {new}  {rule.rule[:60]}")
        if not moves:
            print("  no scope changes")
        return 0

    ledger.save()
    render_mod.write_tier_files(ledger)
    print(f"\napplied {len(moves)} scope change(s):")
    for rule, old, new in moves:
        print(f"  {rule.id} {old} -> {new}")
    pending = [r for r in ledger.by_scope("global") if r.status == "proposed"]
    if pending:
        print(f"\n{len(pending)} global rule(s) now awaiting approval: "
              f"{render_mod.summarize(pending)}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Fold one rule's evidence into another and retire the duplicate."""
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    result = ledger.merge(args.source, args.target)
    if result is None:
        print(f"unknown or identical ids: {args.source}, {args.target}")
        return 2
    source, target = result
    ledger.save()
    render_mod.write_tier_files(ledger)
    print(f"{source.id} retired; its evidence moved to {target.id} [{target.scope}]")
    print(f"  {target.id} now cites {len(target.evidence)} quote(s) ({target.confidence})")
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    adopted = [r for rid in args.ids if (r := ledger.adopt(rid))]
    missing = set(args.ids) - {r.id for r in adopted}
    ledger.save()
    render_mod.write_tier_files(ledger)
    print(f"adopted: {render_mod.summarize(adopted)}")
    if missing:
        print(f"unknown ids: {', '.join(sorted(missing))}")

    if not args.apply_global:
        return 0

    block = render_mod.render_global_block(ledger)
    lines = render_mod.block_line_count(block)
    target = Path(args.claudemd) if args.claudemd else Path.home() / ".claude" / "CLAUDE.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if lines > render_mod.GLOBAL_BLOCK_MAX_LINES:
        print(
            f"refusing to write: global block is {lines} lines "
            f"(cap {render_mod.GLOBAL_BLOCK_MAX_LINES}). Retire rules or move them "
            f"to ~/.claude/memory/."
        )
        return 1
    if target.exists():
        backup = target.with_suffix(target.suffix + ".claude-adapt-rules.bak")
        shutil.copy2(target, backup)
        print(f"backup: {backup}")
    target.write_text(render_mod.splice_block(existing, block), encoding="utf-8")
    print(f"applied {lines}-line global block to {target}")
    return 0


def cmd_retire(args: argparse.Namespace) -> int:
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    retired = [r for rid in args.ids if (r := ledger.retire(rid))]
    ledger.save()
    render_mod.write_tier_files(ledger)
    print(f"retired: {render_mod.summarize(retired)}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    written = render_mod.write_tier_files(ledger)
    for path in written:
        print(path)
    return 0


def cmd_guards(args: argparse.Namespace) -> int:
    """List, attach or clear the mechanical checks behind enforceable rules."""
    ledger = Ledger(Path(args.ledger) if args.ledger else None)

    if args.clear:
        rule = ledger.rules.get(args.clear)
        if rule is None:
            print(f"unknown id: {args.clear}")
            return 2
        rule.guard = {}
        ledger.save()
        print(f"{rule.id}: guard cleared; the rule is prose again")
        return 0

    if args.set:
        rule = ledger.rules.get(args.set)
        if rule is None:
            print(f"unknown id: {args.set}")
            return 2
        if not args.pattern:
            print("--set needs --pattern")
            return 2
        rule.guard = {
            "tool": args.tool,
            "pattern": args.pattern,
            "message": args.message or rule.rule,
        }
        try:
            guards_mod.build_guard(rule)  # refuse to store what cannot compile
        except guards_mod.GuardError as exc:
            rule.guard = {}
            print(exc)
            return 2
        ledger.save()
        render_mod.write_tier_files(ledger)
        print(f"{rule.id}: guarded on {args.tool} /{args.pattern}/")
        if rule.status != "adopted":
            print(f"  note: status is {rule.status}; guards only fire once adopted")
        return 0

    active = guards_mod.active_guards(ledger)
    print(f"enforced by a hook ({len(active)}):")
    for guard in active:
        print(f"  {guard.rule_id} [{guard.tool}] /{guard.pattern.pattern}/")
    if not active:
        print("  none")

    pending = guards_mod.unguarded_enforceable(ledger)
    print(f"\nmechanically enforceable, still only prose ({len(pending)}):")
    for rule in pending:
        print(f"  {rule.id} [{rule.scope}] {rule.rule[:70]}")
    if not pending:
        print("  none")
    else:
        # `=` form, not a space: a pattern beginning with `-` is otherwise parsed
        # as an option, and the ones worth guarding usually are flags.
        print(
            "\nAttach one with:\n"
            "  claude-adapt-rules guards --set R-0024 --tool Bash "
            "--pattern=--no-verify --message='commit hooks are the gate'"
        )
    return 0


def cmd_rot(args: argparse.Namespace) -> int:
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    buckets = ledger.rot_report(quiet_days=args.quiet_days)
    print(f"still violated (last {args.quiet_days}d) — escalate:")
    for rule in buckets["escalate"] or []:
        print(f"  {rule.id} x{rule.violation_count} [{rule.scope}] {rule.rule[:70]}")
    if not buckets["escalate"]:
        print("  none")
    print(f"\nquiet for {args.quiet_days}d — retire candidates:")
    for rule in buckets["quiet"] or []:
        print(f"  {rule.id} [{rule.scope}] {rule.rule[:70]}")
    if not buckets["quiet"]:
        print("  none")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Fail if any rule cites a quote that is not verbatim in the cited session."""
    from . import archive as archive_mod
    from . import verify as verify_mod

    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    result = verify_mod.verify_ledger(
        ledger,
        root=Path(args.root) if args.root else None,
        exclude=args.exclude or (),
        archive=list(archive_mod.archived_files(Path(args.out) if args.out else None)),
    )
    print(f"evidence quotes checked ...... {result.checked}")
    print(f"verbatim in the cited session  {result.exact}")
    print(f"bad evidence ................ {len(result.failures)}")
    print(f"transcript deleted since .... {len(result.expired)}")
    for problem in result.failures:
        print(f"  {problem.rule_id} [{problem.session}] {problem.kind}: {problem.quote[:80]}")
    for problem in result.expired:
        print(f"  {problem.rule_id} [{problem.session}] transcript gone — archive earlier next time")
    return 0 if result.ok else 1


def cmd_archive(args: argparse.Namespace) -> int:
    """Copy transcripts that rules depend on out of the auto-cleanup path."""
    from . import archive as archive_mod

    out = Path(args.out) if args.out else None
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    sessions = None if args.all else archive_mod.cited_sessions(ledger)
    result = archive_mod.archive(
        sessions=sessions, root=Path(args.root) if args.root else None, out=out
    )
    scope = "all sessions" if args.all else f"{len(sessions or ())} cited session(s)"
    print(f"archiving {scope} -> {archive_mod.archive_dir(out)}")
    print(f"  copied ..... {result.copied}")
    print(f"  refreshed .. {result.refreshed}")
    print(f"  unchanged .. {result.skipped}")
    print(f"  bytes ...... {result.total_bytes:,}")
    if result.missing:
        print(
            f"  ! {len(result.missing)} cited session(s) already deleted and not archived: "
            f"{', '.join(result.missing)}"
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report whether the pipeline is actually working.

    Hooks fail open by design, so a broken capture is invisible: eight BOM failures
    sat unnoticed in hook.log. This is the command that surfaces them.
    """
    from . import archive as archive_mod
    from . import inject as inject_mod

    home = extract_mod.home_dir()
    data = extract_mod.data_dir()
    ledger = Ledger(Path(args.ledger) if args.ledger else None)
    problems: list[str] = []

    print(f"state home ................... {home}")
    print(f"  exists ..................... {home.is_dir()}")
    if not home.is_dir():
        problems.append("state directory missing; run `extract` once")

    rules = list(ledger.rules.values())
    adopted = [r for r in rules if r.status == "adopted"]
    proposed = [r for r in rules if r.status == "proposed"]
    repo_scopes = sorted({r.scope for r in rules if r.scope.startswith("repo:")})
    print(f"ledger ....................... {ledger.path}")
    print(f"  rules ...................... {len(rules)} ({len(adopted)} adopted, {len(proposed)} proposed)")
    print(f"  projects with repo rules ... {len(repo_scopes)}")
    if proposed_global := [r for r in proposed if r.scope == "global"]:
        print(f"  ! {len(proposed_global)} global rule(s) awaiting your approval")

    queue = extract_mod.load_queue()
    pending = extract_mod.pending_events()
    print(f"queue ........................ {extract_mod.queue_path()}")
    print(f"  captured ................... {len(queue)}")
    print(f"  pending distillation ....... {len(pending)}")

    log = data / "hook.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        failures = [line for line in lines if "failed" in line]
        # The log is append-only, so old entries are history, not open problems. Only
        # failures inside the window are actionable.
        window = (
            datetime.now(tz=timezone.utc) - timedelta(days=args.failure_days)
        ).isoformat(timespec="seconds")
        recent = [line for line in failures if line[1:20] >= window[:19]]
        print(f"hook failures logged ......... {len(failures)} ({len(recent)} in last {args.failure_days}d)")
        if failures:
            print(f"  last ....................... {failures[-1][:100]}")
        if args.reset_log:
            log.rename(log.with_suffix(".log.reviewed"))
            print(f"  log moved to ............... {log.with_suffix('.log.reviewed')}")
        elif recent:
            problems.append(
                f"{len(recent)} hook failure(s) in the last {args.failure_days} days: {log}"
            )
    else:
        print("hook failures logged ......... 0")

    archived = list(archive_mod.archived_files())
    size = sum(p.stat().st_size for p in archived) if archived else 0
    print(f"archive ...................... {len(archived)} session(s), {size / 1_048_576:.0f} MB")

    live = list(iter_session_files())
    if live:
        now = datetime.now(tz=timezone.utc).timestamp()
        oldest = min(p.stat().st_mtime for p in live)
        print(f"oldest live transcript ....... {(now - oldest) / 86400:.0f} days")
        archived_ids = {p.stem[:8] for p in archived}
        unarchived = [p for p in live if p.stem[:8] not in archived_ids]
        # A fresh session being unarchived is normal: `archive` copies cited sessions,
        # and a session is only cited once it has been extracted. It becomes a problem
        # as it approaches the cleanup age, because then it is about to be deleted.
        at_risk = [
            p for p in unarchived if (now - p.stat().st_mtime) / 86400 >= args.at_risk_days
        ]
        print(f"  unarchived ................. {len(unarchived)} ({len(at_risk)} near cleanup age)")
        if at_risk:
            problems.append(
                f"{len(at_risk)} transcript(s) older than {args.at_risk_days}d are unarchived "
                f"and will be deleted; run `archive --all`"
            )

    # Does the current project actually receive its rules?
    cwd = Path(args.cwd) if args.cwd else Path.cwd()
    injection = inject_mod.build(str(cwd), ledger)
    project = inject_mod.project_name_from_cwd(str(cwd))
    print(f"context for '{project}' ....... ", end="")
    print(f"{len(injection.rules)} rule(s), {len(injection.text)} chars" if injection else "none")

    print()
    if problems:
        print("problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("no problems found")
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    """Score a single transcript and print it, for debugging the detectors."""
    from .transcripts import parse_session

    session = parse_session(Path(args.transcript))
    events = select(score_session(session.prompts), min_score=args.min_score)
    print(f"{session.project_name} · {session.session}")
    print(f"  prompts: {len(session.prompts)}  selected: {len(events)}  bad lines: {session.bad_lines}")
    for event in events:
        text = " ".join(event.prompt.text.split())[:120]
        print(f"  [{event.score:3d}] {','.join(event.signals):40s} {text}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-adapt-rules", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", help="transcript root (default ~/.claude/projects)")
        p.add_argument("--since", type=int, metavar="DAYS", help="only sessions touched in the last N days")
        p.add_argument("--min-score", type=int, default=3)

    p_status = sub.add_parser("status", help="parse and report, write nothing")
    common(p_status)
    p_status.add_argument("--top", type=int, default=10)
    p_status.set_defaults(func=cmd_status)

    # No --since here on purpose: extract rewrites the corpus in place, so a windowed
    # run replaces complete history with a slice. Use `pending` for incremental work.
    p_extract = sub.add_parser("extract", help="write corpus + per-project bundles")
    p_extract.add_argument("--root", help="transcript root (default ~/.claude/projects)")
    p_extract.add_argument("--min-score", type=int, default=3)
    p_extract.add_argument("--out", help="data dir (default ~/.claude-adapt-rules/data)")
    p_extract.add_argument("--max-events", type=int, default=extract_mod.MAX_EVENTS_PER_PROJECT)
    p_extract.set_defaults(func=cmd_extract, since=None)

    p_queue = sub.add_parser("queue", help="append one session's events to the queue")
    p_queue.add_argument("--transcript", required=True)
    p_queue.add_argument("--out")
    p_queue.add_argument("--quiet", action="store_true")
    p_queue.set_defaults(func=cmd_queue)

    p_pending = sub.add_parser("pending", help="queue events not yet distilled")
    p_pending.add_argument("--out")
    p_pending.add_argument("--bundle", help="write the pending events as a markdown bundle")
    p_pending.add_argument("--top", type=int, default=10)
    p_pending.set_defaults(func=cmd_pending)

    p_consume = sub.add_parser("consume", help="mark pending queue events as distilled")
    p_consume.add_argument("--out")
    p_consume.add_argument("--note", help="what consumed them, e.g. a candidates filename")
    p_consume.set_defaults(func=cmd_consume)

    p_ingest = sub.add_parser("ingest", help="apply distilled rule candidates")
    p_ingest.add_argument("file")
    p_ingest.add_argument("--ledger")
    p_ingest.set_defaults(func=cmd_ingest)

    p_reclassify = sub.add_parser(
        "reclassify", help="judge existing rules as universal or project-specific"
    )
    p_reclassify.add_argument("judgements", nargs="+", metavar="ID=universal|project")
    p_reclassify.add_argument("--ledger")
    p_reclassify.add_argument("--apply", action="store_true", help="write the changes")
    p_reclassify.add_argument(
        "--keep-adopted",
        action="store_true",
        help="do not reset a promoted rule to proposed (it is already in CLAUDE.md)",
    )
    p_reclassify.set_defaults(func=cmd_reclassify)

    p_merge = sub.add_parser("merge", help="fold a duplicate rule into another")
    p_merge.add_argument("source", help="rule to retire")
    p_merge.add_argument("target", help="rule that keeps the evidence")
    p_merge.add_argument("--ledger")
    p_merge.set_defaults(func=cmd_merge)

    p_adopt = sub.add_parser("adopt", help="mark rules adopted")
    p_adopt.add_argument("ids", nargs="+")
    p_adopt.add_argument("--ledger")
    p_adopt.add_argument("--apply-global", action="store_true", help="splice into ~/.claude/CLAUDE.md")
    p_adopt.add_argument("--claudemd", help="override target CLAUDE.md")
    p_adopt.set_defaults(func=cmd_adopt)

    p_retire = sub.add_parser("retire", help="mark rules retired")
    p_retire.add_argument("ids", nargs="+")
    p_retire.add_argument("--ledger")
    p_retire.set_defaults(func=cmd_retire)

    p_render = sub.add_parser("render", help="rewrite rule files from the ledger")
    p_render.add_argument("--ledger")
    p_render.set_defaults(func=cmd_render)

    p_guards = sub.add_parser(
        "guards", help="rules enforced by a hook, and which ones still could be"
    )
    p_guards.add_argument("--ledger")
    p_guards.add_argument("--set", metavar="RULE_ID", help="attach a guard to this rule")
    p_guards.add_argument("--tool", default="*", help="tool name to gate, or * for any")
    p_guards.add_argument("--pattern", help="regex; a match refuses the call")
    p_guards.add_argument("--message", default="", help="reason shown when it fires")
    p_guards.add_argument("--clear", metavar="RULE_ID", help="remove a rule's guard")
    p_guards.set_defaults(func=cmd_guards)

    p_rot = sub.add_parser("rot", help="which adopted rules are working")
    p_rot.add_argument("--ledger")
    p_rot.add_argument("--quiet-days", type=int, default=30)
    p_rot.set_defaults(func=cmd_rot)

    p_archive = sub.add_parser(
        "archive", help="copy cited transcripts out of the 30-day cleanup path"
    )
    p_archive.add_argument("--ledger")
    p_archive.add_argument("--root")
    p_archive.add_argument("--out")
    p_archive.add_argument("--all", action="store_true", help="archive every session, not just cited ones")
    p_archive.set_defaults(func=cmd_archive)

    p_verify = sub.add_parser("verify", help="check every rule's evidence is verbatim")
    p_verify.add_argument("--ledger")
    p_verify.add_argument("--root")
    p_verify.add_argument("--out")
    p_verify.add_argument(
        "--exclude",
        nargs="*",
        help="session ids to ignore (e.g. the session that wrote the rules)",
    )
    p_verify.set_defaults(func=cmd_verify)

    p_doctor = sub.add_parser("doctor", help="is the pipeline actually working?")
    p_doctor.add_argument("--ledger")
    p_doctor.add_argument("--cwd", help="project to check rule delivery for (default: current)")
    p_doctor.add_argument("--failure-days", type=int, default=7)
    p_doctor.add_argument(
        "--at-risk-days",
        type=int,
        default=21,
        help="unarchived transcripts this old are treated as about to be deleted",
    )
    p_doctor.add_argument(
        "--reset-log", action="store_true", help="set hook.log aside once reviewed"
    )
    p_doctor.set_defaults(func=cmd_doctor)

    p_session = sub.add_parser("session", help="debug the detectors on one transcript")
    p_session.add_argument("transcript")
    p_session.add_argument("--min-score", type=int, default=3)
    p_session.set_defaults(func=cmd_session)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Before anything constructs a Ledger: a rename left earlier state under the
    # old root, and starting from an empty ledger would restart rule ids at
    # R-0001 against a CLAUDE.md that already cites them.
    for note in migrate_legacy_home():
        print(f"migrated {note}")
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
