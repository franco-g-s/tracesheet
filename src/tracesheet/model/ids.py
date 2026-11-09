"""Typed identifiers. Each is a string underneath, but the type checker keeps them apart,
so a record id cannot be handed to something expecting a company id. How ids are minted is
storage's concern."""

from typing import NewType

CompanyId = NewType("CompanyId", str)
RecordId = NewType("RecordId", str)
