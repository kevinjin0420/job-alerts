from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.render import RenderError, RenderSource


def _invoke_response(payload: dict[str, object], *, function_error: bool = False) -> dict[str, object]:
    class _Payload:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

    response: dict[str, object] = {"Payload": _Payload(json.dumps(payload).encode("utf-8"))}
    if function_error:
        response["FunctionError"] = "Unhandled"
    return response


class RenderSourceFetchTests(unittest.TestCase):
    def test_parses_card_style_listings_and_dedupes(self) -> None:
        rendered_html = (
            '<a href="/profile/job_details/771948392580541">'
            '<div><h3>Research Scientist Intern, AI/ML</h3></div>'
            '<span>Zurich, Switzerland</span></a>'
            '<a href="/profile/job_details/771948392580541"><h3>Research Scientist Intern, AI/ML</h3></a>'
            '<a href="/about">About Example</a>'
        )
        source = RenderSource("Example", "https://example.com/careers", "intern")
        with patch("sources.render._lambda_client.invoke", return_value=_invoke_response({"html": rendered_html})):
            listings = source.fetch()

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Research Scientist Intern, AI/ML")
        self.assertEqual(listings[0].url, "https://example.com/profile/job_details/771948392580541")
        self.assertEqual(listings[0].source, "renderer:Example:intern")

    def test_function_error_raises_render_error(self) -> None:
        source = RenderSource("Example", "https://example.com/careers", "intern")
        with patch(
            "sources.render._lambda_client.invoke",
            return_value=_invoke_response({"errorMessage": "navigation timeout"}, function_error=True),
        ):
            with self.assertRaises(RenderError):
                source.fetch()

    def test_name_uses_company_and_job_type(self) -> None:
        source = RenderSource("Example Co", "https://example.com/careers", "newgrad")
        self.assertEqual(source.name, "renderer:Example Co:newgrad")


if __name__ == "__main__":
    unittest.main()
