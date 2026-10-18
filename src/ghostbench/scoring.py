"""Scoring: deliberately boring (PLAN.md section 4).

- Task success = a user test command passes (when tests are run),
  or, for Tier A static runs, a recorded patch that exists, touches
  at least one expected file, and carries no Verify hard gap.
- No LLM judge anywhere in v0.1.
- Files-touched is INFORMATIONAL: extra files are listed, never
  auto-failures. Real fixes touch unexpected files.
"""
from __future__ import annotations

import hashlib
import re

_DIFF_FILE_RE = re.compile(r"^\+\+\+ [ab]/(.+)$", re.M)
_OLD_FILE_RE = re.compile(r"^--- [ab]/(.+)$", re.M)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def manifest_hash_for_bundle(bundle_dir: str | None = None,
                             manifest_path: str | None = None) -> str | None:
    """sha256 of a bundle manifest.json, for report traceability."""
    import os
    path = manifest_path
    if path is None and bundle_dir:
        path = os.path.join(bundle_dir, "manifest.json")
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return "sha256:" + h.hexdigest()


def manifest_tokens(manifest_path: str) -> int | None:
    """Total sliced tokens from a GhostSlice-style manifest, if the
    manifest carries a recognisable total. None if not determinable:
    Bench surfaces the gap instead of averaging or guessing."""
    import json
    import os
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    totals = data.get("totals") or {}
    for key in ("sliced_tokens", "tokens", "total_tokens"):
        if isinstance(totals.get(key), int):
            return totals[key]
    total = 0
    found = False
    for entry in data.get("files") or []:
        if isinstance(entry, dict) and isinstance(entry.get("sliced_tokens"), int):
            total += entry["sliced_tokens"]
            found = True
    return total if found else None


def parse_patch(text: str) -> dict:
    """Static facts about a unified diff."""
    files = []
    for match in _DIFF_FILE_RE.finditer(text or ""):
        name = match.group(1).strip()
        if name != "/dev/null" and name not in files:
            files.append(name)
    if not files:
        for match in _OLD_FILE_RE.finditer(text or ""):
            name = match.group(1).strip()
            if name != "/dev/null" and name not in files:
                files.append(name)
    added = removed = 0
    for line in (text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "files_touched": files,
        "lines_added": added,
        "lines_removed": removed,
        "patch_sha256": "sha256:" + hashlib.sha256(
            (text or "").encode()).hexdigest(),
        "is_empty": not files and added == 0 and removed == 0,
    }


def normalise_verify_report(data: dict | None) -> dict:
    """Accept GhostVerify report shapes tolerantly, extract the
    signals Bench compares: verdict + hard gaps + soft gaps."""
    if not data:
        return {"present": False, "verdict": None,
                "hard_gaps": [], "soft_gaps": []}
    hard = (data.get("hard_gaps") or data.get("missing_hard")
            or data.get("gaps_hard") or [])
    soft = (data.get("soft_gaps") or data.get("missing_soft")
            or data.get("gaps_soft") or [])
    gaps = data.get("gaps") or []
    if gaps and not hard and not soft:
        for gap in gaps:
            if isinstance(gap, dict) and str(
                    gap.get("severity", "")).lower() in ("hard", "error"):
                hard.append(gap)
            else:
                soft.append(gap)
    verdict = data.get("verdict") or data.get("status")
    if verdict is None and "sufficient" in data:
        verdict = "sufficient" if data["sufficient"] else "insufficient"
    return {"present": True, "verdict": verdict,
            "hard_gaps": list(hard), "soft_gaps": list(soft)}


def score_files_touched(patch_info: dict | None, expected_files: list) -> dict:
    touched = (patch_info or {}).get("files_touched") or []
    expected = list(expected_files or [])
    return {
        "expected_files": expected,
        "touched_files": touched,
        "matched_files": sorted(set(touched) & set(expected)),
        "extra_files": sorted(set(touched) - set(expected)),
        "missing_expected_files": sorted(set(expected) - set(touched)),
        "informational_only": True,
    }


def saving_pct(full_tokens: int, variant_tokens: int | None) -> float | None:
    if variant_tokens is None or not full_tokens:
        return None
    return round((full_tokens - variant_tokens) * 100.0 / full_tokens, 1)
