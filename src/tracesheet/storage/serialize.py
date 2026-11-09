"""Turning an evaluation into files and back.

Two kinds of file. A **node** is one traced number: its value, its unit, and either its
origin (for a figure read from a filing or the market) or its operation, with its inputs
named by id. A **manifest** is the rest of the evaluation, with every traced number
replaced by ``{"$traced": "<id>"}``. A number used in many places is written once.

Both encodings are deterministic: the same evaluation always gives the same bytes. That is
what lets the store name files by their content and refuse to overwrite one.
"""

import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, TypeAdapter
from pydantic_core import to_jsonable_python

from tracesheet.model import (
    Evaluation,
    ExchangeRate,
    Filed,
    Money,
    Observed,
    ShareCount,
    Traced,
    Transform,
    Unit,
)
from tracesheet.model.traced import Parameter, Value

NODE_REFERENCE = "$traced"
"""The key that marks a traced number in a manifest. No model field can be called this."""

_VALUE_TYPE: dict[Unit, type[Money] | type[Decimal] | type[ShareCount] | type[ExchangeRate]] = {
    Unit.AMOUNT: Money,
    Unit.PER_SHARE: Money,
    Unit.RATIO: Decimal,
    Unit.COUNT: ShareCount,
    Unit.EXCHANGE_RATE: ExchangeRate,
}
_ORIGIN_TYPE: dict[str, type[Filed] | type[Observed]] = {"filed": Filed, "observed": Observed}
_DECIMAL = TypeAdapter(Decimal)


class SerializationError(ValueError):
    """A file does not describe what it claims to. The message says which part."""


# --- Nodes ---


def collect_nodes(value: object, into: dict[str, Traced] | None = None) -> dict[str, Traced]:
    """Every traced number reachable from ``value``, inputs included, keyed by id."""
    found: dict[str, Traced] = {} if into is None else into
    if isinstance(value, Traced):
        if value.id not in found:
            found[value.id] = value
            for node in value.inputs:
                collect_nodes(node, found)
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            collect_nodes(getattr(value, name), found)
    elif isinstance(value, Mapping):
        for item in value.values():
            collect_nodes(item, found)
    elif isinstance(value, tuple | list):
        for item in value:
            collect_nodes(item, found)
    return found


def node_to_dict(node: Traced) -> dict[str, Any]:
    """One traced number, its inputs by id. Optional origin fields that are absent are left
    out, exactly as the node's id leaves them out."""
    data: dict[str, Any] = {
        "value": to_jsonable_python(node.value),
        "unit": node.unit.value,
    }
    if node.origin is not None:
        data["origin"] = {
            "kind": type(node.origin).__name__.lower(),
            **node.origin.model_dump(mode="json", exclude_none=True),
        }
    else:
        assert node.transform is not None
        data["transform"] = node.transform.value
        data["parameters"] = [p.model_dump(mode="json") for p in node.parameters]
        data["inputs"] = [child.id for child in node.inputs]
    return data


def input_ids(data: Mapping[str, Any]) -> tuple[str, ...]:
    """The ids a node file names as its inputs."""
    inputs = data.get("inputs", [])
    if not isinstance(inputs, list) or not all(isinstance(i, str) for i in inputs):
        msg = "inputs must be a list of node ids"
        raise SerializationError(msg)
    return tuple(inputs)


def node_from_dict(data: Mapping[str, Any], inputs: tuple[Traced, ...]) -> Traced:
    """Rebuild a traced number from its file and its already rebuilt inputs.

    Each part is parsed from JSON with the model's own strict rules, and the ``Traced``
    validator then recomputes a derived value from its inputs, so a file whose value and
    trail disagree is refused here. Raises ``SerializationError`` or a pydantic
    ``ValidationError``.
    """
    try:
        unit = Unit(data["unit"])
        value_json = json.dumps(data["value"])
    except (KeyError, ValueError, TypeError) as error:
        msg = f"no readable value and unit ({error})"
        raise SerializationError(msg) from error
    kind = _VALUE_TYPE[unit]
    value: Value = (
        _DECIMAL.validate_json(value_json, strict=True)
        if kind is Decimal
        else kind.model_validate_json(value_json)  # type: ignore[union-attr]
    )
    if "origin" in data:
        origin_data = dict(data["origin"])
        origin_type = _ORIGIN_TYPE.get(origin_data.pop("kind", None))
        if origin_type is None:
            msg = "the origin is neither filed nor observed"
            raise SerializationError(msg)
        if inputs or "transform" in data:
            msg = "a node read from a source has no operation and no inputs"
            raise SerializationError(msg)
        return Traced(
            value=value, unit=unit, origin=origin_type.model_validate_json(json.dumps(origin_data))
        )
    try:
        transform = Transform(data["transform"])
    except (KeyError, ValueError) as error:
        msg = f"neither an origin nor a known operation ({error})"
        raise SerializationError(msg) from error
    parameters = tuple(
        Parameter.model_validate_json(json.dumps(p)) for p in data.get("parameters", [])
    )
    return Traced(value=value, unit=unit, transform=transform, parameters=parameters, inputs=inputs)


def node_bytes(node: Traced) -> bytes:
    """A node file's exact content: keys sorted, so field order never changes the bytes."""
    return (json.dumps(node_to_dict(node), sort_keys=True, ensure_ascii=False) + "\n").encode()


# --- Manifests ---


def manifest_to_dict(evaluation: Evaluation) -> dict[str, Any]:
    """The evaluation as plain JSON data, every traced number replaced by its id.

    Mappings keep their order, so the measures come back in the order the catalogue gave
    them. That order is deterministic, so the bytes are too.
    """
    encoded = _encode(evaluation)
    assert isinstance(encoded, dict)
    return encoded


def manifest_bytes(evaluation: Evaluation) -> bytes:
    """A manifest file's exact content."""
    return (json.dumps(manifest_to_dict(evaluation), indent=1, ensure_ascii=False) + "\n").encode()


def manifest_to_evaluation(data: Any, resolve: Callable[[str], Traced]) -> Evaluation:
    """Rebuild an evaluation from its manifest, asking ``resolve`` for each traced number.

    The manifest is plain JSON, so dates and decimals arrive as strings and are converted
    by the models' own types. The caller confirms the result re-encodes to the bytes it
    was read from, which is what rules out any loose reading.
    """
    return Evaluation.model_validate(_decode(data, resolve), strict=False)


def _encode(value: object) -> object:
    if isinstance(value, Traced):
        return {NODE_REFERENCE: value.id}
    if isinstance(value, BaseModel):
        return {name: _encode(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, Mapping):
        return {_key(key): _encode(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_encode(item) for item in value]
    return to_jsonable_python(value)


def _key(key: object) -> str:
    plain = to_jsonable_python(key)
    if not isinstance(plain, str | int):
        msg = f"a mapping key must be text or a whole number, not {type(key).__name__}"
        raise SerializationError(msg)
    return str(plain)


def _decode(value: Any, resolve: Callable[[str], Traced]) -> Any:
    if isinstance(value, dict):
        if NODE_REFERENCE in value:
            node_id = value[NODE_REFERENCE]
            if len(value) != 1 or not isinstance(node_id, str):
                msg = f"a {NODE_REFERENCE!r} reference holds one node id and nothing else"
                raise SerializationError(msg)
            return resolve(node_id)
        return {key: _decode(item, resolve) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item, resolve) for item in value]
    return value
