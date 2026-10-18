# GhostBench

**Prove what GhostSlice saves, on tasks, not just on tokens.**

GhostSlice's headline number is real but narrow: on the GhostBus tree the
calibrated estimator measures 129,555 tokens full vs 45,770 sliced. That
proves a bundle is smaller. GhostBench proves the rest: that an agent
still completes the task with the slice, that the saving holds on *your*
repo and *your* tasks, and that a new GhostSlice version did not quietly
get worse. Same tasks, same projects, full vs sliced vs verified vs
recalled vs proxied, scored the same way every time.

By Ghost Developer Studio. MIT licensed. **Zero dependencies** (Python
standard library only), **local-first**: no network calls in Tier A, no
telemetry, ever.

Position in the Ghost stack: GhostSlice slices, GhostVerify checks a
slice, GhostRecall adds memory, GhostProxy applies slicing live.
GhostBench *measures* all four. Bench owns no slicing logic of its own:
if Bench and Slice disagree on a token count, that is a bug to surface,
not a number to average.

> Build status: v0.1. The corpus format, report format, and CLI
> contract in this README describe the shipped core
> (`src/ghostbench/`). Test results, the Tier B refusal record, and
> the gaps not yet covered are recorded honestly in `REPORT_B.md`
> (Agent B) and `IMPLEMENTATION_A.md` (core).

## Install

From a checkout, no install needed:

```bash
cd ghostbench
PYTHONPATH=src python3 -m ghostbench --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostbench --help
```

Requires Python 3.10 or newer.

## The two tiers

| Tier | What it does | Model? | Spend? | Default |
|---|---|---|---|---|
| A | Static bench: bundle sizes, GhostVerify verdicts, recorded-patch checks, fit behaviour | No | No | Yes |
| B | Live bench: runs one agent (Claude Code in v0.1) on each task, full vs sliced, scores the test command | Yes | Yours, capped | **Off** |

The tiers are kept separate in every report. A Tier A number is never
presented as a live outcome.

**Tier B hard rule: Bench never spends silently.** The gate order in
the core is: (1) a positive per-run budget cap (`--budget <tokens>`)
is required, (2) explicit confirmation (`--confirm`) is required after
the printed pre-flight, (3) live execution must be enabled with
`GHOSTBENCH_ENABLE_LIVE=1`, and (4) the v0.1 core wires **no executor
at all**, so even a capped, confirmed, enabled run is refused with a
message stating no model was called and nothing was spent. The
pre-flight prints the tasks, the model, the estimated full-context
cost per task and both-arms total from the local price table before
any gate decision. Tier B is never run on a schedule or in CI by
default; CI gets Tier A.

## Quickstart

```bash
# Tier A on the bundled adversarial starter corpus (static, free)
ghostbench run examples/corpora/adversarial/corpus.json --out /tmp/bench-adv
cat /tmp/bench-adv/BENCH.md

# Tier A on the mini corpus used by the test suite
ghostbench run tests/fixtures/mini/corpus.json --out /tmp/bench-mini

# Compare two runs (takes the two bench-report.json files)
ghostbench compare /tmp/bench-adv/bench-report.json /tmp/bench-mini/bench-report.json

# Record your own project in a corpus file (by tree hash, copies no code in)
ghostbench add my-corpus.json --project ~/my-project --id my-project

# Write the core's starter demo corpus somewhere you choose
ghostbench demo-corpus /tmp/ghostbench-demo

# Tier B, opt-in only: refuses without --budget, refuses without --confirm
ghostbench live examples/corpora/adversarial/corpus.json --agent claude-code --budget 20000
```

## Corpus format

A corpus is **one JSON file**. Projects and their tasks live inside it;
paths resolve relative to the corpus file.

