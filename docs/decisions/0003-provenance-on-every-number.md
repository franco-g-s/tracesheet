# 0003. Every derived number carries its provenance

Date: 2026-11-09. Status: accepted.

## Context

A ratio is only as trustworthy as the figures behind it. In a spreadsheet, the link between a
cell and the page it came from lives in the analyst's head, and it is lost with the first
copy and paste. Checking one number means redoing the work.

## Decision

- Every number after loading is a `Traced`: either a leaf with an origin, a filed report line
  or a market observation, or a derived value with a transform and its inputs.
- A filed leaf carries the document, its SHA-256, the printed page, the report's own label for
  the line and the publication date. An observed leaf carries what was observed, its source
  and its date.
- Derived values are built only through the traced operations. The validator recomputes each
  one from its inputs and refuses a value that does not match.
- A value that cannot be computed is `NotMeaningful` with a reason. Nothing is imputed or
  clamped.
- The sheet lists every leaf once in Sources, and every cell links to its leaves.

## Consequences

Every computation is written with traced arithmetic rather than plain operators on decimals,
which makes the metrics code more verbose. In return, a reviewer can check any figure on the
sheet against the original report without running anything, and a test can assert on a
number's inputs as well as its value.
