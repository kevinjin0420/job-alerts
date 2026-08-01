from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
app = importlib.import_module("app")


class AdminUsersQueryCountTests(unittest.TestCase):
    def test_query_count_is_companies_times_job_types(self) -> None:
        users = [{"user_id": "a@example.com"}, {"user_id": "b@example.com"}]
        configs = {
            "a@example.com": {"companies": ["Amazon", "Meta", "Oracle"], "job_types": ["intern", "newgrad"]},
            "b@example.com": {"companies": ["Nvidia"]},
        }
        with patch.object(app, "list_all_users", return_value=users):
            with patch.object(app, "load_user_config", side_effect=lambda user_id: configs[user_id]):
                response = app._handle_admin("GET", "/api/admin/users", {}, "admin@example.com")

        body = json.loads(response["body"])
        result_by_id = {user["user_id"]: user for user in body["users"]}
        self.assertEqual(result_by_id["a@example.com"]["query_count"], 6)
        # No job_types configured falls back to the single default ("intern"), so 1 company x 1 job type.
        self.assertEqual(result_by_id["b@example.com"]["query_count"], 1)


if __name__ == "__main__":
    unittest.main()
