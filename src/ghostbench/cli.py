"""GhostBench CLI.

Commands:
  ghostbench run <corpus> [--suite slice|verify|recall|proxy]
                          [--out DIR] [--task ID ...] [--run-tests]
                          [--model ID] [--ledger PATH] [--no-ledger]
  ghostbench compare <run-a.json> <run-b.json> [--out FILE]
  ghostbench add <corpus> --project PATH --id ID   (record a project)
  ghostbench live <corpus> --agent claude-code --budget N
                          [--model ID] [--confirm]  (Tier B, gated)
  ghostbench demo-corpus <dir>                     (starter fixture)
  ghostbench version
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .corpus import CorpusError, compute_tree_hash, load_corpus
from .demo import make_demo_corpus
from .report import (compare_reports, render_compare_md,
                     write_bench_md, write_json_report)
from .runner import append_ledger, run_corpus
from .tierb import TierBRefusal, preflight, run_live


def _cmd_run(args) -> int:
    corpus = load_corpus(args.corpus)
    task_filter = set(args.task) if args.task else None
    report = run_corpus(corpus, suite=args.suite,
                        run_tests=args.run_tests,
                        task_filter=task_filter, model=args.model)
    out_dir = args.out or os.path.join(corpus.base_dir, "runs",
                                       report["run_id"])
    write_json_report(report, os.path.join(out_dir, "bench-report.json"))
    write_bench_md(report, os.path.join(out_dir, "BENCH.md"))
    ledger_path = None
    if not args.no_ledger:
        ledger_path = args.ledger or os.path.join(
            corpus.base_dir, ".ghostbench-history.jsonl")
        append_ledger(report, ledger_path)
    t = report["totals"]
    sliced = t["variants"].get("sliced", {})
    print(f"run {report['run_id']}: tasks={t['tasks']} "
          f"pass={t['pass']} fail={t['fail']} unknown={t['unknown']} "
          f"full={t['full_tokens']} sliced={sliced.get('tokens')} "
          f"saving={sliced.get('saving_pct_vs_full')}%")
    print(f"wrote {out_dir}/BENCH.md and bench-report.json")
    if ledger_path:
        print(f"ledger appended: {ledger_path}")
    return 1 if t["fail"] and args.strict else 0


def _load_report_arg(value: str) -> dict:
    """Compare accepts a bench-report.json file or a run directory
    containing one."""
    path = value
    if os.path.isdir(path):
        path = os.path.join(path, "bench-report.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cmd_compare(args) -> int:
    rep_a = _load_report_arg(args.run_a)
    rep_b = _load_report_arg(args.run_b)
    comp = compare_reports(rep_a, rep_b)
    if args.out:
        if args.out.endswith(".json"):
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(comp, fh, indent=2, sort_keys=True)
        else:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(render_compare_md(comp))
        print(f"wrote {args.out}")
    else:
        print(render_compare_md(comp))
    if comp["estimator_mismatch_warning"]:
        print(f"WARNING: {comp['estimator_mismatch_warning']}",
              file=sys.stderr)
    return 0


def _cmd_add(args) -> int:
    project_path = os.path.abspath(args.project)
    if not os.path.isdir(project_path):
        print(f"error: not a directory: {args.project}", file=sys.stderr)
        return 2
    tree_hash = compute_tree_hash(project_path)
    entry = {"id": args.id, "path": project_path,
             "tree_hash": tree_hash, "tasks": []}
    corpus_path = args.corpus
    if os.path.isfile(corpus_path):
        with open(corpus_path, encoding="utf-8") as fh:
            data = json.load(fh)
        ids = {p.get("id") for p in data.get("projects") or []}
        if args.id in ids:
            print(f"error: project id already in corpus: {args.id}",
                  file=sys.stderr)
            return 2
        data.setdefault("projects", []).append(entry)
    else:
        data = {"name": args.name or "my-corpus", "version": "1",
                "projects": [entry]}
    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print(f"recorded project {args.id} tree_hash={tree_hash} "
          f"in {corpus_path} (no code copied)")
    return 0


def _cmd_live(args) -> int:
    corpus = load_corpus(args.corpus)
    task_filter = set(args.task) if args.task else None
    try:
        pre = preflight(corpus, agent=args.agent,
                        budget_tokens=args.budget, model=args.model,
                        task_filter=task_filter)
    except TierBRefusal as exc:
        print(f"Tier B refused: {exc}", file=sys.stderr)
        return 2
    print("Tier B preflight (estimates only, not billed amounts):")
    print(f"  agent={pre['agent']} model={pre['model']} "
          f"price_table_date={pre['price_table_date']}")
    for row in pre["tasks"]:
        print(f"  {row['project']}/{row['task']}: "
              f"full~{row['full_context_tokens_estimated']} tokens, "
              f"est input ${row['estimated_input_cost_usd']}")
    print(f"  estimated total both arms: "
          f"{pre['estimated_total_tokens_both_arms']} tokens; "
          f"budget cap: {pre['budget_tokens']}")
    try:
        run_live(corpus, agent=args.agent, budget_tokens=args.budget,
                 model=args.model, confirm=args.confirm,
                 task_filter=task_filter)
    except TierBRefusal as exc:
        print(f"Tier B refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_demo(args) -> int:
    path = make_demo_corpus(args.dir)
    print(f"demo corpus written: {path}")
    print(f"run it: ghostbench run {path} --out <runs-dir>")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghostbench",
        description="Proof harness for GhostSlice. Tier A static by "
                    "default; Tier B live is opt-in and budget-gated.")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Tier A static run")
    p_run.add_argument("corpus")
    p_run.add_argument("--suite", choices=["slice", "verify", "recall", "proxy"],
                       default="slice")
    p_run.add_argument("--out")
    p_run.add_argument("--task", action="append",
                       help="only this task id (repeatable); run is labelled a subset")
    p_run.add_argument("--run-tests", action="store_true",
                       help="run task test commands in a temp copy (opt-in)")
    p_run.add_argument("--model", help="model id for cost estimates")
    p_run.add_argument("--ledger")
    p_run.add_argument("--no-ledger", action="store_true")
    p_run.add_argument("--strict", action="store_true",
                       help="exit 1 when any task fails")
    p_run.set_defaults(func=_cmd_run)

    p_cmp = sub.add_parser("compare", help="compare two bench-report.json files")
    p_cmp.add_argument("run_a")
    p_cmp.add_argument("run_b")
    p_cmp.add_argument("--out")
    p_cmp.set_defaults(func=_cmd_compare)

    p_add = sub.add_parser("add", help="record a project in a corpus file")
    p_add.add_argument("corpus")
    p_add.add_argument("--project", required=True)
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--name", help="corpus name when creating a new corpus")
    p_add.set_defaults(func=_cmd_add)

    p_live = sub.add_parser("live", help="Tier B live run (gated OFF by default)")
    p_live.add_argument("corpus")
    p_live.add_argument("--agent", default="claude-code")
    p_live.add_argument("--budget", type=int,
                        help="hard token budget cap (required)")
    p_live.add_argument("--model", default="claude-sonnet")
    p_live.add_argument("--task", action="append")
    p_live.add_argument("--confirm", action="store_true",
                        help="explicit confirmation after preflight")
    p_live.set_defaults(func=_cmd_live)

    p_demo = sub.add_parser("demo-corpus", help="write the starter adversarial corpus")
    p_demo.add_argument("dir")
    p_demo.set_defaults(func=_cmd_demo)

    sub.add_parser("version", help="print version")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "version":
        print(f"ghostbench {__version__}")
        return 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
