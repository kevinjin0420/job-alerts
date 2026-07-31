from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from sources.base import MAX_FETCH_ATTEMPTS, fetch_url, looks_like_job_posting_url


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


if __name__ == "__main__":
    unittest.main()
