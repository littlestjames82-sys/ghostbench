"""Tier B live gate tests. PLAN.md hard rule: Bench never spends
silently - and, since the live-agent build (Oct 18, 2026), never
runs an agent it was not configured to run.

The v0.1 gate model this file used to pin (a positive --budget cap,
--confirm after a printed preflight, GHOSTBENCH_ENABLE_LIVE=1, one
hardcoded --agent, and no executor wired at all) was REPLACED by
the live-agent design: the agent command comes only from
GHOSTBENCH_AGENT_CMD, Bench hardcodes no vendor and has no default
agent, and the gate is a single refusal - with no agent configured,
`ghostbench live` exits 2 before anything runs and writes nothing.
Whatever the configured agent spends happens inside the user's own
program, outside Bench; Bench itself calls no model and no network.

These tests pin that refusal at the CLI level. The behaviour of a
configured run (with fake agents only) is pinned in
tests/test_live_agent.py.
"""

from conftest import FIXTURES, requires_core, run_cli, copy_corpus

MINI = "corpus.json"


@requires_core
def test_live_refuses_without_an_agent_command(tmp_path):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    proc = run_cli(["live", corpus_dir / MINI], stdin="",
                   env_remove=("GHOSTBENCH_AGENT_CMD",))
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2, "live did not refuse with no agent configured"
    assert "no agent is configured" in combined
    assert "ghostbench_agent_cmd" in combined
    # The refusal happens before anything runs: no run folder, no
    # report, no ledger record was written anywhere.
    assert not (corpus_dir / "runs").exists()
    assert not (corpus_dir / ".ghostbench-history.jsonl").exists()


@requires_core
def test_live_refuses_with_an_empty_agent_command(tmp_path):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    proc = run_cli(["live", corpus_dir / MINI], stdin="",
                   env_extra={"GHOSTBENCH_AGENT_CMD": "   "})
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2
    assert "no agent is configured" in combined
    assert not (corpus_dir / "runs").exists()


@requires_core
def test_live_help_documents_the_agent_contract(tmp_path):
    """--help is where the configuration contract lives: the env
    var, the three task variables, the timeout flag, and the
    first-token-only recording rule."""
    proc = run_cli(["live", "--help"])
    assert proc.returncode == 0
    text = " ".join(proc.stdout.split())  # unwrap argparse's lines
    for needle in ("GHOSTBENCH_AGENT_CMD", "GHOSTBENCH_TASK_DIR",
                   "GHOSTBENCH_TASK_ID", "GHOSTBENCH_TASK_PROMPT",
                   "--agent-timeout", "first token"):
        assert needle in text, f"live --help does not document {needle}"
