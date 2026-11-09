"""The traced number: a value that carries its own paper trail.

A ``Traced`` is either a leaf — a figure from a filing, or a market observation — or a value
derived from other traced numbers by one of the operations below. The operation records
itself as the transform, and the validator re-applies it on construction, so the number and
its trail cannot disagree.
"""

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal, DivisionByZero, InvalidOperation
from enum import StrEnum
from functools import cached_property

from pydantic import AwareDatetime, model_validator

from tracesheet.model.base import Model
from tracesheet.model.financial_record import (
    PER_SHARE_LINES,
    FinancialRecord,
    LineItemName,
    RecordRef,
    Source,
)
from tracesheet.model.money import Money, ShareCount
from tracesheet.model.units import (
    DIVIDE,
    MONEY_UNITS,
    MULTIPLY,
    ExchangeRate,
    ProvenanceError,
    Unit,
    UnitMismatchError,
)

Value = Money | Decimal | ShareCount | ExchangeRate


# --- Origins: where a leaf comes from. There are two, and no third. ---


class Filed(Model):
    """A line from a company's own report, copied so the trail stands on its own.

    Everything a reader needs to check the figure by hand: the document (``source.reference``,
    with its SHA-256 fingerprint in ``source.sha256`` when it is a file), the printed ``page``,
    and ``label``, the report's own wording for the line, quoted as printed.
    """

    record: RecordRef
    line_item: LineItemName
    source: Source
    label: str | None = None
    page: int | None = None
    note: str | None = None
    not_printed: bool | None = None
    """True for a line the statement does not print at all, declared at load time: a zero
    with a page to check. Absent otherwise, so no other figure's id moves."""


class Observed(Model):
    """A market fact not in a filing: a share price, an exchange rate."""

    what: str
    source: str
    observed_at: AwareDatetime


Origin = Filed | Observed


class Transform(StrEnum):
    """The operations a derived number can record. Arithmetic only."""

    ADD = "add"
    SUBTRACT = "subtract"
    NEGATE = "negate"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    TOTAL = "total"
    MEAN = "mean"
    PERCENT_CHANGE = "percent_change"
    GROWTH_RATE = "growth_rate"
    CONVERT = "convert"
    CROSS_RATE = "cross_rate"


class Parameter(Model):
    """A structural integer an operation needs — a number of years. Nothing with a meaning
    of its own is a parameter; that is a leaf."""

    name: str
    value: int


