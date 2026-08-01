from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import patch

from classifier import is_good_fit
from llm import MAX_ATTEMPTS, LLMCallError
from sources.base import Listing
from validator import check_is_job_posting


def _listing() -> Listing:
    return Listing(
        source="test", id="1", company_name="Example", title="Intern", locations=["Remote"], url="https://example.com/1"
    )


def _mock_response(body: dict[str, object]) -> object:
    payload = json.dumps(body).encode("utf-8")

    class _Response:
        status = 200

        def read(self) -> bytes:
            return payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


class RetryWithBackoffTests(unittest.TestCase):
    """A truncated/malformed response used to give up after 2 tries - now retries with increasing backoff up to MAX_ATTEMPTS before giving up, so it never fails open just because the model glitched once."""

    def test_retries_with_increasing_backoff_then_succeeds(self) -> None:
        good_response = _mock_response(
            {"choices": [{"message": {"content": json.dumps({"fits": True, "reason": "good match"})}}], "usage": {}}
        )
        with patch(
            "llm.urllib.request.urlopen",
            side_effect=[urllib.error.HTTPError("https://openrouter.ai", 429, "busy", {}, None), good_response],
        ) as mock_urlopen:
            with patch("llm.time.sleep") as mock_sleep:
                result = is_good_fit("fake-key", "fake-model", "must be remote", _listing())

        self.assertTrue(result.fits)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    def test_gives_up_after_max_attempts(self) -> None:
        with patch(
            "llm.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("https://openrouter.ai", 429, "busy", {}, None),
        ) as mock_urlopen:
            with patch("llm.time.sleep"):
                with self.assertRaises(LLMCallError):
                    is_good_fit("fake-key", "fake-model", "must be remote", _listing())

        self.assertEqual(mock_urlopen.call_count, MAX_ATTEMPTS)


class CallOpenrouterErrorWrappingTests(unittest.TestCase):
    """A raw URLError/TimeoutError must never escape call_openrouter - every
    caller only catches LLMCallError to fail open/closed as appropriate (see
    resolve_listing_validity/passes_classifier in watch.py); an unwrapped error
    crashes the whole scan."""

    def test_http_error_is_wrapped_for_the_validator(self) -> None:
        http_error = urllib.error.HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)
        with patch("llm.urllib.request.urlopen", side_effect=http_error):
            with patch("llm.time.sleep"):
                with self.assertRaises(LLMCallError):
                    check_is_job_posting("fake-key", "fake-model", _listing())

    def test_timeout_is_wrapped_for_the_classifier(self) -> None:
        with patch("llm.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with patch("llm.time.sleep"):
                with self.assertRaises(LLMCallError):
                    is_good_fit("fake-key", "fake-model", "must be remote", _listing())


if __name__ == "__main__":
    unittest.main()
