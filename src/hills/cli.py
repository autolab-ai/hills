"""The hills command line. Unitary, git-style, fully local and offline."""

import argparse
import sys
from pathlib import Path

from hills import (
    __version__,
    check as check_mod,
    locks,
    paths,
    registry,
    report as report_mod,
    runner,
    scaffold,
    setup_cmd,
    state,
)
from hills.canonical import dumps
from hills.errors import HillsError
from hills.hill import README_NAME, Hill


def out(message: str = "") -> None:
    print(message, file=sys.stderr)


def _short(value: str | None, width: int = 8) -> str:
    return value[:width] if value else "-"


def _parse_param(pair: str) -> tuple[str, str]:
    if "=" not in pair:
        raise HillsError(f"-p expects key=value, got {pair!r}")
    key, value = pair.split("=", 1)
    return key.strip(), value


def _params(pairs: list[str]) -> dict:
    return dict(_parse_param(pair) for pair in pairs)


def _format_metrics(metrics: list[dict]) -> str:
    return "  ".join(
        f"{metric['name']}={metric['value']:.6g} ({metric['direction']})" for metric in metrics
    )


def _format_config(config: list[dict]) -> str:
    return "  ".join(
        f"{entry['name']}={entry['value']}" + ("*" if entry["primary"] else "")
        for entry in config
    )


# -- commands ---------------------------------------------------------------


def cmd_new(args) -> int:
    hill = scaffold.new(args.name, template=args.template)
    out(f"created {hill.root}")
    out(f"  template   {args.template}")
    out(f"  version control  {hill.root / '.vc'} (empty; nothing committed yet)")
    out("")
    out("Next: fill in README.md, eval.py and hill.yaml, then")
    out(f"  hills check {hill.name}")
    out(f"  hills commit {hill.name} -m \"initial\"")
    return 0


def cmd_check(args) -> int:
    hill = Hill.resolve(args.name)
    result = check_mod.check(hill, run_tests=not args.no_tests)
    if args.json:
        print(
            dumps(
                {
                    "hill": hill.name,
                    "ok": result.ok,
                    "steps": [
                        {"name": name, "ok": ok, "detail": detail}
                        for name, ok, detail in result.steps
                    ],
                }
            )
        )
    else:
        for name, ok, detail in result.steps:
            out(f"  {'ok  ' if ok else 'FAIL'}  {name:<20} {detail}")
        out("")
        out(f"{hill.name}: {'all checks passed' if result.ok else 'check failed'}")
    return 0 if result.ok else 1


def cmd_status(args) -> int:
    hill = Hill.resolve(args.name)
    hill.require_vc()
    hill.refresh_exclude()
    committed = hill.vc.has_commits
    changes = hill.vc.status_porcelain()
    drift = hill.lock_drift()

    if args.json:
        print(
            dumps(
                {
                    "hill": hill.name,
                    "path": str(hill.root),
                    "tree_hash": hill.vc.tree_hash() if committed else None,
                    "commit": hill.vc.commit_hash() if committed else None,
                    "clean": not (changes or drift),
                    "changes": changes,
                    "lock_drift": drift,
                }
            )
        )
        return 0

    if not committed:
        out(f"{hill.name}: no commits yet ({hill.root})")
    else:
        out(f"{hill.name} @ {hill.vc.tree_hash()}  (commit {_short(hill.vc.commit_hash(), 10)})")
    if not changes and not drift:
        out("working tree clean")
        return 0
    if changes:
        out("")
        out("tracked changes:")
        for line in changes:
            out(f"  {line}")
    if drift:
        out("")
        out("lock-tracked content changed (git cannot see these; commit to re-lock):")
        for line in drift:
            out(f"  {line}")
    return 0


