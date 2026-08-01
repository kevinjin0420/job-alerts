from __future__ import annotations

import base64
import importlib
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watch"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
app = importlib.import_module("app")


def _get(path: str) -> dict[str, Any]:
    return {
        "requestContext": {"http": {"method": "GET", "sourceIp": "1.2.3.4"}},
        "rawPath": path,
        "headers": {},
    }


class SpaFallbackTests(unittest.TestCase):
    def test_client_routes_all_serve_index_html(self) -> None:
        """The router owns these paths - the Lambda must not 404 them or a deep link breaks."""
        for path in ("/", "/listings", "/config", "/metrics", "/profile", "/onboarding", "/some/deep/link"):
            with self.subTest(path=path):
                response = app.handler(_get(path), None)
                self.assertEqual(response["statusCode"], 200)
                self.assertTrue(response["headers"]["content-type"].startswith("text/html"))
                self.assertTrue(response["isBase64Encoded"])
                self.assertIn(b'<div id="root">', base64.b64decode(response["body"]))

    def test_index_html_is_not_cached(self) -> None:
        """A cached index.html would keep pointing at the previous deploy's asset hashes."""
        response = app.handler(_get("/listings"), None)
        self.assertEqual(response["headers"]["cache-control"], "no-cache")

    def test_missing_bundle_fails_loudly_rather_than_serving_nothing(self) -> None:
        with patch.object(app, "SPA_INDEX_HTML", None):
            response = app.handler(_get("/listings"), None)
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("frontend bundle missing", json.loads(response["body"])["error"])

    def test_api_paths_are_never_swallowed_by_the_fallback(self) -> None:
        """An unknown /api/ path must reach auth, not render the SPA shell."""
        with patch.object(app, "_authenticate", return_value=None):
            response = app.handler(_get("/api/nonexistent"), None)
        self.assertEqual(response["statusCode"], 401)


class AssetServingTests(unittest.TestCase):
    def test_hashed_assets_are_served_immutably_with_a_real_content_type(self) -> None:
        javascript_assets = [path for path in app.SPA_ASSETS if path.endswith(".js")]
        self.assertTrue(javascript_assets, "build the frontend before running this test")

        response = app.handler(_get(javascript_assets[0]), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["cache-control"], "public, max-age=31536000, immutable")
        self.assertIn("javascript", response["headers"]["content-type"])
        self.assertEqual(base64.b64decode(response["body"]), app.SPA_ASSETS[javascript_assets[0]])

    def test_css_assets_get_a_css_content_type(self) -> None:
        css_assets = [path for path in app.SPA_ASSETS if path.endswith(".css")]
        self.assertTrue(css_assets, "build the frontend before running this test")

        response = app.handler(_get(css_assets[0]), None)
        self.assertEqual(response["headers"]["content-type"], "text/css")

    def test_unknown_asset_path_falls_through_to_the_spa_shell(self) -> None:
        """A stale hash from a previous deploy should land on the app, not a hard error."""
        response = app.handler(_get("/assets/does-not-exist-abc123.js"), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(response["headers"]["content-type"].startswith("text/html"))

    def test_root_public_file_is_served_with_its_real_content_type(self) -> None:
        """favicon.svg must not fall through to the SPA shell like an unmatched route would."""
        self.assertIn("/favicon.svg", app.SPA_ROOT_FILES, "build the frontend before running this test")

        response = app.handler(_get("/favicon.svg"), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["content-type"], "image/svg+xml")
        self.assertEqual(response["headers"]["cache-control"], "public, max-age=3600")
        self.assertEqual(base64.b64decode(response["body"]), app.SPA_ROOT_FILES["/favicon.svg"])


if __name__ == "__main__":
    unittest.main()
