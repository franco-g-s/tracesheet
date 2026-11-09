"""The evaluation store: write-once files, named by their content.

Layout under the store's root::

    nodes/ab/ab3f….json                         one traced number per file, named by its id
    evaluations/<company>/<stamp>-<digest>.json one manifest per evaluation

A node's name is its content id, so the same number is stored once however many
evaluations use it. A manifest's name is the moment the evaluation was run (UTC, to the
microsecond) and the first eight hex digits of the SHA-256 of its bytes. Nothing is ever
updated or deleted: saving an evaluation again writes nothing new, and a file that exists
with other content stops the save. Every load re-hashes what it reads.
"""

import hashlib
import json
import re
import stat
from datetime import UTC
from pathlib import Path
from typing import Any

from tracesheet.model import SCHEMA_VERSION, CompanyId, Evaluation, Traced
from tracesheet.storage.serialize import (
    collect_nodes,
    input_ids,
    manifest_bytes,
    manifest_to_evaluation,
    node_bytes,
    node_from_dict,
)

NODES = "nodes"
EVALUATIONS = "evaluations"
_MANIFEST_ID = re.compile(r"\d{8}T\d{12}Z-[0-9a-f]{8}")
_NODE_ID = re.compile(r"[0-9a-f]{32}")
_COMPANY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class StoreError(ValueError):
    """The store refused a save or a load. The message names the file and the reason."""


class Store:
    """Evaluations on disk, each one written once and verified on every read."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- Writing ---

    def save(self, evaluation: Evaluation) -> str:
        """Store an evaluation and return its manifest id.

        The nodes are written before the manifest, so a manifest never names a node that
        is not on disk. Saving the same evaluation twice returns the same id and leaves
        every file as it was.
        """
        company = evaluation.company.id
        _check_company(company)
        for node in collect_nodes(evaluation).values():
            self._write_once(self._node_path(node.id), node_bytes(node))
        content = manifest_bytes(evaluation)
        stamp = evaluation.created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        manifest_id = f"{stamp}-{_digest(content)}"
        self._write_once(self._manifest_dir(company) / f"{manifest_id}.json", content)
        return manifest_id

    # --- Reading ---

    def load(self, manifest_id: str) -> Evaluation:
        """The evaluation saved under ``manifest_id``, every file re-hashed on the way in."""
        if not _MANIFEST_ID.fullmatch(manifest_id):
            msg = f"{manifest_id!r} is not an evaluation id such as 20261109T081500000000Z-1a2b3c4d"
            raise StoreError(msg)
        found = sorted((self.root / EVALUATIONS).glob(f"*/{manifest_id}.json"))
        if not found:
            msg = f"no evaluation {manifest_id} under {self.root / EVALUATIONS}"
            raise StoreError(msg)
        if len(found) > 1:
            msg = f"evaluation {manifest_id} is stored for more than one company: {found}"
            raise StoreError(msg)
        return self._read_manifest(found[0])

    def latest(self, company_id: CompanyId) -> Evaluation | None:
        """The most recently run evaluation of a company, or ``None`` if it has none."""
        _check_company(company_id)
        directory = self._manifest_dir(company_id)
        if not directory.is_dir():
            return None
        manifests = sorted(
            path for path in directory.iterdir() if _MANIFEST_ID.fullmatch(path.stem)
        )
        # The stamp leads the name and has a fixed width, so name order is run order.
        return self._read_manifest(manifests[-1]) if manifests else None

    # --- Internals ---

    def _read_manifest(self, path: Path) -> Evaluation:
        content = _read_bytes(path)
        if not path.stem.endswith(f"-{_digest(content)}"):
            msg = f"{path}: the content does not match the digest in its name; it was altered"
            raise StoreError(msg)
        data = _parse_json(path, content)
        if data.get("schema_version") != SCHEMA_VERSION:
            version = data.get("schema_version")
            msg = f"{path}: schema version {version!r}; this version reads {SCHEMA_VERSION}"
            raise StoreError(msg)
        nodes: dict[str, Traced] = {}
        try:
            evaluation = manifest_to_evaluation(data, lambda node_id: self._node(node_id, nodes))
        except StoreError:
            raise
        except (ValueError, TypeError, KeyError) as error:
            # ValueError covers pydantic's ValidationError and SerializationError.
            msg = f"{path}: {error}"
            raise StoreError(msg) from error
        if evaluation.company.id != path.parent.name:
            msg = f"{path}: holds an evaluation of {evaluation.company.id!r}"
            raise StoreError(msg)
        if manifest_bytes(evaluation) != content:
            msg = f"{path}: does not re-encode to its own bytes; the store did not write it"
            raise StoreError(msg)
        return evaluation

    def _node(self, node_id: str, nodes: dict[str, Traced]) -> Traced:
        """One node, its inputs first, each checked against the id it is filed under."""
        if node_id in nodes:
            return nodes[node_id]
        if not _NODE_ID.fullmatch(node_id):
            msg = f"{node_id!r} is not a node id"
            raise StoreError(msg)
        path = self._node_path(node_id)
        data = _parse_json(path, _read_bytes(path))
        try:
            # Ids are hashes of content that includes the inputs' ids, so inputs cannot
            # lead back to the node that names them; this recursion always ends.
            inputs = tuple(self._node(child, nodes) for child in input_ids(data))
            node = node_from_dict(data, inputs)
        except StoreError:
            raise
        except (ValueError, TypeError, KeyError) as error:
            msg = f"{path}: {error}"
            raise StoreError(msg) from error
        if node.id != node_id:
            msg = f"{path}: the content hashes to {node.id}, not {node_id}; it was altered"
            raise StoreError(msg)
        nodes[node_id] = node
        return node

    def _node_path(self, node_id: str) -> Path:
        return self.root / NODES / node_id[:2] / f"{node_id}.json"

    def _manifest_dir(self, company: CompanyId) -> Path:
        return self.root / EVALUATIONS / company

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        if path.exists():
            if path.read_bytes() == content:
                return
            msg = f"{path}: already exists with other content; nothing here is ever overwritten"
            raise StoreError(msg)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the target and renamed into place, so a crash never leaves a
        # half-written file under a content name. One left by an earlier crash is
        # read-only and incomplete; it is cleared first.
        partial = path.with_name(f".{path.name}.partial")
        partial.unlink(missing_ok=True)
        partial.write_bytes(content)
        partial.chmod(_READ_ONLY)
        partial.replace(path)


def _check_company(company: CompanyId) -> None:
    if not _COMPANY_ID.fullmatch(company):
        msg = f"{company!r} cannot name a directory in the store"
        raise StoreError(msg)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:8]


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as error:
        msg = f"{path}: missing"
        raise StoreError(msg) from error


def _parse_json(path: Path, content: bytes) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        msg = f"{path}: not valid JSON ({error})"
        raise StoreError(msg) from error
    if not isinstance(data, dict):
        msg = f"{path}: not a JSON object"
        raise StoreError(msg)
    return data