class Traced(Model):
    """A number and the trail that produced it: an origin for a leaf, or a transform and its
    inputs for a derived value."""

    value: Value
    unit: Unit
    origin: Origin | None = None
    transform: Transform | None = None
    parameters: tuple[Parameter, ...] = ()
    inputs: tuple["Traced", ...] = ()

    @model_validator(mode="after")
    def _leaf_or_verified_derivation(self) -> "Traced":
        _check_value_matches_unit(self.value, self.unit)
        if (self.origin is None) == (self.transform is None):
            msg = (
                "a traced number is either a leaf with an origin "
                "or a derived value with a transform"
            )
            raise ValueError(msg)
        if self.origin is not None:
            if self.inputs or self.parameters:
                msg = "a leaf has no inputs and no parameters"
                raise ValueError(msg)
            return self
        assert self.transform is not None
        expected_value, expected_unit = _apply(self.transform, self.inputs, self.parameters)
        if expected_unit is not self.unit or expected_value != self.value:
            msg = (
                f"does not recompute: {self.transform} of its inputs gives "
                f"{expected_unit} {expected_value}, not {self.unit} {self.value}"
            )
            raise ValueError(msg)
        return self

    @cached_property
    def id(self) -> str:
        """A fingerprint of the content: same number, same trail, same id — on any machine.

        Absent optional fields of an origin are left out, as storage leaves them out on
        disk, so adding an optional field later does not move every existing id.

        Derived, never stored inside the node: storage keys its node table by it and checks
        the key against a fresh computation on load.
        """
        content: dict[str, object] = {
            "unit": self.unit.value,
            "value": _canonical(self.value),
        }
        if self.origin is not None:
            content["origin"] = {
                "kind": type(self.origin).__name__.lower(),
                **self.origin.model_dump(mode="json", exclude_none=True),
            }
        else:
            assert self.transform is not None
            content["transform"] = self.transform.value
            content["parameters"] = [[p.name, p.value] for p in self.parameters]
            content["inputs"] = [node.id for node in self.inputs]
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return digest[:32]

    # --- Reading the trail ---

    def sources(self) -> tuple[Origin, ...]:
        """Every origin at the bottom of the trail, in order of first appearance."""
        found: list[Origin] = []
        for node in self._walk():
            if node.origin is not None and node.origin not in found:
                found.append(node.origin)
        return tuple(found)

    def explain(self) -> str:
        """The trail as indented text: result first, then what made it, down to the pages."""
        return "\n".join(self._explain_lines(0))

    def _walk(self) -> list["Traced"]:
        nodes = [self]
        for node in self.inputs:
            nodes.extend(node._walk())
        return nodes

    def _explain_lines(self, depth: int) -> list[str]:
        head = f"{'  ' * depth}{self.unit.value} {_canonical(self.value)}  {self._describe()}"
        lines = [head]
        for node in self.inputs:
            lines.extend(node._explain_lines(depth + 1))
        return lines

    def _describe(self) -> str:
        if self.origin is not None:
            return _describe_origin(self.origin)
        assert self.transform is not None
        if not self.parameters:
            return self.transform.value
        params = ", ".join(f"{p.name}={p.value}" for p in self.parameters)
        return f"{self.transform.value} ({params})"

    # --- Arithmetic: the only way to derive a traced number ---

    def __add__(self, other: "Traced") -> "Traced":
        return _derive(Transform.ADD, (self, other))

    def __sub__(self, other: "Traced") -> "Traced":
        return _derive(Transform.SUBTRACT, (self, other))

    def __neg__(self) -> "Traced":
        return _derive(Transform.NEGATE, (self,))

    def __mul__(self, other: "Traced") -> "Traced":
        return _derive(Transform.MULTIPLY, (self, other))

    def __truediv__(self, other: "Traced") -> "Traced":
        return _derive(Transform.DIVIDE, (self, other))


# --- Leaf constructors ---


def trace(record: FinancialRecord, line_item: LineItemName) -> Traced:
    """Lift a filed line item into a traced number."""
    item = next((i for i in record.line_items if i.name is line_item), None)
    if item is None:
        msg = f"record {record.id} has no line item {line_item}"
        raise ProvenanceError(msg)
    if isinstance(item.value, ShareCount):
        unit = Unit.COUNT
    elif line_item in PER_SHARE_LINES:
        unit = Unit.PER_SHARE
    else:
        unit = Unit.AMOUNT
    origin = Filed(
        record=record.ref(),
        line_item=line_item,
        source=record.source,
        label=item.label,
        page=item.page,
        note=item.note,
        not_printed=True if item.not_printed else None,
    )
    return Traced(value=item.value, unit=unit, origin=origin)


def observed(
    value: Value, unit: Unit, *, what: str, source: str, observed_at: AwareDatetime
) -> Traced:
    """A market fact: a share price, an exchange rate. Says where and when it was read."""
    return Traced(
        value=value, unit=unit, origin=Observed(what=what, source=source, observed_at=observed_at)
    )


# --- Operations across several traced numbers ---


def total(*items: Traced) -> Traced:
    """The sum of the items, all in one unit."""
    return _derive(Transform.TOTAL, items)


def mean(*items: Traced) -> Traced:
    """The arithmetic mean of the items, in their own unit."""
    return _derive(Transform.MEAN, items)


def percent_change(first: Traced, last: Traced) -> Traced:
    """``(last - first) / first``, as a ratio."""
    return _derive(Transform.PERCENT_CHANGE, (first, last))


