#!/usr/bin/env python3
"""Run context tools; TypeSafe requires --allow-remote. Gate executes the supplied command."""

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from context_economy import memory, output, packing, reporting, typesafe
from context_economy.common import Store, encode, read_source


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--project", type=Path, default=Path.cwd())
    command.add_argument("--state-dir", type=Path)
    commands = command.add_subparsers(dest="command", required=True)

    add = commands.add_parser("remember", help="Store a verified note with evidence")
    add.add_argument("--text", required=True)
    add.add_argument("--evidence", required=True)
    add.add_argument("--source", action="append", default=[])
    add.add_argument("--ttl-days", type=float, default=30)

    search = commands.add_parser("recall", help="Retrieve current notes; optional TypeSafe ranking")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--preview-remote", action="store_true", help="Print exactly the candidate request without sending it")

    inspect = commands.add_parser("inspect", help="Inspect a note including staleness reasons")
    inspect.add_argument("id")

    pack = commands.add_parser("pack", help="Build a bounded context packet from an explicit task")
    pack.add_argument("--task", required=True, help="Project-relative UTF-8 JSON with goal, criteria, constraints")
    pack.add_argument("--source", action="append", default=[], help="Optional PATH or PATH:START:END")
    pack.add_argument("--required", action="append", default=[], help="Mandatory instruction/evidence file; never truncated")
    pack.add_argument("--query", help="Optional memory query; no memory retrieval unless set")
    pack.add_argument("--budget", type=int, default=12000)
    pack.add_argument("--check-budget", action="store_true", help="Also run existing context-budget on the final packet")

    for sub in (search, pack):
        sub.add_argument("--typesafe", choices=("off", "shadow", "active"), default="off")
        sub.add_argument("--allow-remote", action="store_true")
        sub.add_argument("--typesafe-model", default="jev-latest")
        sub.add_argument("--daily-calls", type=int, default=10)
        sub.add_argument("--confidence", type=float, default=0.8)
        sub.add_argument("--api-timeout", type=float, default=10)

    gate = commands.add_parser("gate", help="Run an explicit command; archive exact output and return its exit code")
    gate.add_argument("--timeout", type=float, default=120)
    gate.add_argument("--preview-chars", type=int, default=4000)
    gate.add_argument("argv", nargs=argparse.REMAINDER)

    record = commands.add_parser("record", help="Record measured usage for one attempt; absent fields stay unknown")
    record.add_argument("--file", required=True, help="Project-relative measurement JSON")
    report = commands.add_parser("report", help="Group measured attempts by dataset, variant and model settings")
    report.add_argument("--end-to-end", action="store_true", help="Include preparation across all models per dataset/variant")
    return command


def ranking(args, store, query, notes):
    return typesafe.rerank(store, query, notes, mode=args.typesafe,
                           allow_remote=args.allow_remote, model=args.typesafe_model,
                           daily_calls=args.daily_calls, timeout=args.api_timeout,
                           confidence=args.confidence)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        with Store(args.project, args.state_dir) as store:
            if args.command == "remember":
                result = {"id": memory.add(store, args.text, args.evidence, args.source, args.ttl_days)}
            elif args.command == "inspect":
                result = memory.inspect(store, args.id)
            elif args.command == "recall":
                notes = memory.search(store, args.query, args.limit)
                result = (typesafe.payload_for(args.query, notes, args.typesafe_model)
                          if args.preview_remote else ranking(args, store, args.query, notes))
            elif args.command == "pack":
                task = json.loads(read_source(store.root, args.task)["text"])
                notes = memory.search(store, args.query) if args.query else []
                ranked = ranking(args, store, args.query or task.get("goal", ""), notes)
                result = packing.build(store.root, task, args.source, args.required, ranked["notes"], args.budget)
                if args.check_budget:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md") as bundle:
                        bundle.write(result["text"])
                        bundle.flush()
                        checked = subprocess.run([str(Path(__file__).parent / "bin/context-budget"),
                                                  "--limit", str(args.budget), bundle.name],
                                                 capture_output=True, text=True, timeout=30)
                    if checked.returncode:
                        raise ValueError("context-budget did not pass; packet not emitted. "
                                         + checked.stderr[:1000])
                    result["external_budget_check"] = "passed"
                # Packet goes to stdout for redirection; diagnostic metadata stays on stderr.
                text = result.pop("text")
                result["typesafe"] = {k: v for k, v in ranked.items() if k != "notes"}
                print(encode(result), file=sys.stderr)
                print(text, end="")
                return 0
            elif args.command == "gate":
                command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
                result = output.run(store, command, args.timeout, args.preview_chars)
                print(encode(result))
                return result["exit_code"]
            elif args.command == "record":
                reporting.record(store, json.loads(read_source(store.root, args.file)["text"]))
                result = {"recorded": True}
            else:
                result = {"groups": reporting.summary(store, args.end_to_end), "comparison_notice":
                          "Compare matching task sets and settings. Missing values are unknown. "
                          "Token measurements do not predict subscription quota savings."}
            print(encode(result))
            return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        print(f"context-economy: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
