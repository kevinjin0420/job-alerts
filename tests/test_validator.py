from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watch"))
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


class ReasoningTokenCapTests(unittest.TestCase):
    """Regression test for the "friend getting spammed" incident: some models
    (e.g. qwen3.6-flash) ignore reasoning "effort" and reason at length regardless,
    blowing through max_tokens before emitting content - every call then fails
    open (notifies anyway) instead of actually classifying anything."""

    def test_request_caps_reasoning_tokens_not_effort(self) -> None:
        response = _mock_response(
            {"choices": [{"message": {"content": json.dumps({"is_job_posting": True, "reason": "ok"})}}], "usage": {}}
        )
        with patch("llm.urllib.request.urlopen", return_value=response) as mock_urlopen:
            with patch("validator.record_llm_call"):
                check_is_job_posting("fake-key", "fake-model", _listing())

        sent_body = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(sent_body["reasoning"], {"max_tokens": 150})
        self.assertGreater(sent_body["max_tokens"], 150)


class RecordLlmCallTests(unittest.TestCase):
    """LLM Logs page data - kept off stdout/CloudWatch, see check_is_job_posting's docstring comment above the print line."""

    def test_records_full_payload_and_response(self) -> None:
        response = _mock_response(
            {"choices": [{"message": {"content": json.dumps({"is_job_posting": True, "reason": "looks real"})}}], "usage": {}}
        )
        with patch("llm.urllib.request.urlopen", return_value=response):
            with patch("validator.record_llm_call") as mock_record:
                check_is_job_posting("fake-key", "fake-model", _listing())

        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        self.assertEqual(kwargs["event"], "validity_check")
        self.assertEqual(kwargs["reason"], "looks real")
        self.assertIn("Company: Example", kwargs["user_content"])

    def test_record_failure_does_not_affect_the_returned_result(self) -> None:
        response = _mock_response(
            {"choices": [{"message": {"content": json.dumps({"is_job_posting": True, "reason": "looks real"})}}], "usage": {}}
        )
        with patch("llm.urllib.request.urlopen", return_value=response):
            with patch("validator.record_llm_call", side_effect=RuntimeError("boom")):
                is_job_posting, reason = check_is_job_posting("fake-key", "fake-model", _listing())

        self.assertTrue(is_job_posting)
        self.assertEqual(reason, "looks real")


if __name__ == "__main__":
    unittest.main()
