from tracesheet.model import RELATIONSHIPS, LineItemName


def test_every_relationship_names_only_line_items() -> None:
    for relationship in RELATIONSHIPS:
        for member in relationship.members:
            assert isinstance(member, LineItemName)


def test_no_line_is_its_own_part() -> None:
    for relationship in RELATIONSHIPS:
        parts = (*relationship.add, *relationship.subtract)
        assert relationship.total not in parts, relationship.formula()


def test_the_balance_sheet_balances_is_one_of_them() -> None:
    assert any(
        r.formula() == "total_assets = total_liabilities + total_equity" for r in RELATIONSHIPS
    )
