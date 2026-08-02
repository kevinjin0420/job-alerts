from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.base import RENDERED_DESCRIPTION_MAX_CHARS
from sources.render import RenderError, RenderSource, fetch_render_description


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


class FetchRenderDescriptionTests(unittest.TestCase):
    def test_strips_html_from_rendered_page(self) -> None:
        rendered_html = "<nav>Example</nav><main><p>Great role.</p></main>"
        with patch("sources.render._lambda_client.invoke", return_value=_invoke_response({"html": rendered_html})):
            description = fetch_render_description("https://example.com/job/1")

        self.assertEqual(description, "Example Great role.")

    def test_truncates_very_long_pages(self) -> None:
        rendered_html = f"<p>{'x' * (RENDERED_DESCRIPTION_MAX_CHARS + 500)}</p>"
        with patch("sources.render._lambda_client.invoke", return_value=_invoke_response({"html": rendered_html})):
            description = fetch_render_description("https://example.com/job/1")

        assert description is not None
        self.assertEqual(len(description), RENDERED_DESCRIPTION_MAX_CHARS)

    def test_function_error_returns_none_instead_of_raising(self) -> None:
        with patch(
            "sources.render._lambda_client.invoke",
            return_value=_invoke_response({"errorMessage": "navigation timeout"}, function_error=True),
        ):
            self.assertIsNone(fetch_render_description("https://example.com/job/1"))


if __name__ == "__main__":
    unittest.main()