```json
{
  "name": "adversarial",
  "version": "0.1.0",
  "projects": [
    {
      "id": "adversarial",
      "path": "project",
      "tasks": [
        {
          "id": "adv-001-fix-missing-route",
          "prompt": "Change the fallback handler name for an unknown route.",
          "expected_files": ["shop/helpers.py"],
          "expected_symbols": ["dispatch"],
          "recorded_patch": "patches/good-patch.diff",
          "test_command": "python3 -m pytest project -q"
        }
      ]
    }
  ]
}
```

Field notes:

- `path` (per project) is the project root, relative to the corpus
  file or absolute. Bench records repo state by `commit` (optional,
  recorded, never fetched) or a computed `tree_hash`
  (`sha256:` over sorted file hashes). Adding a project with
  `ghostbench add` records its tree hash and **never copies its code
  into the corpus**.
- Every task carries `id` and `prompt`, plus optional
  `expected_files` / `expected_symbols` (scoring hints, see Scoring),
  `recorded_patch` (a diff file, resolved relative to the corpus file
  or the project; or inline `patch_text`), `test_command` (string or
  list), `budget_tokens` (per-task fit budget), `verify_report` (a
  GhostVerify report file whose hard gaps Bench compares against what
  actually failed), and `variants` (provided bundles by `bundle_dir`,
  `manifest`, or explicit `tokens` for the sliced / verified /
  recalled / proxied arms).
- Project and task ids must be unique inside the corpus; the loader
  rejects duplicates, missing paths, and non-positive budgets.

Starter corpora, in `examples/corpora/`:

- **ghostbus** - the GhostBus demo tree as a corpus whose project path
  points at the real checkout (relative path, tree hash stamped by the
  loader). Tasks target the real modules (`src/tools.mjs`,
  `src/core.mjs`, `src/handler.mjs`, `src/cli.mjs`), test command
  `node test.mjs`. No GhostBus code is copied into this repo.
- **adversarial** - a small bundled Python project with planted traps:
  a byte-identical duplicate pair, a near-duplicate pair, a small
  generic-looking file (`shop/helpers.py`) that every routing call
  goes through, a recorded patch referencing a missing symbol paired
  with a Verify report predicting a hard gap (it must surface as a
  visible failure), and a superseded decision for Recall runs. A
  correct first run of this corpus is **not** all-green.

## Report format

Every Tier A run writes a run folder containing `BENCH.md` (human,
shareable) and `bench-report.json` (machine), and appends a stamped
record to `.ghostbench-history.jsonl` next to the corpus file. A
summary percentage with no per-task rows is not a valid Bench report:
the report writer refuses a report with no rows.

`bench-report.json` keys (written by the core, see
`src/ghostbench/runner.py` for the authoritative writer):

- Header: `tool`, `tool_version`, `tier`, `suite`, `run_id`,
  `created_utc`, `corpus` (`name`, `version`, `file`), `subset`
  (labelled when `--task` filtered the run).
- Version stamps on every report: `slice_version`,
  `estimator_version`, `estimator_source`, `price_table_date`, and a
  `cost_note` stating costs are estimates, never billed amounts.
- `totals`: `full_tokens`, `tasks`, `pass`, `fail`, `unknown`,
  `hard_gaps_predicted`, and per-variant `tokens`,
  `saving_pct_vs_full`, `fit_success_rate`.
- `tasks`: one row per task with `project`, `task`, `status`
  (pass / fail / unknown), `full_tokens`, per-variant tokens +
  `manifest_sha256` + `source`, `verify` (normalised verdict and
  gaps), `patch` (files touched, sha256), `files_touched_score`,
  `test`, `failures`, and `flaky`.
- `honest_scope`: what Tier A measured and what it did not (live
  agent completion, answer quality).
- `failures_visible`: every failure, by project and task.

