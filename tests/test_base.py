from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from sources.base import (
    MAX_FETCH_ATTEMPTS,
    _extract_anchor_title,
    fetch_url,
    looks_like_job_posting_url,
    parse_rendered_html_listings,
    strip_html,
)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.com", code, "error", {}, None)


def _mock_response(body: bytes) -> object:
    class _Response:
        status = 200

        def read(self) -> bytes:
            return body

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


class FetchUrlRetryTests(unittest.TestCase):
    """A transient 429/5xx used to fail the whole source immediately - now retried with backoff first."""

    def test_retries_on_429_then_succeeds(self) -> None:
        with patch(
            "sources.base.urllib.request.urlopen", side_effect=[_http_error(429), _mock_response(b"ok")]
        ) as mock_urlopen:
            with patch("sources.base.time.sleep") as mock_sleep:
                body = fetch_url("test", "https://example.com")

        self.assertEqual(body, b"ok")
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    def test_gives_up_after_max_attempts(self) -> None:
        with patch("sources.base.urllib.request.urlopen", side_effect=_http_error(429)) as mock_urlopen:
            with patch("sources.base.time.sleep"):
                with self.assertRaises(urllib.error.HTTPError):
                    fetch_url("test", "https://example.com")

        self.assertEqual(mock_urlopen.call_count, MAX_FETCH_ATTEMPTS)

    def test_non_retryable_status_raises_immediately_without_retrying(self) -> None:
        with patch("sources.base.urllib.request.urlopen", side_effect=_http_error(403)) as mock_urlopen:
            with patch("sources.base.time.sleep") as mock_sleep:
                with self.assertRaises(urllib.error.HTTPError):
                    fetch_url("test", "https://example.com")

        mock_urlopen.assert_called_once()
        mock_sleep.assert_not_called()

    def test_retries_on_read_timeout_then_succeeds(self) -> None:
        with patch(
            "sources.base.urllib.request.urlopen",
            side_effect=[TimeoutError("The read operation timed out"), _mock_response(b"ok")],
        ) as mock_urlopen:
            with patch("sources.base.time.sleep") as mock_sleep:
                body = fetch_url("test", "https://example.com")

        self.assertEqual(body, b"ok")
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    def test_gives_up_after_max_attempts_on_repeated_timeout(self) -> None:
        with patch(
            "sources.base.urllib.request.urlopen", side_effect=TimeoutError("The read operation timed out")
        ) as mock_urlopen:
            with patch("sources.base.time.sleep"):
                with self.assertRaises(TimeoutError):
                    fetch_url("test", "https://example.com")

        self.assertEqual(mock_urlopen.call_count, MAX_FETCH_ATTEMPTS)

    def test_retries_on_url_error(self) -> None:
        with patch(
            "sources.base.urllib.request.urlopen",
            side_effect=[urllib.error.URLError("DNS lookup failed"), _mock_response(b"ok")],
        ) as mock_urlopen:
            with patch("sources.base.time.sleep") as mock_sleep:
                body = fetch_url("test", "https://example.com")

        self.assertEqual(body, b"ok")
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()


class LooksLikeJobPostingUrlTests(unittest.TestCase):
    def test_matches_numeric_path_segment(self) -> None:
        self.assertTrue(looks_like_job_posting_url("https://careers.airbnb.com/positions/7732569/"))

    def test_matches_slug_suffixed_id(self) -> None:
        # Tesla's job URLs suffix the numeric id onto a slug rather than its own path segment.
        self.assertTrue(
            looks_like_job_posting_url(
                "https://www.tesla.com/careers/search/job/ai-engineer-manipulation-optimus-224501"
            )
        )

    def test_matches_letter_prefixed_id_glued_to_slug(self) -> None:
        # ASML's job URLs glue a letter-prefixed id directly onto the slug with no separator (e.g. "-j00348041").
        self.assertTrue(
            looks_like_job_posting_url(
                "https://www.asml.com/en/careers/find-your-job/physics-internship-j00348041"
            )
        )

    def test_matches_with_trailing_query_string(self) -> None:
        self.assertTrue(looks_like_job_posting_url("https://boards.greenhouse.io/company/jobs/7732569?gh_src=abc"))

    def test_rejects_query_only_listing_page(self) -> None:
        self.assertFalse(looks_like_job_posting_url("https://careers.airbnb.com/positions/?_departments=university"))

    def test_rejects_non_numeric_page(self) -> None:
        self.assertFalse(looks_like_job_posting_url("https://www.tesla.com/about"))

    def test_rejects_short_number(self) -> None:
        # Fewer than 4 digits shouldn't count - too likely to be a real word/date fragment.
        self.assertFalse(looks_like_job_posting_url("https://example.com/jobs/42"))


