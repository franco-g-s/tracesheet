# 0002. Evaluations are immutable and content-addressed

Date: 2026-11-09. Status: accepted.

## Context

An evaluation depends on the filings known at a date, the code that ran and the price used.
If a re-run overwrote the previous result, there would be no way to see what changed, or to
show what a sheet said at the time it was read.

## Decision

- Running a company again creates a new evaluation; nothing is updated in place.
- Each traced number is stored once, as a file named by its content id. An evaluation is a
  manifest that refers to its numbers by id, named by its run time and a hash of its bytes.
- Encoding is deterministic, so the same evaluation always produces the same bytes.
- Saving refuses to replace a file that exists with different content, and every load
  re-hashes what it reads.
- Each evaluation records its as-of moment, its run time and the code version, including the
  git commit when run from a checkout.

## Consequences

Storage grows with every run, slowly, because unchanged numbers are shared between
evaluations. Diffing two evaluations becomes a comparison of manifests and node ids, which is
listed in the roadmap. Stored evaluations live under `data/evaluations/`, which is
gitignored.
