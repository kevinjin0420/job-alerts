from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

from botocore.exceptions import ClientError

os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watch"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
app = importlib.import_module("app")

_CLIENT_ERROR = ClientError({"Error": {"Code": "NotAuthorizedException"}}, "InitiateAuth")


class TokensFromAuthResultTests(unittest.TestCase):
    def test_includes_refresh_token_when_cognito_issues_one(self) -> None:
        tokens = app._tokens_from_auth_result(
            {"AccessToken": "access-1", "ExpiresIn": 3600, "RefreshToken": "refresh-1"}
        )
        self.assertEqual(tokens, {"access_token": "access-1", "expires_in": 3600, "refresh_token": "refresh-1"})

    def test_omits_refresh_token_on_a_refresh_result(self) -> None:
        """REFRESH_TOKEN_AUTH returns no RefreshToken - the client keeps the one it already stored."""
        tokens = app._tokens_from_auth_result({"AccessToken": "access-2", "ExpiresIn": 3600})
        self.assertEqual(tokens, {"access_token": "access-2", "expires_in": 3600})
        self.assertNotIn("refresh_token", tokens)


class HandleRefreshTests(unittest.TestCase):
    def test_rejects_a_missing_refresh_token_without_calling_cognito(self) -> None:
        with patch.object(app.cognito_client, "initiate_auth") as initiate_auth:
            response = app._handle_refresh({}, "1.2.3.4")
        self.assertEqual(response["statusCode"], 400)
        initiate_auth.assert_not_called()

    def test_exchanges_a_refresh_token_for_a_fresh_access_token(self) -> None:
        auth_result = {"AuthenticationResult": {"AccessToken": "access-new", "ExpiresIn": 3600}}
        with patch.object(app.cognito_client, "initiate_auth", return_value=auth_result) as initiate_auth:
            with patch.object(app, "_clear_failed_auth") as clear_failed_auth:
                response = app._handle_refresh({"refresh_token": "refresh-1"}, "1.2.3.4")

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), {"access_token": "access-new", "expires_in": 3600})
        clear_failed_auth.assert_called_once_with("1.2.3.4")

        kwargs: dict[str, Any] = initiate_auth.call_args.kwargs
        self.assertEqual(kwargs["AuthFlow"], "REFRESH_TOKEN_AUTH")
        self.assertEqual(kwargs["AuthParameters"], {"REFRESH_TOKEN": "refresh-1"})

    def test_a_rejected_refresh_token_counts_against_the_per_ip_budget(self) -> None:
        """Otherwise the refresh endpoint is an unmetered oracle for guessing tokens."""
        with patch.object(app.cognito_client, "initiate_auth", side_effect=_CLIENT_ERROR):
            with patch.object(app, "_record_failed_auth") as record_failed_auth:
                response = app._handle_refresh({"refresh_token": "bad"}, "1.2.3.4")

        self.assertEqual(response["statusCode"], 401)
        record_failed_auth.assert_called_once_with("1.2.3.4")


class RefreshRouteTests(unittest.TestCase):
    @staticmethod
    def _event(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "requestContext": {"http": {"method": "POST", "sourceIp": "1.2.3.4"}},
            "rawPath": "/api/refresh",
            "headers": {},
            "body": json.dumps(body),
        }

    def test_route_needs_no_bearer_token(self) -> None:
        auth_result = {"AuthenticationResult": {"AccessToken": "access-new", "ExpiresIn": 3600}}
        with patch.object(app.cognito_client, "initiate_auth", return_value=auth_result):
            with patch.object(app, "_is_rate_limited", return_value=False):
                with patch.object(app, "_clear_failed_auth"):
                    with patch.object(app, "_authenticate") as authenticate:
                        response = app.handler(self._event({"refresh_token": "refresh-1"}), None)

        self.assertEqual(response["statusCode"], 200)
        authenticate.assert_not_called()

    def test_route_is_rate_limited(self) -> None:
        with patch.object(app, "_is_rate_limited", return_value=True):
            with patch.object(app.cognito_client, "initiate_auth") as initiate_auth:
                response = app.handler(self._event({"refresh_token": "refresh-1"}), None)

        self.assertEqual(response["statusCode"], 429)
        initiate_auth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