def cmd_commit(args) -> int:
    hill = Hill.resolve(args.name)
    hill.require_vc()
    result = check_mod.check(hill, run_tests=not args.no_tests)
    for name, ok, detail in result.steps:
        out(f"  {'ok  ' if ok else 'FAIL'}  {name:<20} {detail}")
    if not result.ok:
        out("")
        raise HillsError("check failed; nothing was committed")

    private_lock, blobs_lock = locks.write(hill.root, hill.manifest)
    hill.refresh_exclude()
    excluded = [locks.PRIVATE_DIR, *blobs_lock.paths]
    tree_hash = hill.vc.commit(args.message, excluded)
    registry.set_tree_hash(hill.name, tree_hash)

    out("")
    out(f"  private.lock  {len(private_lock.entries)} file(s), {private_lock.total_size:,} bytes")
    out(f"  blobs.lock    {len(blobs_lock.entries)} file(s), {blobs_lock.total_size:,} bytes")
    out("")
    out(f"committed {hill.name} {hill.manifest.version}")
    out(f"  tree hash  {tree_hash}")
    out(f"  commit     {hill.vc.commit_hash()}")
    out("")
    out("Scores from here on are tied to this tree hash. A new commit starts a fresh history.")
    return 0


def cmd_log(args) -> int:
    hill = Hill.resolve(args.name)
    hill.require_commits()
    entries = hill.vc.log(args.number)
    if args.json:
        print(dumps(entries))
        return 0
    for entry in entries:
        attempts = state.read(hill.name, entry["tree_hash"])
        out(f"{entry['tree_hash'][:12]}  {entry['date'][:19]}  {entry['message']}")
        out(f"    commit {entry['short']}   {len(attempts)} eval(s) recorded")
    return 0


def cmd_describe(args) -> int:
    hill = Hill.resolve(args.name)
    committed = hill.vc.has_commits
    readme = (
        hill.vc.show(f"HEAD:{README_NAME}")
        if committed
        else (hill.root / README_NAME).read_text()
    )
    payload = {
        "hill": hill.name,
        "version": hill.manifest.version,
        "path": str(hill.root),
        "tree_hash": hill.vc.tree_hash() if committed else None,
        "commit": hill.vc.commit_hash() if committed else None,
        "committed": committed,
        "watchdog_timeout_s": hill.manifest.watchdog_timeout_s,
        "exclusive_device": hill.manifest.exclusive,
        "params": {name: spec.as_json() for name, spec in hill.manifest.params.items()},
        "submission": "a directory; see readme for its required contents",
        "test_mode": "hills eval <dir> -H {} --final".format(hill.name),
        "files": hill.vc.ls_tree() if committed else [],
        "readme": readme,
    }
    print(dumps(payload))
    return 0


def cmd_eval(args) -> int:
    hill = Hill.resolve(args.hill)
    outcome = runner.evaluate(
        hill,
        Path(args.submission),
        param_overrides=_params(args.param),
        final=args.final,
        force=args.force,
        current=args.current,
        queue=args.queue,
        stream=args.verbose,
    )
    report = outcome.report

    out("")
    out(f"{hill.name} @ {_short(report['tree_hash'], 12) if report['tree_hash'] else 'WORKING TREE'}")
    out(f"  submission   {args.submission}")
    out(f"  hash         {report['submission_hash'][:19]}…  {report['submission_git'] or ''}")
    if report["params"]:
        out("  params       " + "  ".join(f"{k}={v}" for k, v in sorted(report["params"].items())))
    out(f"  {'PASSED' if report['passed'] else 'FAILED'}       {_format_metrics(report['metrics'])}")
    if report["config"]:
        out(f"  config       {_format_config(report['config'])}   (* = primary)")
    if not report["official"]:
        out(f"  unofficial   {report['official_reason']}")
    out(f"  report       {outcome.report_path}")
    out("")

    print(dumps(report))
    if args.out:
        Path(args.out).write_text(dumps(report) + "\n")
        out(f"wrote {args.out}")
    return 0


