"""Tier B budget gate tests. PLAN.md hard rule: Bench never spends
silently. The core's gate order (src/ghostbench/tierb.py) is:
(1) a positive --budget cap is required, (2) explicit confirmation via
--confirm is required after the preflight is printed, (3) live
execution must be enabled with GHOSTBENCH_ENABLE_LIVE=1, and (4) the
v0.1 core wires no executor at all, so even a capped, confirmed run
is refused with 'nothing was spent'.

These tests exercise refusal paths only. The one test that passes
--confirm also removes GHOSTBENCH_ENABLE_LIVE from the environment,
so gate (3) refuses before any executor could ever be reached.
"""

import pytest

from conftest import FIXTURES, requires_core, run_cli, copy_corpus

MINI = "corpus.json"


def _live(tmp_path, *extra, env_remove=()):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    return run_cli(
        ["live", corpus_dir / MINI, "--agent", "claude-code", *extra],
        stdin="",
        env_remove=env_remove,
    )


@requires_core
def test_live_refuses_without_a_budget_cap(tmp_path):
    proc = _live(tmp_path)
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2, "Tier B did not refuse a run with no budget cap"
    assert "budget" in combined and "refused" in combined


@requires_core
def test_live_refuses_with_budget_but_no_confirmation(tmp_path):
    proc = _live(tmp_path, "--budget", "20000")
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2, "Tier B did not refuse an unconfirmed run"
    assert "confirmation is required" in combined


@requires_core
def test_live_preflight_shows_estimate_before_refusing(tmp_path):
    """The CLI prints the preflight (tasks, model, estimated cost, cap)
    before the confirmation refusal, so the user refuses informed."""
    proc = _live(tmp_path, "--budget", "20000")
    stdout = proc.stdout.lower()
    assert proc.returncode == 2
    assert "preflight" in stdout and "estimat" in stdout
    assert "budget cap: 20000" in stdout


@requires_core
def test_live_confirmed_but_executor_gate_off_still_spends_nothing(tmp_path):
    proc = _live(tmp_path, "--budget", "20000", "--confirm",
                 env_remove=("GHOSTBENCH_ENABLE_LIVE",))
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2
    assert "nothing was spent" in combined or "no model was called" in combined


@requires_core
def test_live_rejects_an_unsupported_agent(tmp_path):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    proc = run_cli(["live", corpus_dir / MINI, "--agent", "some-other-agent",
                    "--budget", "20000"])
    assert proc.returncode == 2
    assert "one agent only" in (proc.stdout + proc.stderr).lower()


@pytest.mark.skip(reason="Mid-corpus cap stop (tierb.check_budget in the core) can only "
                         "be exercised end-to-end with a stub executor injected into "
                         "run_live, which the CLI does not expose; the CLI-level gate "
                         "cannot reach it without a live run. Not run under the "
                         "no-live-runs gate for this build. See REPORT_B.md.")
def test_live_stops_at_cap_mid_corpus_and_reports_partial():
    raise NotImplementedError
