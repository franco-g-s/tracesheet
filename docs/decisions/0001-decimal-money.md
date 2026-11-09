# 0001. Money is a decimal with a currency

Date: 2026-11-09. Status: accepted.

## Context

Binary floating point cannot represent most decimal fractions exactly. A margin computed
from float inputs is off in the last digits, and the error compounds through growth rates
and averages. Separately, an amount without a currency is ambiguous the moment a second
currency appears: a share price in euros and a balance sheet in francs would combine
silently.

## Decision

- Every amount is a `Money`: a `decimal.Decimal` and a `Currency`. It cannot be built from a
  float, and arithmetic across two currencies raises an error.
- Share counts are a separate type, so a count cannot be added to an amount.
- Units are checked when numbers are combined: an amount divided by a share count is a
  per-share amount, an amount divided by an amount is a ratio, an amount plus a ratio is
  refused.
- Figures in data files are quoted text, read straight into `Decimal`. The loader refuses a
  bare number, and the TOML writer refuses a float.
- Rounding happens only for display, half to even.

## Consequences

Arithmetic is slower than with floats, which is irrelevant at this size. Conversions between
currencies must be explicit, with the rate as a traced input. Vendor JSON is parsed with every
number as a `Decimal`, so a vendor float never enters the pipeline.
