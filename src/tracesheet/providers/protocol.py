"""The one interface every source of filed figures sits behind."""

from typing import Protocol, runtime_checkable

from tracesheet.model import CompanyId, FinancialRecord


@runtime_checkable
class Provider(Protocol):
    """Anything with these members is a provider; there is no base class to inherit."""

    name: str

    def companies(self) -> tuple[CompanyId, ...]:
        """The companies this source has figures for."""
        ...

    def financial_records(self, company: CompanyId) -> tuple[FinancialRecord, ...]:
        """Every record this source holds for one company, as filed, restatements included."""
        ...
