# GhostBench - Test Results

Reproducible record of a full-suite run. Regenerate on every
release-grade change; counts quoted anywhere else must match this
file or be removed.

## Run of Oct 18, 2026 (evidence-contract build)

- Date (UTC): 2026-10-18T20:50Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostbench v0.1.0, evidence-contract build (sandbox hardening
  + verification_level), working tree identical to the GitHub push
  that carries this file
- Command:

```sh
cd ghostbench
PYTHONPATH=src python3 -m pytest tests -q -rs
```

- Result: **92 passed, 1 skipped** (3.81s)

The one skip, stated by the test itself
(`tests/test_budget_gate.py:75`): the mid-corpus budget-cap stop in
`tierb.check_budget` can only be exercised end-to-end with a stub
executor injected into `run_live`, which the CLI does not expose; the
CLI-level gate cannot reach it without a live run, and live runs are
gated off in this build. See REPORT_B.md.

## Evidence-contract probes (known-answer set, in the suite)

`tests/test_evidence_contract.py` (23 tests) encodes the sanity gate:
a passing test command scores pass; a failing one scores fail; a
planted parent-env secret (`GHOSTBENCH_PROBE_SECRET`) does not reach
the test process; a patch escaping the temp copy (`../`, absolute, or
through a patch-created symlink) is refused before `git apply`; a
project symlink to an outside file is skipped and recorded, never
followed. Parent re-verification on Oct 18, 2026 reproduced the
secret probe independently of the suite: output `SECRET_IS: ABSENT`.

## Known limits of this run

- Tier B (live-agent) did not run: it is gated off by design, and no
  code path in v0.1.0 emits a `live-agent` report yet.
- Test execution containment is application-level (scrubbed env,
  contained patch/copy, POSIX rlimits, timeout). Host filesystem
  writes and network access by a test process are not OS-enforced;
  every report's `sandbox` block says so.
