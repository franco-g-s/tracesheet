# Metrics

Every measure on the sheet, with the formula it is computed by, and the conventions the
measures share. The sheet describes and does not judge: no measure has a threshold, a
target or a notion of a good or bad value. A value that cannot be computed is shown as
n/m with the reason.

This file is generated from `src/tracesheet/metrics/catalogue.py`. Do not edit it by
hand; regenerate it with `uv run python -m tracesheet.metrics.docs > docs/METRICS.md`.

## Growth

| Measure | Formula |
| --- | --- |
| Revenue | Revenue as filed |
| EBIT | Earnings before interest and taxes, as filed |
| Net income | Profit for the year, including minorities' share, as filed |
| Revenue growth | Revenue: (this year − prior year) ÷ prior year; n/m when the prior year is ≤ 0 |
| EBIT growth | EBIT: (this year − prior year) ÷ prior year; n/m when the prior year is ≤ 0 |
| Net income growth | Net income: (this year − prior year) ÷ prior year; n/m when the prior year is ≤ 0 |
| Diluted EPS growth | Diluted EPS: (this year − prior year) ÷ prior year; n/m when the prior year is ≤ 0 |
| FCF per share growth | FCF per share: (this year − prior year) ÷ prior year; n/m when the prior year is ≤ 0 |

## Profitability

| Measure | Formula |
| --- | --- |
| Gross margin | Gross profit ÷ revenue |
| EBITDA margin | EBITDA ÷ revenue |
| EBIT margin | EBIT ÷ revenue |
| Net margin | Net income ÷ revenue |
| Return on equity | Net income attributable to shareholders ÷ average equity attributable to shareholders (total equity − non-controlling interests) |
| Return on assets | Net income ÷ average total assets |
| Return on invested capital | NOPAT ÷ average invested capital, where NOPAT = EBIT × (1 − income tax ÷ profit before tax) and invested capital = total equity + financial debt + lease liabilities − cash and equivalents |

## Cash generation

| Measure | Formula |
| --- | --- |
| Operating cash flow | Net cash from operating activities, as filed |
| Capex | Purchases of property, plant and equipment + purchases of intangible assets |
| Free cash flow | Operating cash flow − capex |
| FCF conversion | Free cash flow ÷ net income |
| Capex to revenue | Capex ÷ revenue |

## Balance sheet

| Measure | Formula |
| --- | --- |
| Net debt | Financial debt + lease liabilities − cash and equivalents; negative is net cash |
| Net debt to EBITDA | Net debt ÷ EBITDA |
| Equity ratio | Total equity ÷ total assets |
| Current ratio | Current assets ÷ current liabilities |

## Shareholder returns

| Measure | Formula |
| --- | --- |
| Dividend per share | The ordinary dividend for the fiscal year, as proposed |
| Special dividend per share | An extraordinary dividend for the fiscal year, printed apart from the ordinary one |
| Payout ratio | Dividend per share ÷ diluted EPS |
| Share buybacks | Cash paid to buy back the company's own shares, from the cash-flow statement |
| Change in diluted shares | Diluted weighted average shares: (this year − prior year) ÷ prior year |

### Per share

| Measure | Formula |
| --- | --- |
| Diluted EPS | Diluted earnings per share, as filed |
| FCF per share | Free cash flow ÷ diluted weighted average shares |
| Book value per share | Equity attributable to shareholders ÷ year-end shares outstanding |

## Compound annual growth

Over n = 5 and 10 fiscal years, ending in the latest year: (latest year's value ÷ the
value n years earlier)^(1 ÷ n) − 1. Undefined when either value is zero or negative,
or when the earlier year has no figures.

Computed for: Revenue, EBIT, Net income, Diluted EPS, FCF per share.

## Valuation multiples

Set from one closing price against the latest fiscal year. Each states the price, its
date and its source. Without a price the section says so, and the rest of the sheet
still renders.

| Multiple | Formula |
| --- | --- |
| Price to earnings | Share price ÷ diluted EPS |
| EV to EBIT | Enterprise value ÷ EBIT |
| EV to EBITDA | Enterprise value ÷ EBITDA |
| Free cash flow yield | Free cash flow ÷ market capitalisation |
| Price to book | Share price ÷ book value per share |
| Dividend yield | Dividend per share ÷ share price |

## Conventions

| Topic | Convention |
| --- | --- |
| Revenue | The filed top line. Margins divide by it. Gross margin is gross profit ÷ revenue. |
| Capex | Purchases of property, plant and equipment plus purchases of intangible assets, both from the cash-flow statement: the common analyst definition. Both are held as positive outflows; a purchase line filed as negative gives n/m rather than being flipped. Intangible purchases count as zero only where the report prints no such line, or prints one line for both, which is then taken whole; otherwise capex is n/m. Free cash flow = operating cash flow − capex, used consistently in FCF growth, conversion, per share and yield. |
| FCF conversion | Free cash flow ÷ net income, both consolidated. |
| Earnings and equity | Attributable to the parent's shareholders for EPS, return on equity, payout ratio and book value per share. Consolidated (including minorities) for margins, return on assets and FCF conversion. |
| NOPAT | EBIT × (1 − effective tax rate), with effective rate = income tax ÷ profit before tax. Undefined when profit before tax ≤ 0. |
| Invested capital | Total equity + financial debt + lease liabilities − cash and equivalents. Financial debt is the filed total, or else current plus non-current borrowings. Both halves must be filed: a half the company has none of counts as zero only where the record declares it not printed; a half simply missing gives n/m. |
| Lease liabilities | The filed total, or else current plus non-current lease liabilities. A lease line counts as zero only where the record declares it not printed, so the zero is filed with its page; a lease line simply missing gives n/m, whatever the year. Before IFRS 16 (periods beginning before 1 January 2019) the balance sheet carried finance leases only, and those are what such years show. The first IFRS 16 year averages an opening balance with finance leases only against a closing balance with all leases. |
| Averages | Return on equity, on assets and on invested capital use the average of opening and closing balances. The first year shown, and any year after a gap, has no opening balance, so they are undefined there. |
| Net debt | Financial debt + lease liabilities − cash and equivalents. It may be negative (net cash). |
| Shares | Per-share flow figures (diluted EPS and FCF per share) use the diluted weighted average for the year. Book value per share is the exception: like market capitalisation, it uses year-end shares outstanding, net of treasury shares, a balance-sheet point in time, which keeps price-to-book consistent with market capitalisation. Every per-share figure and count is on one share basis across the years. |
| Dividends | Dividend per share is the ordinary dividend for the fiscal year, as proposed. Special dividends are shown separately, as special dividend per share. Payout ratio = ordinary dividend per share ÷ diluted EPS. Buybacks are the cash-flow line. |
| EV | Market capitalisation + financial debt + lease liabilities + minorities − cash and equivalents, from the latest annual balance sheet. |
| Currency | Figures stay in the reporting currency. No exchange rate is fetched: when the share price is in another currency, the multiples are n/m (no exchange rate). A caller may supply a rate from the price's currency into the reporting currency; the price is then converted at it, and the rate is shown and sits in every multiple's trail. |
| Growth | Year on year: (this year − prior year) ÷ prior year. Compound annual growth over 5 and 10 years ends in the latest year. Both are undefined when the starting value is zero or negative; compound growth also when the ending value is. |
| Undefined | A zero or negative denominator, or a missing input, gives n/m with the reason. Nothing is clamped or imputed. |