def cmd_attempts(args) -> int:
    hill = Hill.resolve(args.name)
    committed = hill.vc.has_commits
    tree_hash = hill.vc.tree_hash() if committed else None
    records = state.read(hill.name, tree_hash)
    dirty_records = state.read(hill.name, None) if committed else []

    if args.json:
        print(dumps({"hill": hill.name, "tree_hash": tree_hash, "attempts": records}))
        return 0

    out(f"{hill.name} @ {tree_hash or 'uncommitted'}   {len(records)} attempt(s)")
    if not records:
        out("no evals recorded for this version yet")
    else:
        out("")
        out(f"  {'#':>3}  {'when':<20} {'submission':<34} {'result'}")
        for record in records:
            when = record["timestamp"].replace("T", " ").rstrip("Z")
            label = record.get("submission_git") or record["submission_hash"][7:19]
            if record.get("error"):
                verdict = "ERROR  " + record["error"].splitlines()[0][:60]
            elif record["passed"]:
                verdict = _format_metrics(record["metrics"])
            else:
                verdict = "did not pass"
            flags = "".join(
                [" [final]" if record.get("final") else "", "" if record.get("official") else " [unofficial]"]
            )
            marker = " " if record["_chain_ok"] else "!"
            out(f"{marker} {record['seq']:>3}  {when:<20} {label:<34} {verdict}{flags}")

        broken = [record["seq"] for record in records if not record["_chain_ok"]]
        if broken:
            out("")
            out(f"! chain broken at attempt(s) {broken}: this log was edited or truncated.")

        groups = report_mod.rank([r for r in records if r["passed"]])
        if groups:
            out("")
            out("best per comparable configuration:")
            for key, group in sorted(groups.items(), key=lambda item: str(item[0])):
                best = group[0]
                out(f"  {report_mod.comparability_label(key)}")
                out(f"    {_format_metrics(best['metrics'])}   {best.get('submission_git') or best['submission_hash'][7:19]}")

    if dirty_records:
        out("")
        out(f"{len(dirty_records)} unofficial --current attempt(s) recorded separately "
            f"({state.attempts_path(hill.name, None)})")
    return 0


def cmd_verify(args) -> int:
    report = report_mod.read(Path(args.report))
    valid = report_mod.verify(report)
    if args.json:
        print(dumps({"report": args.report, "valid": valid}))
    elif valid:
        out(f"signature valid: {report['hill']} @ {_short(report.get('tree_hash'), 12)}")
        out(f"  {'PASSED' if report['passed'] else 'FAILED'}  {_format_metrics(report['metrics'])}")
        out(f"  signed {report['timestamp']} by hills {report['tool']['version']}")
    else:
        out("signature INVALID: this report was edited, or it was signed on another machine.")
    return 0 if valid else 1


def cmd_list(args) -> int:
    entries = registry.entries()
    rows = []
    for name, entry in sorted(entries.items()):
        root = Path(entry["path"]) if entry.get("path") else None
        rows.append(
            {
                "name": name,
                "path": str(root) if root else None,
                "tree_hash": entry.get("tree_hash"),
                "present": bool(root and root.is_dir()),
            }
        )
    if args.json:
        print(dumps(rows))
        return 0
    if not rows:
        out("no hills registered. Create one with: hills new <name>")
        return 0
    for row in rows:
        status = "" if row["present"] else "  (missing)"
        out(f"{row['name']:<24} {_short(row['tree_hash'], 12):<14} {row['path']}{status}")
    return 0


def cmd_examples(args) -> int:
    summaries = scaffold.template_summaries()
    if args.json:
        print(dumps([{"name": name, "summary": summary} for name, summary in summaries]))
        return 0
    out("Example hills bundled with the tool. Start from one with:")
    out("  hills new <your-name> -t <example>")
    out("")
    for name, summary in summaries:
        out(f"  {name}")
        out(f"      {summary}")
    return 0


def cmd_setup(args) -> int:
    available = setup_cmd.harnesses()
    if args.list:
        for harness in available:
            mark = "detected" if harness.marker.is_dir() else "not found"
            out(f"  {harness.name:<14} {mark:<10} {harness.skills_dir}")
        return 0

    if args.harness:
        chosen = [h for h in available if h.name == args.harness]
        if not chosen:
            raise HillsError(
                f"unknown harness {args.harness!r}. Known: {', '.join(h.name for h in available)}"
            )
    else:
        chosen = setup_cmd.detected()

    if not chosen:
        out("no agent harness detected. Pass --harness <name>, or see --list.")
        return 1

    for name, destination in setup_cmd.install(chosen):
        out(f"installed the hills skill for {name}: {destination}")
    return 0


