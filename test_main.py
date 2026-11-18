import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from main import analyze_comments, collect_comments, save_results


class CommentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        self.cutoff = self.now - timedelta(days=7)

    def comment(self, body, comment_id="one", created=None):
        return {"id": comment_id, "body": body,
                "created_utc": (created or self.now).timestamp(),
                "permalink": "/r/reddevils/comments/example/post/one/"}

    def analyze(self, comments):
        return analyze_comments(comments, "Dalot", self.cutoff, self.now)

    def test_sentiment_and_sentence_selection(self):
        rows = self.analyze([
            self.comment("Dalot was terrible today.", "negative"),
            self.comment("The result was terrible. Dalot was excellent!", "positive"),
            self.comment("Dalot started at right back.", "neutral"),
            self.comment("Dalot was not bad today.", "negation"),
        ])
        labels = {row["id"]: row["sentiment"] for row in rows}
        self.assertEqual(labels, {"negative": "negative", "positive": "positive",
                                  "neutral": "neutral", "negation": "positive"})
        self.assertEqual(rows[0]["id"], "negative")
        self.assertTrue(rows[0]["permalink"].startswith("https://www.reddit.com/"))

    def test_window_word_boundaries_and_duplicates(self):
        valid = self.comment("DALOT was terrible.", created=self.cutoff)
        rows = self.analyze([
            valid, valid,
            self.comment("Dalot was terrible.", "old", self.cutoff - timedelta(seconds=1)),
            self.comment("Dalot was terrible.", "future", self.now + timedelta(seconds=1)),
            self.comment("Dalottery is terrible.", "partial"),
            self.comment("The midfield was terrible.", "other"),
            self.comment("[removed]", "removed"),
        ])
        self.assertEqual([row["id"] for row in rows], ["one"])

    def test_exports_include_only_negative_csv(self):
        rows = self.analyze([self.comment("Dalot was terrible."),
                             self.comment("Dalot was excellent!", "two")])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report = save_results(output, rows, {"source": "test"})
            self.assertEqual(report["negative_count"], 1)
            self.assertEqual(report["negative_percentage"], 50.0)
            self.assertEqual(json.loads((output / "report.json").read_text(encoding="utf-8"))["source"], "test")
            with (output / "negative_comments.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)

    def test_empty_export(self):
        with tempfile.TemporaryDirectory() as directory:
            report = save_results(Path(directory), [], {})
            self.assertEqual(report["negative_percentage"], 0)

    @patch("main.time.sleep")
    @patch("main.sync_playwright")
    def test_pagination_stops_at_cutoff(self, playwright_factory, sleep):
        page = MagicMock()
        page.goto.return_value.status = 200
        browser = playwright_factory.return_value.__enter__.return_value.chromium.launch.return_value
        browser.new_page.return_value = page
        page.locator.return_value.inner_text.side_effect = [
            json.dumps({"data": {"children": [{"kind": "t1", "data": self.comment("Dalot", "new")}], "after": "t1_new"}}),
            json.dumps({"data": {"children": [{"kind": "t1", "data": self.comment("Dalot", "old", self.cutoff - timedelta(seconds=1))}], "after": "t1_old"}}),
        ]
        comments, reason = collect_comments("reddevils", self.cutoff, 10)
        self.assertEqual(reason, "cutoff_reached")
        self.assertEqual(len(comments), 2)
        self.assertIn("after=t1_new", page.goto.call_args.args[0])
        browser.close.assert_called_once()

    @patch("main.sync_playwright")
    def test_blocked_reddit_fails_clearly(self, playwright_factory):
        browser = playwright_factory.return_value.__enter__.return_value.chromium.launch.return_value
        browser.new_page.return_value.goto.return_value.status = 403
        with self.assertRaisesRegex(RuntimeError, "403"):
            collect_comments("reddevils", self.cutoff, 1)
        browser.close.assert_called_once()

    @patch("main.sync_playwright")
    def test_page_limit_is_reported(self, playwright_factory):
        browser = playwright_factory.return_value.__enter__.return_value.chromium.launch.return_value
        page = browser.new_page.return_value
        page.goto.return_value.status = 200
        page.locator.return_value.inner_text.return_value = json.dumps({
            "data": {"children": [{"kind": "t1", "data": self.comment("Dalot")}], "after": "t1_one"}})
        _, reason = collect_comments("reddevils", self.cutoff, 1)
        self.assertEqual(reason, "page_limit")


if __name__ == "__main__":
    unittest.main()