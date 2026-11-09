"""The base every model object inherits, and the shared error vocabulary.

Every object in ``tracesheet.model`` is strict (no silent type coercion — a float is never
quietly turned into a decimal), frozen (built once, never changed) and closed (an unknown
field is an error, not a typo that vanishes).
"""

from pydantic import BaseModel, ConfigDict
from pydantic_core import PydanticCustomError

CHAIN_RUNS_BACKWARDS = "chain_runs_backwards"
"""The error type raised when dates run the wrong way, such as a restatement filed before
the filing it restates. Distinct so a caller can tell it from other validation errors."""


class Model(BaseModel):
    """Strict, frozen, closed. Inherit this; never ``BaseModel`` directly."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def chain_runs_backwards(message: str) -> PydanticCustomError:
    """Build the error for a chain that runs backwards. Raise it inside a validator."""
    return PydanticCustomError(CHAIN_RUNS_BACKWARDS, message)
