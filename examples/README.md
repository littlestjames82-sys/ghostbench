# Examples

- `corpora/ghostbus/` - starter corpus description for GhostBus, the standing
  GhostSlice demo tree. External project, described, not copied in.
- `corpora/adversarial/` - the small adversarial project built for Bench,
  bundled in full: planted exact and near duplicates, a called file that is
  easy to wrongly exclude (`project/shop/helpers.py`), a broken recorded
  patch that must surface as a visible failure, and a superseded decision
  for Recall runs.
- `corpus-template/` - copy-and-fill starting point for adding your own
  project as a corpus.
- `runs/sample-tier-a-run-a/` and `runs/sample-tier-a-run-b/` - SAMPLE report
  pairs in the documented `bench-report.json` + `BENCH.md` format, for the
  compare mode. The numbers in these two folders are illustrative format
  examples, labelled SAMPLE in the files themselves. They are not measured
  bench results and must never be quoted as results.
