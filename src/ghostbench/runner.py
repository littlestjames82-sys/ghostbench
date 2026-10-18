"""Tier A static runner (default, free, deterministic) + ledger.

Tier A builds, per task:
- a "full" variant: every scannable file in the project, or the
  task's provided full bundle manifest when one is supplied;
- a "sliced" variant: the task's provided sliced bundle manifest
  when supplied, otherwise the task's expected_files only (a
  task-selection derivation, labelled as such in every row -
  Bench does not pretend this is a GhostSlice-produced bundle);
- any further variants (verified / recalled / proxied / custom)
  strictly from provided bundle manifests or explicit token totals.

Recorded patches get a static pass (files touched, Verify hard
gaps). Tests are NOT run unless the caller explicitly passes
run_tests=True, in which case they run in a temporary copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from . import __version__
from .corpus import (Corpus, Project, Task, list_project_files,
                     read_task_patch, read_verify_report)
from .prices import estimate_input_cost_usd, load_price_table, price_table_date
from .scoring import (manifest_hash_for_bundle, manifest_tokens,
                      normalise_verify_report, parse_patch,
                      saving_pct, score_files_touched)
from .tokens import (ESTIMATOR_SOURCE, ESTIMATOR_VERSION,
                     estimate_tokens, language_for_path, slice_version)

TEXT_EXT_SKIP = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
                 ".zip", ".gz", ".so", ".dll", ".exe", ".class", ".pyc"}


def _read_text(path: str) -> str | None:
    if os.path.splitext(path)[1].lower() in TEXT_EXT_SKIP:
        return None
    try:
        with open(path, encoding="utf-8", errors="strict") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None


def _file_tokens(project: Project, rel: str) -> int:
    text = _read_text(os.path.join(project.path, rel))
    if text is None:
        return 0
    return estimate_tokens(text, language_for_path(rel))


def _resolve_spec_path(corpus: Corpus, value: str) -> str:
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(corpus.base_dir, value))


def _variant_from_spec(corpus: Corpus, spec: dict) -> dict:
    """A variant supplied via bundle_dir / manifest / tokens."""
    out = {"tokens": None, "manifest_sha256": None, "source": "provided"}
    if isinstance(spec.get("tokens"), int):
        out["tokens"] = spec["tokens"]
        out["source"] = "provided-tokens"
    bundle_dir = spec.get("bundle_dir")
    manifest = spec.get("manifest")
    if bundle_dir:
        bdir = _resolve_spec_path(corpus, bundle_dir)
        out["manifest_sha256"] = manifest_hash_for_bundle(bundle_dir=bdir)
        mt = manifest_tokens(os.path.join(bdir, "manifest.json"))
        if mt is not None:
            out["tokens"] = mt
            out["source"] = "bundle-manifest"
    if manifest:
        mpath = _resolve_spec_path(corpus, manifest)
        out["manifest_sha256"] = manifest_hash_for_bundle(manifest_path=mpath)
        mt = manifest_tokens(mpath)
        if mt is not None:
            out["tokens"] = mt
            out["source"] = "bundle-manifest"
    return out


def _apply_patch_git(temp_root: str, patch_text: str) -> tuple[bool, str]:
    patch_file = os.path.join(temp_root, ".ghostbench-patch.diff")
    with open(patch_file, "w", encoding="utf-8") as fh:
        fh.write(patch_text)
    try:
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_file],
            cwd=temp_root, capture_output=True, text=True, timeout=30)
        return proc.returncode == 0, (proc.stderr or proc.stdout or "")[-500:]
    except Exception as exc:  # git missing etc: reported, not hidden
        return False, f"git apply unavailable/failed: {exc}"
    finally:
        try:
            os.remove(patch_file)
        except OSError:
            pass


def _run_test_in_temp(project: Project, task: Task,
                        patch_text: str | None) -> dict:
    cmd = task.test_command
    argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd or [])
    if not argv:
        return {"ran": False, "status": "no-test-command"}
    tmp = tempfile.mkdtemp(prefix="ghostbench-test-")
    try:
        dest = os.path.join(tmp, "project")
        shutil.copytree(project.path, dest, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "node_modules"))
        if patch_text:
            ok, msg = _apply_patch_git(dest, patch_text)
            if not ok:
                return {"ran": False, "status": "patch-apply-failed",
                        "detail": msg}
        try:
            proc = subprocess.run(argv, cwd=dest, capture_output=True,
                                  text=True, timeout=120)
            return {"ran": True,
                    "status": "pass" if proc.returncode == 0 else "fail",
                    "exit_code": proc.returncode,
                    "output_tail": (proc.stdout + proc.stderr)[-1000:]}
        except subprocess.TimeoutExpired:
            return {"ran": True, "status": "timeout", "exit_code": None}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_task(corpus: Corpus, project: Project, task: Task, *,
               suite: str = "slice", run_tests: bool = False,
               model: str | None = None, table: dict | None = None) -> dict:
    failures: list[str] = []
    files = list_project_files(project.path)
    full_tokens = sum(_file_tokens(project, rel) for rel in files)
    variants: dict[str, dict] = {}

    full_spec = (task.variants or {}).get("full")
    if full_spec:
        full_v = _variant_from_spec(corpus, full_spec)
        if full_v["tokens"] is not None:
            full_tokens = full_v["tokens"]
            variants["full"] = {**full_v, "fit_success": None}
    if "full" not in variants:
        variants["full"] = {"tokens": full_tokens,
                            "manifest_sha256": None,
                            "source": "project-scan", "fit_success": None}

    sliced_spec = (task.variants or {}).get("sliced")
    if sliced_spec:
        sliced = _variant_from_spec(corpus, sliced_spec)
        if sliced["tokens"] is None:
            failures.append("sliced variant supplied but its token "
                            "total could not be determined from the manifest")
    else:
        sliced_tokens = sum(
            _file_tokens(project, rel) for rel in task.expected_files
            if os.path.isfile(os.path.join(project.path, rel)))
        sliced = {"tokens": sliced_tokens, "manifest_sha256": None,
                  "source": "derived:expected-files"}
    variants["sliced"] = sliced

    wanted_extra = {"slice": [], "verify": ["verified"],
                    "recall": ["recalled"], "proxy": ["proxied"]}[suite]
    for name, spec in (task.variants or {}).items():
        if name in ("full", "sliced"):
            continue
        if wanted_extra and name not in wanted_extra:
            continue
        variants[name] = _variant_from_spec(corpus, spec)

    budget = task.budget_tokens
    for name, var in variants.items():
        var["saving_pct_vs_full"] = saving_pct(full_tokens, var["tokens"])
        var["fit_success"] = (
            None if budget is None or var["tokens"] is None
            else var["tokens"] <= budget)
        var["estimated_input_cost_usd"] = estimate_input_cost_usd(
            var["tokens"] or 0, model, table) if var["tokens"] is not None else None
    if budget is not None and variants["sliced"]["fit_success"] is False:
        failures.append(
            f"sliced variant ({variants['sliced']['tokens']} tokens) "
            f"exceeds task budget ({budget} tokens)")

    vdata, vhash = read_verify_report(corpus, project, task)
    verify = normalise_verify_report(vdata)
    verify["report_sha256"] = ("sha256:" + vhash) if vhash else None
    hard_gaps = verify["hard_gaps"]
    if hard_gaps:
        failures.append(f"verify predicted {len(hard_gaps)} hard gap(s)")

    patch_text = read_task_patch(corpus, project, task)
    patch = parse_patch(patch_text) if patch_text is not None else None
    files_score = score_files_touched(patch, task.expected_files)

    test_result = {"ran": False, "status": "not-run"}
    if run_tests and task.test_command:
        test_result = _run_test_in_temp(project, task, patch_text)
        if test_result.get("status") not in ("pass",):
            failures.append(f"test command: {test_result.get('status')}")

    if test_result["ran"]:
        status = "pass" if test_result["status"] == "pass" else "fail"
    elif patch is not None:
        patch_fail = False
        if patch["is_empty"]:
            patch_fail = True
            failures.append("recorded patch is empty")
        if hard_gaps:
            patch_fail = True
        if not files_score["matched_files"]:
            patch_fail = True
            failures.append("recorded patch touches no expected file")
        status = "fail" if patch_fail else "pass"
    elif hard_gaps:
        status = "fail"
    else:
        status = "unknown"
        failures.append("no recorded patch and no test result: "
                        "task outcome cannot be scored in Tier A")

    return {
        "project": project.id, "task": task.id, "prompt": task.prompt,
        "project_commit": project.commit,
        "project_tree_hash": project.tree_hash,
        "full_tokens": full_tokens,
        "variants": variants,
        "budget_tokens": budget,
        "verify": verify,
        "hard_gaps_predicted": len(hard_gaps),
        "soft_gaps_predicted": len(verify["soft_gaps"]),
        "patch": patch,
        "files_touched_score": files_score,
        "test": test_result,
        "status": status,
        "failures": failures,
        "flaky": False,
    }


def run_corpus(corpus: Corpus, *, suite: str = "slice",
               run_tests: bool = False, task_filter: set | None = None,
               model: str | None = None) -> dict:
    table = load_price_table()
    rows = []
    for project, task in corpus.all_tasks():
        if task_filter and task.id not in task_filter:
            continue
        rows.append(run_task(corpus, project, task, suite=suite,
                             run_tests=run_tests, model=model, table=table))
    totals: dict = {"full_tokens": sum(r["full_tokens"] for r in rows),
                    "tasks": len(rows),
                    "pass": sum(1 for r in rows if r["status"] == "pass"),
                    "fail": sum(1 for r in rows if r["status"] == "fail"),
                    "unknown": sum(1 for r in rows if r["status"] == "unknown"),
                    "hard_gaps_predicted": sum(
                        r["hard_gaps_predicted"] for r in rows),
                    "variants": {}}
    variant_names = sorted({n for r in rows for n in r["variants"]})
    for name in variant_names:
        toks = [r["variants"][name]["tokens"] for r in rows
                if r["variants"].get(name, {}).get("tokens") is not None]
        fits = [r["variants"][name]["fit_success"] for r in rows
                if r["variants"].get(name, {}).get("fit_success") is not None]
        if toks:
            total_toks = sum(toks)
            partial = len(toks) < len(rows)
            totals["variants"][name] = {
                "tokens": total_toks,
                "tasks_with_tokens": len(toks),
                "partial": partial,
                # A saving against the full total is only meaningful
                # when every task contributed a token total.
                "saving_pct_vs_full": (
                    None if partial else
                    saving_pct(totals["full_tokens"], total_toks)),
                "fit_success_rate": (
                    round(sum(1 for f in fits if f) * 100.0 / len(fits), 1)
                    if fits else None),
            }
    now = datetime.now(timezone.utc)
    fingerprint = hashlib.sha256(json.dumps(
        {"corpus": corpus.name, "version": corpus.version, "rows": rows},
        sort_keys=True, default=str).encode()).hexdigest()[:12]
    subset = (sorted(task_filter) if task_filter else None)
    return {
        "tool": "ghostbench", "tool_version": __version__,
        "tier": "A", "suite": suite,
        "run_id": f"{now.strftime('%Y%m%dT%H%M%SZ')}-{fingerprint}",
        "created_utc": now.isoformat(),
        "corpus": {"name": corpus.name, "version": corpus.version,
                   "file": corpus.path},
        "subset": ({"labelled": True, "task_ids": subset}
                   if subset else {"labelled": False, "task_ids": None}),
        "slice_version": slice_version(),
        "estimator_version": ESTIMATOR_VERSION,
        "estimator_source": ESTIMATOR_SOURCE,
        "price_table_date": price_table_date(table),
        "price_table_source": table.get("_source"),
        "model_for_cost_estimates": model,
        "cost_note": ("Costs are ESTIMATES from a local dated price "
                      "table, never billed amounts."),
        "run_tests": run_tests,
        "honest_scope": {
            "tier": "A (static, no model, no spend)",
            "tasks_measured": len(rows),
            "what_was_not_measured": [
                "live agent task completion (Tier B, opt-in, not run)",
                "answer quality (no LLM judge in v0.1)",
            ],
        },
        "totals": totals,
        "tasks": rows,
        "failures_visible": [
            {"project": r["project"], "task": r["task"],
             "failures": r["failures"]}
            for r in rows if r["failures"]],
    }


def append_ledger(report: dict, ledger_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(ledger_path)), exist_ok=True)
    record = {
        "ts": report["created_utc"], "run_id": report["run_id"],
        "tool_version": report["tool_version"], "tier": report["tier"],
        "estimator_version": report["estimator_version"],
        "corpus": report["corpus"]["name"],
        "corpus_version": report["corpus"]["version"],
        "totals": report["totals"],
    }
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return ledger_path


def read_ledger(ledger_path: str) -> list[dict]:
    if not os.path.isfile(ledger_path):
        return []
    out = []
    with open(ledger_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
