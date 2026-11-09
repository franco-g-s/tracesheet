"""Immutable, content-addressed storage for evaluations: each traced number written once,
each evaluation a manifest that names them, everything re-hashed when it is read."""

from tracesheet.storage.store import Store, StoreError

__all__ = ["Store", "StoreError"]