def growth_rate(first: Traced, last: Traced, years: int | None = None) -> Traced:
    """Compound annual growth from ``first`` to ``last``, as a ratio.

    When both are filed figures the number of years is read from their fiscal years, and
    a ``years`` given by hand must agree — the operation refuses a mismatch rather than
    annualising over the wrong span.
    """
    from_filings = _years_between(first, last)
    if from_filings is None and years is None:
        msg = "growth_rate needs `years` when the two ends are not both filed figures"
        raise ProvenanceError(msg)
    if from_filings is not None and years is not None and from_filings != years:
        msg = (
            f"growth_rate was told years={years}, but the filings are {from_filings} "
            f"fiscal years apart"
        )
        raise ProvenanceError(msg)
    span = from_filings if from_filings is not None else years
    assert span is not None
    return _derive(Transform.GROWTH_RATE, (first, last), (Parameter(name="years", value=span),))


def convert(amount: Traced, rate: Traced) -> Traced:
    """``amount`` in the rate's quote currency, at an observed exchange rate."""
    return _derive(Transform.CONVERT, (amount, rate))


def cross_rate(quote_per_base: Traced, other_per_base: Traced) -> Traced:
    """From CHF per EUR and USD per EUR, CHF per USD: the shared base cancels.

    The European Central Bank publishes every rate against the euro, so a franc-dollar rate
    is a cross of two of its rates, and the trail names both.
    """
    return _derive(Transform.CROSS_RATE, (quote_per_base, other_per_base))


# --- Internals: applying a transform, and checking units ---


def _derive(
    transform: Transform, inputs: Sequence[Traced], parameters: tuple[Parameter, ...] = ()
) -> Traced:
    if not all(isinstance(node, Traced) for node in inputs):
        msg = f"{transform} works on traced numbers only, never on bare numbers"
        raise TypeError(msg)
    value, unit = _apply(transform, tuple(inputs), parameters)
    return Traced(
        value=value, unit=unit, transform=transform, parameters=parameters, inputs=tuple(inputs)
    )


def _apply(
    transform: Transform, inputs: tuple[Traced, ...], parameters: tuple[Parameter, ...]
) -> tuple[Value, Unit]:
    if not inputs:
        msg = f"{transform} needs at least one input"
        raise ProvenanceError(msg)
    try:
        return _APPLY[transform](inputs, _params(parameters))
    except (DivisionByZero, ZeroDivisionError) as error:
        msg = f"{transform}: division by zero"
        raise ProvenanceError(msg) from error
    except InvalidOperation as error:
        msg = f"{transform}: the arithmetic is undefined for these values ({error})"
        raise ProvenanceError(msg) from error


def _params(parameters: tuple[Parameter, ...]) -> dict[str, int]:
    return {p.name: p.value for p in parameters}


def _magnitude(node: Traced) -> Decimal:
    value = node.value
    if isinstance(value, Money):
        return value.amount
    if isinstance(value, ShareCount):
        return value.count
    if isinstance(value, ExchangeRate):
        return value.rate
    return value


def _rebuild(unit: Unit, magnitude: Decimal, like: Value) -> Value:
    """A value of ``unit`` with this magnitude, taking currency (or pair) from ``like``."""
    if unit in MONEY_UNITS:
        assert isinstance(like, Money)
        return Money(amount=magnitude, currency=like.currency)
    if unit is Unit.COUNT:
        return ShareCount(count=magnitude)
    if unit is Unit.EXCHANGE_RATE:
        assert isinstance(like, ExchangeRate)
        return ExchangeRate(rate=magnitude, base=like.base, quote=like.quote)
    return magnitude


def _same_unit(transform: Transform, inputs: tuple[Traced, ...]) -> Unit:
    first = inputs[0]
    for node in inputs[1:]:
        if node.unit is not first.unit:
            msg = f"{transform}: cannot combine {first.unit} with {node.unit}"
            raise UnitMismatchError(msg)
        if node.value != first.value and _label(node.value) != _label(first.value):
            msg = f"{transform}: cannot combine {_label(first.value)} with {_label(node.value)}"
            raise UnitMismatchError(msg)
    return first.unit