def cmd_home(args) -> int:
    root = paths.home()
    out(f"{root}")
    out(f"  registry   {paths.registry_path()}")
    out(f"  key        {paths.key_path()} ({'present' if report_mod.key_exists() else 'not created yet'})")
    out(f"  state      {paths.state_root()}")
    out(f"  runs       {paths.runs_root()}")
    out(f"  envs       {paths.envs_root()}")
    return 0


# -- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hills",
        description="Verification environments for AI research agents.",
    )
    parser.add_argument("--version", action="version", version=f"hills {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text, description=help_text)
        child.add_argument("--json", action="store_true", help="machine-readable output")
        return child

    new = add("new", "scaffold a hill in .hills/<name>, init its version control, register it")
    new.add_argument("name")
    new.add_argument(
        "-t",
        "--template",
        default=scaffold.DEFAULT_TEMPLATE,
        choices=scaffold.available_templates(),
        metavar="EXAMPLE",
        help="start from an example bundled with the tool, by name; "
        "run `hills examples` to see them (default: %(default)s)",
    )
    new.set_defaults(func=cmd_new)

    check = add("check", "validate the manifest and evaluator contract, and run tests/")
    check.add_argument("name")
    check.add_argument("--no-tests", action="store_true", help="skip tests/")
    check.set_defaults(func=cmd_check)

    status = add("status", "working-tree changes since the last commit")
    status.add_argument("name")
    status.set_defaults(func=cmd_status)

    commit = add("commit", "check, regenerate locks, and freeze this version of the hill")
    commit.add_argument("name")
    commit.add_argument("-m", "--message", required=True)
    commit.add_argument("--no-tests", action="store_true", help="skip tests/ in the check gate")
    commit.set_defaults(func=cmd_commit)

    log = add("log", "version history of the hill")
    log.add_argument("name")
    log.add_argument("-n", "--number", type=int, default=20)
    log.set_defaults(func=cmd_log)

    describe = add("describe", "README, params and submission contract, as JSON")
    describe.add_argument("name")
    describe.set_defaults(func=cmd_describe)

    evaluate = add("eval", "score a submission directory against a committed hill")
    evaluate.add_argument("submission", help="the submission directory")
    evaluate.add_argument("-H", "--hill", required=True)
    evaluate.add_argument(
        "-p", "--param", action="append", default=[], metavar="KEY=VALUE",
        help="override a manifest param",
    )
    evaluate.add_argument("--final", action="store_true", help="score against the held-out test split")
    mode = evaluate.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true", help="evaluate HEAD even though the hill is dirty")
    mode.add_argument("--current", action="store_true", help="evaluate the working tree; report is unofficial")
    evaluate.add_argument("--queue", action="store_true", help="wait for a busy device instead of failing")
    evaluate.add_argument("-v", "--verbose", action="store_true", help="stream evaluator output")
    evaluate.add_argument("-o", "--out", help="also write the report to this path")
    evaluate.set_defaults(func=cmd_eval)

    attempts = add("attempts", "eval history for the current version of a hill")
    attempts.add_argument("name")
    attempts.set_defaults(func=cmd_attempts)

    verify = add("verify", "check a report's signature")
    verify.add_argument("report")
    verify.set_defaults(func=cmd_verify)

    listing = add("list", "registered hills")
    listing.set_defaults(func=cmd_list)

    examples = add("examples", "example hills bundled with the tool, usable with `hills new -t`")
    examples.set_defaults(func=cmd_examples)

    setup = add("setup", "install the agent skill into detected harnesses")
    setup.add_argument("--harness", help="install for one named harness")
    setup.add_argument("--list", action="store_true", help="show harnesses and where the skill goes")
    setup.set_defaults(func=cmd_setup)

    home = add("home", "where machine state lives")
    home.set_defaults(func=cmd_home)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HillsError as error:
        print(f"hills: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("hills: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