Traceability rule: every number in `BENCH.md` comes from the
estimator stamped in the header or from a bundle manifest whose
sha256 is in the same run's `bench-report.json`. Token counts are
**estimates from the GhostSlice estimator method** (or the core's
formula-compatible fallback, named in `estimator_source`), and costs
come from a local dated price table. Estimates are labelled as
estimates in every report, never presented as billed amounts.
Tier B provider-reported tokens, when a future executor records
them, are labelled *reported* and kept separate.

The sliced arm, when a task supplies no bundle, is derived from the
task's `expected_files` and labelled in the row as
`source: derived:expected-files`. Bench does not pretend that is a
GhostSlice-produced bundle.

Two labelled SAMPLE report pairs live in `examples/runs/` purely to
show the format and to exercise compare mode. They carry
`"sample": true` and a sample note, their numbers are illustrative,
and they must never be quoted as bench results.

## Commands

| Command | What it does |
|---|---|
| `ghostbench run <corpus.json> [--suite slice\|verify\|recall\|proxy] [--out <dir>] [--task <id> ...] [--run-tests] [--model <id>] [--ledger <path>] [--no-ledger] [--strict]` | Tier A run. `--run-tests` is opt-in and runs task test commands in a temp copy only. `--strict` exits 1 when any task fails |
| `ghostbench live <corpus.json> --agent claude-code --budget <tokens> [--confirm] [--model <id>] [--task <id> ...]` | Tier B. Gate order: positive budget required, explicit `--confirm` required after the printed preflight, `GHOSTBENCH_ENABLE_LIVE=1` required, and the v0.1 core wires no executor, so a fully gated run is still refused with nothing spent |
| `ghostbench compare <run-a.json> <run-b.json> [--out <file>]` | Per-task token and status deltas (B - A). `.json` out writes the compare object, anything else writes Markdown. Warns when estimator versions differ |
| `ghostbench add <corpus.json> --project <path> --id <id> [--name <name>]` | Record a project in a corpus file by tree hash |
| `ghostbench demo-corpus <dir>` | Write the core's starter adversarial corpus into a directory you choose |
| `ghostbench version` | Print the version |

## Scoring (deliberately boring)

- Task success = the task's test command passes (Tier B, in a temp copy
  only), or the recorded-patch check outcome for Tier A. **No LLM judge
  in v0.1.**
- Files-touched is informational only. Extra files are not
  auto-failures; real fixes touch unexpected files.
- Flakiness is reported, not hidden: a Tier B task that passes one arm
  and fails the other on a re-run is marked flaky.
- Every report shows corpus version, GhostSlice version, estimator
  version, price table date, per-task rows, and **all** failures. Full
  corpus results are the default; a subset run is labelled a subset.

## Verification bar (from PLAN.md)

- A stranger following this README re-runs Tier A on the GhostBus
  corpus and gets the same per-task token numbers at the same Slice
  and estimator versions, which the report states.
- The adversarial corpus produces at least one visible failure or hard
  gap in the first published report.
- Tier B refuses to start without a cap and a confirmation, and stops
  at the cap mid-corpus, reporting partial results as partial.
- Every `BENCH.md` number traces to a manifest hash + a report row.

## Out of scope for v0.1

Hosted leaderboards, public rankings, other people's submitted
results, telemetry, LLM-as-judge scoring, human-rating workflows,
multi-agent Tier B, and competitor comparisons. Bench measures Ghost
tools on stated corpora.

## Layout

```
src/ghostbench/     the core (Agent A): corpus loader, Tier A runner,
                    Tier B runner with the budget gate, compare, reports
tests/              format + fixture tests (run without the core) and
                    black-box CLI tests for run / live-refusal / compare
examples/
  corpora/ghostbus/      starter corpus description for the GhostBus tree
  corpora/adversarial/   bundled adversarial project + recorded patches
  corpus-template/       copy-and-fill corpus for your own project
  runs/                  labelled SAMPLE report pairs (format only)
PLAN.md             the v0.1 plan this build follows
REPORT_B.md         tests/docs build report: honest pass/fail + assumptions
```
