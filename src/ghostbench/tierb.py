"""Tier B live bench: code path present, gated OFF by default.

Gate order (PLAN.md + build gates for this build):
1. budget is required - no cap, no run, ever;
2. explicit confirmation is required - preflight prints the tasks,
   the model, the estimated full-context cost per task and the
   total cap, and nothing runs without an explicit yes;
3. the live executor must be enabled with GHOSTBENCH_ENABLE_LIVE=1;
4. in this v0.1 core build the built-in executor does NOT call any
   model or agent and spends nothing: enabling the gate currently
   yields a clear refusal naming that the executor is not wired.
   A future executor plugs in via run_live(executor=...) and must
   run tasks in temp copies only, record reported tokens separately
   from estimates, and mark divergent re-runs flaky.

Bench never spends silently. That rule outranks convenience.
"""
from __future__ import annotations

import os

from .corpus import Corpus
from .prices import estimate_input_cost_usd, load_price_table, price_table_date
from .runner import _file_tokens
from .corpus import list_project_files

SUPPORTED_AGENTS = ("claude-code",)
LIVE_ENV = "GHOSTBENCH_ENABLE_LIVE"


class TierBRefusal(RuntimeError):
    """Raised whenever a Tier B gate refuses. Message is user-facing."""


def preflight(corpus: Corpus, *, agent: str = "claude-code",
              budget_tokens: int | None = None,
              model: str | None = "claude-sonnet",
              task_filter: set | None = None) -> dict:
    """Build the Tier B preflight shown to the user before any run.

    Lists each task with its estimated full-context tokens and input
    cost, plus the both-arms total. All figures are estimates from the
    local price table. Raises :class:`TierBRefusal` for an unsupported
    agent. This function never runs an agent and never spends.
    """
    if agent not in SUPPORTED_AGENTS:
        raise TierBRefusal(
            f"Tier B v0.1 supports one agent only: {', '.join(SUPPORTED_AGENTS)} "
            f"(got: {agent})")
    table = load_price_table()
    rows = []
    for project, task in corpus.all_tasks():
        if task_filter and task.id not in task_filter:
            continue
        full = sum(_file_tokens(project, rel)
                   for rel in list_project_files(project.path))
        rows.append({
            "project": project.id, "task": task.id, "prompt": task.prompt,
            "full_context_tokens_estimated": full,
            "estimated_input_cost_usd": estimate_input_cost_usd(
                full, model, table),
            "arms": ["full", "sliced"],
        })
    total_est = sum(r["full_context_tokens_estimated"] for r in rows) * 2
    return {
        "tier": "B", "agent": agent, "model": model,
        "budget_tokens": budget_tokens,
        "price_table_date": price_table_date(table),
        "tasks": rows,
        "estimated_total_tokens_both_arms": total_est,
        "confirmation_required": True,
        "note": ("Estimates only, from a local dated price table. "
                 "Both arms (full + sliced) are counted. No run "
                 "starts without a budget cap and explicit confirmation."),
    }


def check_budget(pre: dict, tokens_used: int) -> bool:
    """True while usage is within the cap; caller MUST stop at cap
    and report partial results as partial (PLAN.md budget test)."""
    cap = pre.get("budget_tokens")
    if cap is None or isinstance(cap, bool) \
            or not isinstance(cap, (int, float)):
        return False
    if isinstance(tokens_used, bool) \
            or not isinstance(tokens_used, (int, float)) \
            or tokens_used < 0:
        return False
    return tokens_used <= cap


def run_live(corpus: Corpus, *, agent: str = "claude-code",
             budget_tokens: int | None = None,
             model: str | None = "claude-sonnet",
             confirm: bool = False, task_filter: set | None = None,
             executor=None) -> dict:
    """Enforce the Tier B gates in order, then delegate to ``executor``.

    Gate order: positive budget cap, explicit ``confirm``, then --
    only when no executor is injected -- the
    ``GHOSTBENCH_ENABLE_LIVE=1`` check and the v0.1 "no executor
    wired" refusal. Every refusal raises :class:`TierBRefusal` with a
    user-facing message stating nothing was spent. An injected
    executor receives the preflight dict and its return value is
    returned unchanged.
    """
    pre = preflight(corpus, agent=agent, budget_tokens=budget_tokens,
                    model=model, task_filter=task_filter)
    if budget_tokens is None or isinstance(budget_tokens, bool) \
            or not isinstance(budget_tokens, (int, float)) \
            or budget_tokens <= 0:
        raise TierBRefusal(
            "a positive --budget token cap is required. "
            "Bench never spends without a cap.")
    if pre["estimated_total_tokens_both_arms"] > budget_tokens and executor is None:
        # Still a refusal path below covers execution; preflight data
        # is returned by the CLI so the user sees the over-cap state.
        pass
    if not confirm:
        raise TierBRefusal(
            "explicit confirmation is required after "
            "reviewing the preflight (tasks, model, estimated cost, cap).")
    # Gate 3 applies to EVERY executor, injected ones included: an
    # injected executor must not be able to spend just because the
    # caller supplied one while the env gate is off.
    if os.environ.get(LIVE_ENV) != "1":
        raise TierBRefusal(
            f"live execution is gated OFF by default. "
            f"Set {LIVE_ENV}=1 to enable a wired executor. "
            "No model was called and nothing was spent.")
    if executor is None:
        raise TierBRefusal(
            "no live executor is wired in this v0.1 "
            "core build. No model was called and nothing was spent.")
    return executor(pre)


def mark_flaky(task_rows: list[dict]) -> list[dict]:
    """Given repeated rows for the same task, flag tasks whose arms
    disagree across re-runs. Flakiness is reported, not hidden."""
    by_task: dict[str, list[dict]] = {}
    for row in task_rows:
        by_task.setdefault(row.get("task", ""), []).append(row)
    for task_id, rows in by_task.items():
        statuses = {r.get("status") for r in rows}
        flaky = len(rows) > 1 and len(statuses) > 1
        for row in rows:
            row["flaky"] = flaky
    return task_rows
