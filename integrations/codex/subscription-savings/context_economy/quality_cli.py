"""Shared public command contracts for context economy and project quality guards."""

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

from . import design, quality_checks, quality_policy, retrieval
from .common import Store, encode, read_source
from .quality_common import cache_stats, load_config, load_profile

COMMANDS = {"repo-map", "index-update", "source-read", "retrieve", "retrieval-eval", "symbols", "callers", "tests", "search", "context-build", "verify-context",
            "cache-stats",
            "queue-submit", "queue-status", "queue-cancel", "queue-worker", "relations",
            "quality-plan", "quality-verify", "guard-context", "design-check", "design-context",
            "performance-check", "docs", "reference-search", "semantic-search", "rerank", "asset-prepare", "svg-normalize"}


def selected(parser):
    parser.add_argument("--source", action="append", required=True, help="Explicit project-relative source/test path")


def add_parsers(commands):
    commands.add_parser("cache-stats", help="Aggregate local quality cache hits, misses and evictions")
    evaluation = commands.add_parser("retrieval-eval", help="Evaluate labeled real-project code search")
    evaluation.add_argument("--suite", choices=("hearthpulse", "hs-manacost"), required=True)
    evaluation.add_argument("--semantic", action="store_true", help="Opt in to native OpenRouter embedding and rerank")
    evaluation.add_argument("--limit", type=int, default=3)
    relations = commands.add_parser("relations", help="Compiler-resolved selected TypeScript bindings; explicit AST fallback")
    selected(relations)
    relations.add_argument("symbol")
    relations.add_argument("--direction", choices=("callers", "callees"), default="callers")
    relations.add_argument("--limit", type=int, default=10)
    relations.add_argument("--config", default="tsconfig.json")
    relations.add_argument("--definition-path")
    submit = commands.add_parser("queue-submit", help="Queue bounded selected-source quality argv from JSON")
    submit.add_argument("payload")
    submit.add_argument("--timeout", type=int, default=120)
    status = commands.add_parser("queue-status", help="Read this project's bounded queue status")
    status.add_argument("--id")
    cancel = commands.add_parser("queue-cancel", help="Cancel a queued or running project job")
    cancel.add_argument("id")
    worker = commands.add_parser("queue-worker", help="Run a bounded foreground worker; never retry interrupted API calls")
    worker.add_argument("--max-jobs", type=int, default=1)
    worker.add_argument("--idle-timeout", type=int, default=0)
    update = commands.add_parser("index-update", help="Incrementally update only selected source")
    selected(update)
    source = commands.add_parser("source-read", help="Read exact code with stale-hash protection")
    source.add_argument("source")
    source.add_argument("--sha256", required=True)
    flow = commands.add_parser("retrieve", help="Local-first code retrieval with explicit semantic fallback")
    flow.add_argument("query")
    selected(flow)
    flow.add_argument("--symbol")
    flow.add_argument("--limit", type=int, default=3)
    flow.add_argument("--config", default=".ai/manacost-quality.json")
    flow.add_argument("--semantic-fallback", action="store_true")
    flow.add_argument("--allow-remote", action="store_true")
    flow.add_argument("--preview-remote", action="store_true")
    flow.add_argument("--evidence-gap", default="")
    for mode in ("symbols", "callers", "tests"):
        command = commands.add_parser(mode, help="Bounded AST symbol/reference/test candidates")
        command.add_argument("symbol")
        selected(command)
        command.add_argument("--limit", type=int, default=8)
    index = commands.add_parser("repo-map", help="Incremental AST map of selected source paths")
    selected(index)
    index.add_argument("--budget", type=int, default=3000)
    search = commands.add_parser("search", help="Bounded local BM25 lexical retrieval")
    selected(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    build = commands.add_parser("context-build", help="Build a verifiable source/test context packet")
    selected(build)
    build.add_argument("--task", required=True)
    build.add_argument("--required", action="append", default=[])
    build.add_argument("--symbol")
    build.add_argument("--budget", type=int, default=8000)
    verify = commands.add_parser("verify-context", help="Verify exact source hashes/text and packet budget")
    verify.add_argument("packet")
    verify.add_argument("--budget", type=int, default=12000)
    route = commands.add_parser("guard-context", help="Select at most three task-specific instruction modules")
    route.add_argument("--changed", action="append", required=True)
    route.add_argument("--task-type", default="implementation")
    route.add_argument("--risk", default="low", choices=quality_policy.RISKS)
    route.add_argument("--stack", choices=("nextjs", "go", "wordpress"))
    for name in ("quality-plan", "quality-verify"):
        gate = commands.add_parser(name, help="Plan or execute the project's explicit quality contract")
        gate.add_argument("--config", default=".ai/manacost-quality.json")
        gate.add_argument("--profile", choices=("hearthpulse", "hs-manacost", "nextjs", "go", "wordpress"))
        gate.add_argument("--changed", action="append", required=True)
        gate.add_argument("--risk", default="low", choices=quality_policy.RISKS)
        gate.add_argument("--task-type", default="implementation")
        gate.add_argument("--family", choices=("engineering", "design"))
        gate.add_argument("--allow-heavy", action="store_true")
        gate.add_argument("--allow-network", action="store_true")
        gate.add_argument("--only", action="append")
    check = commands.add_parser("design-check", help="Validate project tokens, CSS, SVG or registry")
    check.add_argument("kind", choices=("tokens", "css", "svg", "components"))
    check.add_argument("--config", default=".ai/manacost-quality.json")
    check.add_argument("--profile", choices=("hearthpulse", "hs-manacost"))
    check.add_argument("--source", action="append", default=[])
    context = commands.add_parser("design-context", help="Retrieve matching registered components and their tokens")
    context.add_argument("query")
    context.add_argument("--config", default=".ai/manacost-quality.json")
    context.add_argument("--profile", choices=("hearthpulse", "hs-manacost"))
    context.add_argument("--limit", type=int, default=3)
    performance = commands.add_parser("performance-check", help="Compare measured metrics to project budgets")
    for flag in ("current", "baseline", "budgets"):
        performance.add_argument("--" + flag, required=True)
    # Optional providers are imported only when explicitly requested.
    for name in ("docs", "reference-search", "semantic-search", "rerank"):
        provider = commands.add_parser(name, help="Explicit bounded external or semantic retrieval")
        provider.add_argument("query")
        provider.add_argument("--config", default=".ai/manacost-quality.json")
        provider.add_argument("--source", action="append", default=[])
        provider.add_argument("--library")
        provider.add_argument("--library-version")
        provider.add_argument("--allow-remote", action="store_true")
        provider.add_argument("--preview-remote", action="store_true")
        provider.add_argument("--evidence-gap", required=True)
        provider.add_argument("--limit", type=int, default=3)
        if name == "reference-search":
            provider.add_argument("--include-tests", action="store_true", help="Include test code in external references")
            provider.add_argument("--full-definition", action="store_true", help="Return complete AST definition up to 16 KB")
            provider.add_argument("--rerank-references", action="store_true",
                                  help="Rank the verified GitHub snippets with native OpenRouter rerank")
    svg = commands.add_parser("svg-normalize", help="Validate and normalize SVG into a new file with pinned SVGO")
    svg.add_argument("source")
    svg.add_argument("--output", required=True)
    svg.add_argument("--monochrome", action="store_true", help="Explicitly convert solid colors to currentColor")
    asset = commands.add_parser("asset-prepare", help="Prepare a new responsive asset bundle without changing its source")
    asset.add_argument("source")
    asset.add_argument("--preset", required=True, choices=("hero-art", "character-cutout", "card-background", "portrait", "decorative-overlay"))
    asset.add_argument("--output", required=True, help="New project-relative output directory")
    asset.add_argument("--alt", default="")
    asset.add_argument("--decorative", action="store_true")
    asset.add_argument("--focal-x", type=float)
    asset.add_argument("--focal-y", type=float)
    asset.add_argument("--remove-background", action="store_true")
    asset.add_argument("--background-python", help="Provisioned CPU rembg environment; defaults to release .assets-venv")
    asset.add_argument("--background-model", help="Provisioned pinned u2netp.onnx; never downloaded at runtime")


def configuration(store, args):
    return load_profile(args.profile) if getattr(args, "profile", None) else load_config(store.root, args.config)


def execute(store, args):
    command = args.command
    if command == "cache-stats":
        return cache_stats(store)
    if command == "retrieval-eval":
        from . import retrieval_eval
        return retrieval_eval.evaluate(store, retrieval_eval.SUITES[args.suite], args.semantic, args.limit)
    if command == "relations":
        from . import relations
        return relations.lookup(store, args.source, args.symbol, args.direction, args.limit, args.config, args.definition_path)
    if command.startswith("queue-"):
        from . import job_queue
        return job_queue.execute(store, args)
    if command in {"index-update", "source-read", "retrieve"}:
        from . import retrieval_flow
        if command == "index-update":
            return retrieval_flow.update_index(store, args.source)
        if command == "source-read":
            return retrieval_flow.definition(store, args.source, args.sha256)
        return retrieval_flow.retrieve(store, args)
    if command == "repo-map":
        return retrieval.repo_map(store, args.source, args.budget)
    if command in {"symbols", "callers", "tests"}:
        return retrieval.lookup(store, args.source, args.symbol, command, args.limit)
    if command == "search":
        return {"matches": retrieval.lexical(store, args.source, args.query, args.limit)}
    if command == "context-build":
        return retrieval.build_context(store, args.task, args.source, args.required, args.budget, args.symbol)
    if command == "verify-context":
        return retrieval.verify_context(store.root, json.loads(read_source(store.root, args.packet)["text"]), args.budget)
    if command == "guard-context":
        return quality_policy.route(args.changed, args.task_type, args.risk, args.stack)
    if command in {"quality-plan", "quality-verify"}:
        config = configuration(store, args)
        if command == "quality-plan":
            return quality_checks.plan(config, args.changed, args.risk, args.task_type, args.family)
        return quality_checks.verify(store, config, args.changed, args.risk, args.task_type, args.family,
                                     args.allow_heavy, args.allow_network, args.only)
    if command == "design-check":
        config = configuration(store, args)
        if args.kind == "tokens":
            return design.check_tokens(store.root, config)
        if args.kind == "components":
            return design.check_components(store.root, config)
        return getattr(design, "check_" + args.kind)(store.root, config, args.source)
    if command == "design-context":
        return design.context(store.root, configuration(store, args), args.query, args.limit)
    if command == "performance-check":
        data = [json.loads(read_source(store.root, name)["text"]) for name in (args.current, args.baseline, args.budgets)]
        return quality_checks.compare_performance(*data)
    if command in {"docs", "reference-search", "semantic-search", "rerank"}:
        from . import quality_providers
        return quality_providers.run(store, args)
    if command in {"asset-prepare", "svg-normalize"}:
        from . import assets
        return assets.normalize_svg(store, args) if command == "svg-normalize" else assets.prepare(store, args)
    raise ValueError("Unknown quality command")


def emit(result):
    if "text" in result:
        print(result["text"], end="")
    else:
        print(encode(result))
    return 1 if result.get("status") in {"failed", "incomplete", "blocked", "missing_tool"} else 0


def guard_main(family, argv=None):
    parser = argparse.ArgumentParser(description=f"Project-scoped {family} guard")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("action", choices=("plan", "verify", "tokens", "css", "svg", "components", "context"))
    parser.add_argument("--config", default=".ai/manacost-quality.json")
    parser.add_argument("--profile", choices=("hearthpulse", "hs-manacost", "nextjs", "go", "wordpress"))
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--query", default="")
    parser.add_argument("--risk", choices=quality_policy.RISKS, default="low")
    parser.add_argument("--task-type", default="implementation")
    parser.add_argument("--allow-heavy", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--only", action="append")
    args = parser.parse_args(argv)
    if family == "engineering" and args.action not in {"plan", "verify"}:
        parser.error("Engineering guard supports plan and verify")
    args.family = family
    args.command = {"plan": "quality-plan", "verify": "quality-verify", "context": "design-context"}.get(args.action, "design-check")
    args.kind, args.query, args.limit = args.action, args.query, 3
    try:
        with Store(args.project, args.state_dir) as store:
            return emit(execute(store, args))
    except (ValueError, OSError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(encode({"status": "blocked", "error": str(exc)}))
        return 2
