# AGENTS.md

Rules for anyone changing this repository, human or coding agent. Read
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before changing a stage, and the records in
[`docs/decisions/`](docs/decisions/) before changing anything they cover.

## Commands

```sh
uv sync                          # create .venv from uv.lock
uv run ruff check .              # lint
uv run ruff format --check .     # formatting (drop --check to apply)
uv run mypy                      # types, strict
uv run pytest                    # tests

uv run tracesheet load kuehne-nagel      # check a company's filings tie out
uv run tracesheet render kuehne-nagel    # write examples/kuehne-nagel.html
uv run tracesheet evaluate kuehne-nagel  # store an evaluation under data/evaluations/
```

CI runs the four checks on every pull request. Run them locally before pushing. A dependency
change is committed together with its `uv.lock`.

## Layout

| Path | What lives there |
| --- | --- |
| `src/tracesheet/model/` | money, units, periods, filed records, the traced number |
| `src/tracesheet/providers/` | typed-in filings, document registry, tie-out checks, market data |
| `src/tracesheet/normalize/` | point-in-time selection, share basis, standardization |
| `src/tracesheet/metrics/` | the catalogue (`catalogue.py`), its computation, the METRICS.md generator |
| `src/tracesheet/multiples/` | the valuation multiples from one closing price |
| `src/tracesheet/evaluate.py` | runs the stages in order |
| `src/tracesheet/storage/` | immutable, content-addressed evaluations |
| `src/tracesheet/report/` | the HTML sheet |
| `src/tracesheet/cli.py` | the command line |
| `data/companies/<id>/` | one company's typed-in filings |
| `tests/` | mirrors `src/`; `tests/fixtures/acme/` is a small synthetic company |

## Rules

These are bug classes, not style preferences.

- **Money is `Decimal` with a currency.** Never a float, never an amount without a currency.
  Figures in data files are quoted text. See
  [0001](docs/decisions/0001-decimal-money.md).
- **Every number carries provenance.** Derive values only through the traced operations in
  `tracesheet.provenance`. A number that cannot be traced to a filed line or an observation
  is a bug. A value that cannot be computed is `NotMeaningful` with a reason; never impute a
  default or clamp. See [0003](docs/decisions/0003-provenance-on-every-number.md).
- **The sheet describes and never judges.** No thresholds, scores, pass/fail, verdicts or
  judging colours, in code, data or output.
- **Point in time.** An evaluation as of a date uses only what was published by then.
- **Evaluations are immutable.** Never overwrite or delete a stored file. See
  [0002](docs/decisions/0002-immutable-evaluations.md).
- **No vendor data or PDFs in git.** Fetched market data stays in `data/cache/`, documents in
  `data/raw/`; both are gitignored. Commit only figures typed in from public reports, with
  their source. See [0004](docs/decisions/0004-no-vendor-data-in-git.md).
- **Domicile, operating country and listing venue are separate fields.** Do not merge them.
- **Tests first** for a behaviour change, and write fixtures fresh rather than copying real
  data into `tests/`.

## Generated files

Two committed files are generated:

- **`docs/METRICS.md`** is built from `CATALOGUE`, `CAGR_KEYS`, `CAGR_SPANS` and
  `CONVENTIONS` in `src/tracesheet/metrics/catalogue.py`, and the multiples' definitions in
  `src/tracesheet/report/build.py`. A test fails when it drifts. After changing any of them:

  ```sh
  uv run python -m tracesheet.metrics.docs > docs/METRICS.md
  ```

- **`examples/kuehne-nagel.html`** is the rendered sample. After changing the sheet, a
  measure, a convention or the Kühne+Nagel data, render it again by hand; no test compares it, because
  it records the build date and commit:

  ```sh
  uv run tracesheet render kuehne-nagel --as-of 2026-11-09
  ```

  Unset `TRACESHEET_EODHD_TOKEN` first, so the price comes from `data/prices.toml`.

## Commits

Small commits with a subject that says what changed. A pull request says what changed, why,
and how it was verified, with the commands and their output.
