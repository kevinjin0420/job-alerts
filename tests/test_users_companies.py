from __future__ import annotations

import unittest
from unittest.mock import patch

import users


def _company(name: str) -> dict[str, object]:
    return users._wrap_item({"company_name": name, "source_kind": "greenhouse"})


class ListCompaniesSortOrderTests(unittest.TestCase):
    """A plain scan's order is arbitrary (DynamoDB's internal partition layout, not
    insertion order) - made both the admin Sources page and the ConfigPage company
    picker hard to scan for one company."""

    def test_returned_alphabetically_case_insensitive(self) -> None:
        items = [_company(name) for name in ["Zillow", "amazon", "Airbnb", "netflix"]]
        with patch.object(users._dynamodb, "scan", return_value={"Items": items}):
            result = users.list_companies()

        self.assertEqual([entry["company_name"] for entry in result], ["Airbnb", "amazon", "netflix", "Zillow"])


if __name__ == "__main__":
    unittest.main()