def _label(value: Value) -> str:
    """The currency or pair a value is in, for mismatch messages. Empty for a ratio."""
    if isinstance(value, Money):
        return value.currency.value
    if isinstance(value, ExchangeRate):
        return f"{value.quote}/{value.base}"
    return ""


def _check_value_matches_unit(value: Value, unit: Unit) -> None:
    expected: type[object] = {
        Unit.AMOUNT: Money,
        Unit.PER_SHARE: Money,
        Unit.RATIO: Decimal,
        Unit.COUNT: ShareCount,
        Unit.EXCHANGE_RATE: ExchangeRate,
    }[unit]
    if not isinstance(value, expected):
        msg = f"a {unit} holds a {expected.__name__}, not a {type(value).__name__}"
        raise ValueError(msg)


def _exactly(transform: Transform, inputs: tuple[Traced, ...], n: int) -> None:
    if len(inputs) != n:
        msg = f"{transform} takes exactly {n} inputs, got {len(inputs)}"
        raise ProvenanceError(msg)


def _add(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.ADD, inputs, 2)
    unit = _same_unit(Transform.ADD, inputs)
    return _rebuild(unit, _magnitude(inputs[0]) + _magnitude(inputs[1]), inputs[0].value), unit


def _subtract(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.SUBTRACT, inputs, 2)
    unit = _same_unit(Transform.SUBTRACT, inputs)
    return _rebuild(unit, _magnitude(inputs[0]) - _magnitude(inputs[1]), inputs[0].value), unit


def _negate(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.NEGATE, inputs, 1)
    node = inputs[0]
    return _rebuild(node.unit, -_magnitude(node), node.value), node.unit


def _multiply(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.MULTIPLY, inputs, 2)
    a, b = inputs
    unit = MULTIPLY.get((a.unit, b.unit))
    if unit is None:
        msg = f"multiply: {a.unit} times {b.unit} is not a thing"
        raise UnitMismatchError(msg)
    like = a.value if a.unit in MONEY_UNITS else b.value
    return _rebuild(unit, _magnitude(a) * _magnitude(b), like), unit


def _divide(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.DIVIDE, inputs, 2)
    a, b = inputs
    unit = DIVIDE.get((a.unit, b.unit))
    if unit is None:
        msg = f"divide: {a.unit} by {b.unit} is not a thing"
        raise UnitMismatchError(msg)
    if (
        isinstance(a.value, Money)
        and isinstance(b.value, Money)
        and a.value.currency is not b.value.currency
    ):
        msg = f"divide: {a.value.currency} by {b.value.currency} — convert first"
        raise UnitMismatchError(msg)
    return _rebuild(unit, _magnitude(a) / _magnitude(b), a.value), unit


