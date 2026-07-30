from __future__ import annotations

import unittest

from sources.base import looks_like_job_posting_url


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