class ExtractAnchorTitleTests(unittest.TestCase):
    def test_flat_text_anchor(self) -> None:
        # The shape rendered-page parsing originally supported, before card-style SPAs.
        html = "Software Engineer Intern"
        self.assertEqual(_extract_anchor_title(html), "Software Engineer Intern")

    def test_nested_heading_anchor(self) -> None:
        # Meta-style: title lives in a heading buried under divs/spans, location/tags as later siblings.
        html = (
            '<div><div><h3 class="x1motxo8">Research Scientist Intern, AI/ML</h3></div></div>'
            '<div><span>Zurich, Switzerland</span><span>AI Research</span></div>'
        )
        self.assertEqual(_extract_anchor_title(html), "Research Scientist Intern, AI/ML")

    def test_decodes_html_entities(self) -> None:
        html = "<h3>FAIR - Language &amp; Multimodal Foundations</h3>"
        self.assertEqual(_extract_anchor_title(html), "FAIR - Language & Multimodal Foundations")

    def test_falls_back_to_full_text_without_heading(self) -> None:
        html = "<span>Data Engineer</span> <span>Intern</span>"
        self.assertEqual(_extract_anchor_title(html), "Data Engineer Intern")


class StripHtmlTests(unittest.TestCase):
    def test_strips_tags_and_collapses_whitespace(self) -> None:
        html = "<p>Who we are</p>\n<p>Stripe is a  financial\ninfrastructure platform.</p>"
        self.assertEqual(strip_html(html), "Who we are Stripe is a financial infrastructure platform.")

    def test_decodes_entities(self) -> None:
        self.assertEqual(strip_html("<p>Engineering &amp; Product</p>"), "Engineering & Product")

    def test_empty_input_returns_empty_string(self) -> None:
        self.assertEqual(strip_html(""), "")

    def test_style_block_contents_are_removed_not_just_the_tags(self) -> None:
        # Regression: a real Tesla page's <style> block CSS survived as "text" until this
        # was added - the tag-stripper alone only removes the <style> tags, not their contents.
        html = "<head><style>.cookie-banner{width:calc(100% - 2px)}</style></head><body><p>Great role.</p></body>"
        self.assertEqual(strip_html(html), "Great role.")

    def test_script_block_contents_are_removed_not_just_the_tags(self) -> None:
        html = '<script>window.dataLayer = window.dataLayer || [];</script><p>Great role.</p>'
        self.assertEqual(strip_html(html), "Great role.")

    def test_hidden_display_none_element_contents_are_removed(self) -> None:
        # Regression: Microsoft embeds a JSON config blob in a hidden <code>, not <script>.
        html = (
            '<code id="branding-data" style="display: none;">{"themeOptions": {"a": "b>c"}}</code>'
            "<p>Great role.</p>"
        )
        self.assertEqual(strip_html(html), "Great role.")

    def test_hidden_element_with_other_attributes_before_style(self) -> None:
        html = '<div data-x="1" style=\'display:none\'>junk</div><p>Great role.</p>'
        self.assertEqual(strip_html(html), "Great role.")


class ParseRenderedHtmlListingsTests(unittest.TestCase):
    def test_parses_card_style_listings_and_dedupes(self) -> None:
        rendered_html = (
            '<a href="/profile/job_details/771948392580541">'
            '<div><h3>Research Scientist Intern, AI/ML</h3></div>'
            '<span>Zurich, Switzerland</span></a>'
            # A repeat of the same href (e.g. a duplicate mobile/desktop card) must be deduped.
            '<a href="/profile/job_details/771948392580541"><h3>Research Scientist Intern, AI/ML</h3></a>'
            # Nav/footer-style link with no numeric id must be dropped.
            '<a href="/about">About Meta</a>'
        )

        listings = parse_rendered_html_listings(
            rendered_html, "https://www.metacareers.com/jobsearch/?roles[0]=Internship", "Meta", "zyte:Meta:intern"
        )

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Research Scientist Intern, AI/ML")
        self.assertEqual(listings[0].url, "https://www.metacareers.com/profile/job_details/771948392580541")
        self.assertEqual(listings[0].source, "zyte:Meta:intern")

    def test_short_titles_are_dropped(self) -> None:
        rendered_html = '<a href="/jobs/771948392580541">Hi</a>'
        listings = parse_rendered_html_listings(rendered_html, "https://example.com/careers", "Example", "render:Example:intern")
        self.assertEqual(listings, [])


if __name__ == "__main__":
    unittest.main()