def _total(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    unit = _same_unit(Transform.TOTAL, inputs)
    return _rebuild(unit, sum((_magnitude(n) for n in inputs), Decimal(0)), inputs[0].value), unit


def _mean(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    unit = _same_unit(Transform.MEAN, inputs)
    magnitudes = [_magnitude(n) for n in inputs]
    return _rebuild(unit, sum(magnitudes, Decimal(0)) / len(magnitudes), inputs[0].value), unit


def _percent_change(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.PERCENT_CHANGE, inputs, 2)
    _same_unit(Transform.PERCENT_CHANGE, inputs)
    first, last = (_magnitude(n) for n in inputs)
    return (last - first) / first, Unit.RATIO


def _growth_rate(inputs: tuple[Traced, ...], params: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.GROWTH_RATE, inputs, 2)
    _same_unit(Transform.GROWTH_RATE, inputs)
    years = params.get("years")
    if years is None or years <= 0:
        msg = "growth_rate needs a positive number of years"
        raise ProvenanceError(msg)
    first, last = (_magnitude(n) for n in inputs)
    if first <= 0 or last <= 0:
        msg = f"growth_rate is undefined from {first} to {last}: both must be positive"
        raise ProvenanceError(msg)
    return (last / first) ** (Decimal(1) / Decimal(years)) - Decimal(1), Unit.RATIO


def _convert(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.CONVERT, inputs, 2)
    amount, rate = inputs
    if amount.unit not in MONEY_UNITS or not isinstance(rate.value, ExchangeRate):
        msg = f"convert takes an amount and an exchange rate, not {amount.unit} and {rate.unit}"
        raise UnitMismatchError(msg)
    assert isinstance(amount.value, Money)
    if amount.value.currency is not rate.value.base:
        msg = (
            f"convert: the amount is in {amount.value.currency} "
            f"but the rate is per {rate.value.base}"
        )
        raise UnitMismatchError(msg)
    converted = Money(amount=amount.value.amount * rate.value.rate, currency=rate.value.quote)
    return converted, amount.unit


def _cross_rate(inputs: tuple[Traced, ...], _: dict[str, int]) -> tuple[Value, Unit]:
    _exactly(Transform.CROSS_RATE, inputs, 2)
    a, b = inputs
    if not (isinstance(a.value, ExchangeRate) and isinstance(b.value, ExchangeRate)):
        msg = f"cross_rate takes two exchange rates, not {a.unit} and {b.unit}"
        raise UnitMismatchError(msg)
    if a.value.base is not b.value.base:
        msg = f"cross_rate: the rates must share a base, not {a.value.base} and {b.value.base}"
        raise UnitMismatchError(msg)
    if a.value.quote is b.value.quote:
        msg = "cross_rate: the two rates quote the same currency; nothing to cross"
        raise UnitMismatchError(msg)
    crossed = ExchangeRate(
        rate=a.value.rate / b.value.rate, base=b.value.quote, quote=a.value.quote
    )
    return crossed, Unit.EXCHANGE_RATE


_APPLY = {
    Transform.ADD: _add,
    Transform.SUBTRACT: _subtract,
    Transform.NEGATE: _negate,
    Transform.MULTIPLY: _multiply,
    Transform.DIVIDE: _divide,
    Transform.TOTAL: _total,
    Transform.MEAN: _mean,
    Transform.PERCENT_CHANGE: _percent_change,
    Transform.GROWTH_RATE: _growth_rate,
    Transform.CONVERT: _convert,
    Transform.CROSS_RATE: _cross_rate,
}


def _years_between(first: Traced, last: Traced) -> int | None:
    """Fiscal years apart, when both are filed figures; else None."""
    if not (isinstance(first.origin, Filed) and isinstance(last.origin, Filed)):
        return None
    span = last.origin.record.period.fiscal_year - first.origin.record.period.fiscal_year
    if span <= 0:
        msg = (
            f"growth_rate runs forwards: {first.origin.record.period.fiscal_year} to "
            f"{last.origin.record.period.fiscal_year} is not a positive span"
        )
        raise ProvenanceError(msg)
    return span


def _canonical(value: Value) -> str:
    """One spelling per value, so equal numbers hash equally: ``1.0`` and ``1`` agree."""
    if isinstance(value, Money):
        return f"{_plain(value.amount)} {value.currency.value}"
    if isinstance(value, ShareCount):
        return f"{_plain(value.count)} shares"
    if isinstance(value, ExchangeRate):
        return f"{_plain(value.rate)} {value.quote.value}/{value.base.value}"
    return _plain(value)


def _plain(number: Decimal) -> str:
    normalized = number.normalize()
    return format(normalized, "f") if normalized.is_finite() else str(normalized)


def _describe_origin(origin: Origin) -> str:
    if isinstance(origin, Filed):
        parts = [origin.line_item.value, f"FY{origin.record.period.fiscal_year}"]
        if origin.label is not None:
            parts.append(
                f'"{origin.label}"' + (f" p.{origin.page}" if origin.page is not None else "")
            )
        parts.append(origin.source.reference)
        return " · ".join(parts)
    return f"observed: {origin.what} · {origin.source} · {origin.observed_at.date().isoformat()}"
