from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import patch

from classifier import MAX_ATTEMPTS, ClassifierError, check_is_job_posting, is_good_fit
from sources.base import Listing


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


class ReasoningTokenCapTests(unittest.TestCase):
    """Regression test for the "friend getting spammed" incident: some models
    (e.g. qwen3.6-flash) ignore reasoning "effort" and reason at length regardless,
    blowing through max_tokens before emitting content - every call then fails
    open (notifies anyway) instead of actually classifying anything."""

    def test_request_caps_reasoning_tokens_not_effort(self) -> None:
        response = _mock_response(
            {"choices": [{"message": {"content": json.dumps({"is_job_posting": True, "reason": "ok"})}}], "usage": {}}
        )
        with patch("classifier.urllib.request.urlopen", return_value=response) as mock_urlopen:
            check_is_job_posting("fake-key", "fake-model", _listing())

        sent_body = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(sent_body["reasoning"], {"max_tokens": 150})
        self.assertGreater(sent_body["max_tokens"], 150)


class FitScoreClampingTests(unittest.TestCase):
    """A model once returned a stray year (2022) as fit_score - now clamped by schema constraint and a Python-side backstop."""

    def test_out_of_range_score_is_clamped_to_100(self) -> None:
        response = _mock_response(
            {
                "choices": [{"message": {"content": json.dumps({"fits": True, "reason": "ok", "fit_score": 2022})}}],
                "usage": {},
            }
        )
        with patch("classifier.urllib.request.urlopen", return_value=response) as mock_urlopen:
            result = is_good_fit("fake-key", "fake-model", "must be remote", _listing(), resume_text="resume text")

        self.assertEqual(result.fit_score, 100)
        sent_body = json.loads(mock_urlopen.call_args.args[0].data)
        fit_score_schema = sent_body["response_format"]["json_schema"]["schema"]["properties"]["fit_score"]
        self.assertEqual(fit_score_schema["minimum"], 0)
        self.assertEqual(fit_score_schema["maximum"], 100)

    def test_negative_score_is_clamped_to_zero(self) -> None:
        response = _mock_response(
            {
                "choices": [{"message": {"content": json.dumps({"fits": False, "reason": "ok", "fit_score": -5})}}],
                "usage": {},
            }
        )
        with patch("classifier.urllib.request.urlopen", return_value=response):
            result = is_good_fit("fake-key", "fake-model", "must be remote", _listing(), resume_text="resume text")

        self.assertEqual(result.fit_score, 0)

    def test_in_range_score_passes_through_unchanged(self) -> None:
        response = _mock_response(
            {
                "choices": [{"message": {"content": json.dumps({"fits": True, "reason": "ok", "fit_score": 72})}}],
                "usage": {},
            }
        )
        with patch("classifier.urllib.request.urlopen", return_value=response):
            result = is_good_fit("fake-key", "fake-model", "must be remote", _listing(), resume_text="resume text")

        self.assertEqual(result.fit_score, 72)


class RetryWithBackoffTests(unittest.TestCase):
    """A truncated/malformed response used to give up after 2 tries - now retries with increasing backoff up to MAX_ATTEMPTS before giving up, so it never fails open just because the model glitched once."""

    def test_retries_with_increasing_backoff_then_succeeds(self) -> None:
        good_response = _mock_response(
            {"choices": [{"message": {"content": json.dumps({"fits": True, "reason": "good match"})}}], "usage": {}}
        )
        with patch(
            "classifier.urllib.request.urlopen",
            side_effect=[urllib.error.HTTPError("https://openrouter.ai", 429, "busy", {}, None), good_response],
        ) as mock_urlopen:
            with patch("classifier.time.sleep") as mock_sleep:
                result = is_good_fit("fake-key", "fake-model", "must be remote", _listing())

        self.assertTrue(result.fits)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    def test_gives_up_after_max_attempts(self) -> None:
        with patch(
            "classifier.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("https://openrouter.ai", 429, "busy", {}, None),
        ) as mock_urlopen:
            with patch("classifier.time.sleep"):
                with self.assertRaises(ClassifierError):
                    is_good_fit("fake-key", "fake-model", "must be remote", _listing())

        self.assertEqual(mock_urlopen.call_count, MAX_ATTEMPTS)


class CallOpenrouterErrorWrappingTests(unittest.TestCase):
    """A raw URLError/TimeoutError must never escape _call_openrouter - every
    caller only catches ClassifierError to fail open (see resolve_listing_validity/
    passes_classifier in watch.py); an unwrapped error crashes the whole scan."""

    def test_http_error_is_wrapped_in_classifier_error(self) -> None:
        http_error = urllib.error.HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)
        with patch("classifier.urllib.request.urlopen", side_effect=http_error):
            with patch("classifier.time.sleep"):
                with self.assertRaises(ClassifierError):
                    check_is_job_posting("fake-key", "fake-model", _listing())

    def test_timeout_is_wrapped_in_classifier_error(self) -> None:
        with patch("classifier.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with patch("classifier.time.sleep"):
                with self.assertRaises(ClassifierError):
                    is_good_fit("fake-key", "fake-model", "must be remote", _listing())


if __name__ == "__main__":
    unittest.main()
