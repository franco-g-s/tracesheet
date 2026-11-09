# 0004. No licensed vendor data or report PDFs in git

Date: 2026-11-09. Status: accepted.

## Context

Market data vendors license their data for use, not for redistribution, and a public
repository redistributes everything in it. Annual-report PDFs are large binaries, their
copyright belongs to the publisher, and the publisher already hosts them.

## Decision

- Prices fetched from a vendor stay in `data/cache/`, which is gitignored.
- Report PDFs are not committed: `*.pdf` and `data/raw/` are gitignored. Each document is
  recorded in `documents.toml` by URL and SHA-256 and can be fetched again on demand, so
  "page 47" always refers to one identified file.
- What is committed is typed in by hand: figures transcribed from public annual reports,
  each with its document, page and label.
- The repository holds no vendor datasets. The one exception is a single closing price in
  `data/prices.toml`, used for the example's multiples and attributed to its source there.

## Consequences

A fresh clone renders the sample sheet offline and with no key. Re-checking a figure against
its page needs the PDF fetched first, from the URL in the registry, with the hash confirming
it is the same file.
