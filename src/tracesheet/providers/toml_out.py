"""A small TOML writer for the files this package rewrites, such as the document registry.

The standard library reads TOML but does not write it. This writes the subset the package
needs (scalars, inline tables, arrays of tables) and refuses a float, so a number reaches a
file only as quoted text that ``Decimal`` reads back exactly.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal


def emit_toml(table: Mapping[str, object]) -> str:
    """Render a mapping as TOML. ``None`` values are left out; a binary fraction is refused."""
    lines: list[str] = []
    arrays: list[tuple[str, Sequence[Mapping[str, object]]]] = []
    for key, value in table.items():
        if value is None:
            continue
        tables = _array_of_tables(value)
        if tables is not None:
            arrays.append((key, tables))
            continue
        lines.append(f"{key} = {_value(key, value)}")
    for key, items in arrays:
        for item in items:
            lines.append("")
            lines.append(f"[[{key}]]")
            for sub_key, sub_value in item.items():
                if sub_value is None:
                    continue
                lines.append(f"{sub_key} = {_value(sub_key, sub_value)}")
    return "\n".join(lines) + "\n"


def _value(key: str, value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | date | datetime):
        return _temporal_or_int(key, value)
    if isinstance(value, Decimal | str):
        return _quote(format(value, "f") if isinstance(value, Decimal) else value)
    if isinstance(value, Mapping):
        inner = ", ".join(f"{k} = {_value(k, v)}" for k, v in value.items() if v is not None)
        return "{ " + inner + " }"
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            return "[" + ", ".join(str(item) for item in value) + "]"  # page numbers
        if not all(isinstance(item, str) for item in value):
            msg = f"{key}: an inline array holds strings or whole numbers only"
            raise TypeError(msg)
        return "[" + ", ".join(_quote(str(item)) for item in value) + "]"
    # Anything else, a float above all, is refused: a number reaches a file as text only.
    msg = f"{key}: cannot write a {type(value).__name__} to TOML; pass a Decimal or text"
    raise TypeError(msg)


def _temporal_or_int(key: str, value: int | date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            msg = f"{key}: a datetime must carry a timezone"
            raise TypeError(msg)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _array_of_tables(value: object) -> list[Mapping[str, object]] | None:
    """The items, when ``value`` is a non-empty sequence of mappings; else None."""
    if isinstance(value, str | bytes) or not isinstance(value, Sequence) or not value:
        return None
    items: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        items.append(item)
    return items
