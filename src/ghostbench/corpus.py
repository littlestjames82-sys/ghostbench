"""Corpus format + loader.

A corpus is a single JSON file:

{
  "name": "my-corpus",
  "version": "1",                    // or "corpus_version"
  "projects": [
    {
      "id": "adversarial",
      "path": "projects/adversarial",   // relative to the corpus file
      "commit": "abc123...",            // optional, recorded not fetched
      "tree_hash": "sha256:...",        // optional; computed if absent
      "tasks": [
        {
          "id": "fix-swap",
          "prompt": "Fix Pair.swap",
          "expected_files": ["src/pair.py"],
          "expected_symbols": ["Pair.swap"],        // optional
          "recorded_patch": "patches/fix-swap.diff", // path or null
          "patch_text": "...",                       // inline alternative
          "test_command": "python3 -m pytest -q",    // str or list, opt.
          "budget_tokens": 20000,                    // fit budget, opt.
          "verify_report": "verify/fix-swap.json",   // optional
          "variants": {                              // optional bundles
            "sliced": {"bundle_dir": "bundles/fix-swap"},
            "verified": {"manifest": "bundles/fix-swap-v/manifest.json",
                          "tokens": 1234}
          }
        }
      ]
    }
  ]
}

Bench records repo state by commit hash or tree hash; it never
copies project code into Bench's own tree (PLAN.md, corpus format).
Paths inside a corpus resolve relative to the corpus file.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", ".venv", "venv"}


class CorpusError(ValueError):
    pass


@dataclass
class Task:
    id: str
    prompt: str = ""
    expected_files: list = field(default_factory=list)
    expected_symbols: list = field(default_factory=list)
    recorded_patch: str | None = None
    patch_text: str | None = None
    test_command: object = None
    budget_tokens: int | None = None
    verify_report: str | None = None
    variants: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class Project:
    id: str
    path: str  # absolute
    commit: str | None = None
    tree_hash: str | None = None
    tasks: list = field(default_factory=list)


@dataclass
class Corpus:
    name: str
    version: str
    path: str  # corpus file (absolute)
    base_dir: str
    projects: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def all_tasks(self):
        for project in self.projects:
            for task in project.tasks:
                yield project, task


def _resolve(base_dir: str, value: str) -> str:
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(base_dir, value))


def compute_tree_hash(root: str) -> str:
    """Deterministic sha256 over (relpath, content-hash) pairs."""
    h = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            try:
                with open(full, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                continue
            entries.append((rel, digest))
    for rel, digest in sorted(entries):
        h.update(rel.encode("utf-8", "replace"))
        h.update(b"\0")
        h.update(digest.encode())
        h.update(b"\n")
    return "sha256:" + h.hexdigest()


def list_project_files(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


def load_corpus(path: str) -> Corpus:
    apath = os.path.abspath(path)
    if not os.path.isfile(apath):
        raise CorpusError(f"corpus file not found: {path}")
    try:
        with open(apath, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise CorpusError(f"corpus is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CorpusError("corpus root must be a JSON object")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise CorpusError("corpus requires a string 'name'")
    version = raw.get("version", raw.get("corpus_version"))
    if version is None:
        raise CorpusError("corpus requires 'version' (or 'corpus_version')")
    base = os.path.dirname(apath)
    projects_raw = raw.get("projects")
    if not isinstance(projects_raw, list) or not projects_raw:
        raise CorpusError("corpus requires a non-empty 'projects' list")
    projects = []
    seen_projects = set()
    for praw in projects_raw:
        if not isinstance(praw, dict) or not praw.get("id"):
            raise CorpusError("each project requires an 'id'")
        pid = praw["id"]
        if pid in seen_projects:
            raise CorpusError(f"duplicate project id: {pid}")
        seen_projects.add(pid)
        ppath_raw = praw.get("path")
        if not ppath_raw:
            raise CorpusError(f"project {pid}: requires 'path'")
        ppath = _resolve(base, ppath_raw)
        if not os.path.isdir(ppath):
            raise CorpusError(f"project {pid}: path is not a directory: {ppath_raw}")
        tasks = []
        seen_tasks = set()
        for traw in praw.get("tasks") or []:
            if not isinstance(traw, dict) or not traw.get("id"):
                raise CorpusError(f"project {pid}: each task requires an 'id'")
            tid = traw["id"]
            if tid in seen_tasks:
                raise CorpusError(f"project {pid}: duplicate task id: {tid}")
            seen_tasks.add(tid)
            budget = traw.get("budget_tokens")
            if budget is not None and (not isinstance(budget, int) or budget <= 0):
                raise CorpusError(f"task {tid}: budget_tokens must be a positive int")
            tasks.append(Task(
                id=tid,
                prompt=traw.get("prompt", ""),
                expected_files=list(traw.get("expected_files") or []),
                expected_symbols=list(traw.get("expected_symbols") or []),
                recorded_patch=traw.get("recorded_patch"),
                patch_text=traw.get("patch_text"),
                test_command=traw.get("test_command"),
                budget_tokens=budget,
                verify_report=traw.get("verify_report"),
                variants=dict(traw.get("variants") or {}),
                raw=traw,
            ))
        projects.append(Project(
            id=pid, path=ppath,
            commit=praw.get("commit"),
            tree_hash=praw.get("tree_hash") or compute_tree_hash(ppath),
            tasks=tasks,
        ))
    return Corpus(name=name, version=str(version), path=apath,
                  base_dir=base, projects=projects, raw=raw)


def read_task_patch(corpus: Corpus, project: Project, task: Task) -> str | None:
    if task.patch_text:
        return task.patch_text
    if not task.recorded_patch:
        return None
    p = _resolve(corpus.base_dir, task.recorded_patch)
    if not os.path.isfile(p):
        # Also try relative to the project dir.
        alt = os.path.join(project.path, task.recorded_patch)
        if os.path.isfile(alt):
            p = alt
        else:
            raise CorpusError(
                f"task {task.id}: recorded_patch not found: {task.recorded_patch}")
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def read_verify_report(corpus: Corpus, project: Project, task: Task):
    if not task.verify_report:
        return None, None
    p = _resolve(corpus.base_dir, task.verify_report)
    if not os.path.isfile(p):
        alt = os.path.join(project.path, task.verify_report)
        if os.path.isfile(alt):
            p = alt
        else:
            raise CorpusError(
                f"task {task.id}: verify_report not found: {task.verify_report}")
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    return data, hashlib.sha256(json.dumps(
        data, sort_keys=True).encode()).hexdigest()
