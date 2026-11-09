# Architecture

Tracesheet is a pipeline of stages. Each takes what the previous one produced and returns a
new, frozen value. Input and output sit at the edges: the providers read files at the start,
and storage and the report write them at the end. Normalize, metrics and multiples in between
read no files, no network and no clock. Provenance is not a side channel: it is the type
every number has from the moment it is read.

```
data/companies/<company>/*.toml
        │
        ▼
providers ──── HandLoaded: company, filings, documents, share actions
        │      reconcile: each filing must tie out
        ▼
normalize ──── point-in-time selection, share basis, lines solved from printed ones
        │
        ▼
metrics ────── the catalogue, every year, plus 5- and 10-year compound growth
        │
        ▼
multiples ──── one closing price against the latest fiscal year
        │
        ▼
evaluate ───── assembles one Evaluation
        │
        ├──▶ storage ── write-once, content-addressed files
        └──▶ report ─── build_page → render → one self-contained HTML file
```

`tracesheet.evaluate.evaluate` runs the stages in this order; `tracesheet.cli` wraps it in
three commands: `load`, `evaluate` and `render`.

## The traced number

Everything downstream of the providers computes with `Traced`
(`src/tracesheet/model/traced.py`). A `Traced` is one of two things:

- a **leaf**, with an origin. There are exactly two kinds of origin. `Filed` is a line from
  a company's report and carries the document, its SHA-256, the printed page, the report's
  own label and the publication date. `Observed` is a market fact, such as a closing price
  or an exchange rate, with what was observed, its source and its date.
- a **derived value**, with a transform (add, subtract, negate, multiply, divide, total, mean,
  percent change, growth rate, convert, cross rate) and its inputs.

The validator re-applies the transform to the inputs whenever a derived value is built and
refuses it if the result differs. A number cannot disagree with its own trail. Each node
has a content id, a SHA-256 over its value, unit and origin or inputs, so the same number
with the same trail has the same id on any machine.

Values are typed by unit (`src/tracesheet/model/units.py`): money, money per share, share
counts, ratios and exchange rates. The unit tables decide what may be combined: an amount
divided by a share count is a per-share amount, and an amount plus a ratio is refused.
Money is a `Decimal` with a currency and cannot be built from a float
([0001](decisions/0001-decimal-money.md)).

## Stages

### Providers

`providers/hand_loaded.py` reads one directory per company:

| File | Holds |
| --- | --- |
| `company.toml` | identity: name, listing, ISIN, reporting currency and standard, domicile, fiscal-year end |
| `documents.toml` | the reports the company published, each with its URL and SHA-256 |
| `actions.toml` | share splits and similar actions, confirmed against the issuer's documents |
| any other `.toml` | one filing: period, publication time, figures and, for each line, page and label |

Unknown keys and malformed numbers are refused with the file and line named. Figures are
written as quoted text, so they are read as exact decimals; a bare number is refused.

`providers/reconcile.py` checks each filing ties out: assets equal liabilities plus equity,
subtotals equal the sum of their parts, a part never exceeds its whole, and printed EPS
follows from earnings and the share count. The sums come from
`model/relationships.py`, a table of accounting equations that normalization also uses.

Market data sits behind a second interface (`providers/market/`), because it is observed on a
day rather than filed for a period. `LocalPrices` reads `data/prices.toml` and is the
default. `Eodhd` fetches end-of-day closes when `TRACESHEET_EODHD_TOKEN` is set and keeps
them in a gitignored cache. `Ecb` serves reference exchange rates; the command line does not
call it yet (see the Currency convention in [METRICS.md](METRICS.md)).

### Normalize

`normalize/stage.py` turns filings into comparable years, as of a date:

- **Point in time.** A filing published after `as_of` is ignored. Where a later report
  restates an earlier year, the restated line is used only once it was published, and the
  choice is made line by line.
- **Annual and interim** series are kept apart; gaps are reported and irregular years
  marked.
- **Share basis** (`normalize/shares.py`). Confirmed splits and similar actions that are
  effective by `as_of` divide per-share figures and multiply share counts. The factor is an
  `Observed` leaf naming the action and its document, so it shows in every adjusted figure's
  trail. Amounts of money are never touched.
- **Standardization** (`normalize/standardize.py`). Where exactly one member of an
  accounting equation is missing, it is solved from the others, for example EBITDA from EBIT
  and depreciation. A printed figure is never replaced.

What the stage did, and what it declined to do, is stated in plain-language adjustments on
the result.

### Metrics

`metrics/catalogue.py` defines each measure once: a key, a label, its section and its
formula, plus `CONVENTIONS`, the choices measures share. `metrics/stage.py` computes them in
two passes, first each year's values and then growth from those values. A value that cannot
be computed is `NotMeaningful` with a reason, never zero and never clamped.
[METRICS.md](METRICS.md) is generated from the catalogue.

### Multiples

`multiples/stage.py` sets one closing price against the latest fiscal year: P/E, EV/EBIT,
EV/EBITDA, FCF yield, P/B and dividend yield. It reuses the metrics stage's own values (diluted
EPS, free cash flow, book value per share, net debt) so a multiple and the measure beneath it
follow one convention. The price is an `Observed` leaf, so every multiple's trail ends in the
price, its date and its source as well as in the filings.

### Evaluate

`evaluate.py` runs the stages and returns an `Evaluation`: the company, the as-of moment, the
time of the run, the normalized figures, the metrics, the multiples, the tie-out result of
every filing used and the code version (the package version plus the git commit).

## Storage

`storage/` writes an evaluation as two kinds of file under `data/evaluations/` (gitignored):

```
nodes/ab/ab3f….json                          one traced number, named by its content id
evaluations/<company>/<stamp>-<digest>.json  one manifest per evaluation
```

A node holds its value, unit and either its origin or its transform with input ids. A
manifest is the rest of the evaluation, with each traced number replaced by a reference to
its node. Encoding is deterministic, so the same evaluation always gives the same bytes. A
number shared by many evaluations is stored once. Nothing is ever overwritten or deleted, and
every load re-hashes what it reads ([0002](decisions/0002-immutable-evaluations.md)).

## The sheet

`report/build.py` turns an evaluation into a `Page` (`report/page.py`): every figure
formatted, every table in the sheet's order. It walks each figure's trail down to its leaves.
Each leaf becomes one entry in Sources, keyed by the start of its content id, and each cell
lists the entries beneath it. `report/render.py` fills a Jinja2 template and inlines the
stylesheet and a small script, so the file fetches nothing.

Formatting (`report/format.py`) rounds half to even for display only; stored values keep every
digit.

With the script, selecting a figure opens its trail: every filed line and observation it was
computed from, each linking to Sources. Without the script, a figure links to its first
source. A "last 10 years" toggle hides the older columns.

## Where provenance can be lost, and why it is not

| Boundary | What keeps the trail |
| --- | --- |
| File to model | Each figure becomes a `Filed` leaf carrying its document, hash, page and label |
| Normalization | Restated, adjusted and solved figures are traced operations over leaves |
| Metrics and multiples | Built only with traced arithmetic; a missing input is `NotMeaningful`, not a guess |
| Storage | Nodes are content-addressed and re-hashed on load |
| Sheet | Every cell lists the Sources entries of its leaves |

See [0003](decisions/0003-provenance-on-every-number.md) for the decision behind this.
