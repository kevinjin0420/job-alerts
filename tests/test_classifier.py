from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watch"))
from classifier import is_good_fit
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


class FitScoreClampingTests(unittest.TestCase):
    """A model once returned a stray year (2022) as fit_score - now clamped by schema constraint and a Python-side backstop."""

    def test_out_of_range_score_is_clamped_to_100(self) -> None:
        response = _mock_response(
            {
                "choices": [{"message": {"content": json.dumps({"fits": True, "reason": "ok", "fit_score": 2022})}}],
                "usage": {},
            }
        )
        with patch("llm.urllib.request.urlopen", return_value=response) as mock_urlopen:
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
        with patch("llm.urllib.request.urlopen", return_value=response):
            result = is_good_fit("fake-key", "fake-model", "must be remote", _listing(), resume_text="resume text")

        self.assertEqual(result.fit_score, 0)

    def test_in_range_score_passes_through_unchanged(self) -> None:
        response = _mock_response(
            {
                "choices": [{"message": {"content": json.dumps({"fits": True, "reason": "ok", "fit_score": 72})}}],
                "usage": {},
            }
        )
        with patch("llm.urllib.request.urlopen", return_value=response):
            result = is_good_fit("fake-key", "fake-model", "must be remote", _listing(), resume_text="resume text")

        self.assertEqual(result.fit_score, 72)


if __name__ == "__main__":
    unittest.main()
