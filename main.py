"""Find negative sentiment in recent Reddit comments mentioning a player."""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


def collect_comments(subreddit, cutoff, max_pages, headed=False):
    comments = []
    after = None
    seen_cursors = set()
    stop_reason = "page_limit"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        try:
            page = browser.new_page()
            for page_number in range(max_pages):
                if page_number:
                    time.sleep(2)
                params = {"limit": 100, "raw_json": 1}
                if after:
                    params["after"] = after
                url = f"https://www.reddit.com/r/{subreddit}/comments.json?{urlencode(params)}"
                response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if response is None or response.status != 200:
                    status = response.status if response else "no response"
                    raise RuntimeError(
                        f"Reddit returned {status}. Access may be blocked or rate-limited. "
                        "Stop and try later; this project does not bypass access controls. "
                        "Use --demo to test offline."
                    )
                try:
                    listing = json.loads(page.locator("body").inner_text())
                    children = listing["data"]["children"]
                    next_after = listing["data"].get("after")
                    if not isinstance(children, list):
                        raise TypeError("Expected a comment listing")
                except (ValueError, KeyError, TypeError) as error:
                    raise RuntimeError(
                        "Reddit did not return a public JSON listing (possibly a login "
                        "or access-check page). Use --demo or an authorized JSON export."
                    ) from error
                reached_cutoff = False
                for child in children:
                    if child.get("kind") != "t1":
                        continue
                    comment = child["data"]
                    if float(comment["created_utc"]) < cutoff.timestamp():
                        reached_cutoff = True
                    comments.append(comment)
                print(f"Fetched page {page_number + 1}: {len(children)} comments.", file=sys.stderr)
                if reached_cutoff:
                    stop_reason = "cutoff_reached"
                    break
                if not children or not next_after:
                    stop_reason = "listing_exhausted"
                    break
                if next_after in seen_cursors:
                    stop_reason = "repeated_cursor"
                    break
                seen_cursors.add(next_after)
                after = next_after
        finally:
            browser.close()
    return comments, stop_reason


def analyze_comments(comments, player, cutoff, now, threshold=-0.05):
    analyzer = SentimentIntensityAnalyzer()
    mention = re.compile(rf"\b{re.escape(player)}\b", re.IGNORECASE)
    results = []
    seen = set()
    for comment in comments:
        comment_id = str(comment["id"])
        created = float(comment["created_utc"])
        body = comment["body"]
        if comment_id in seen or not cutoff.timestamp() <= created <= now.timestamp():
            continue
        seen.add(comment_id)
        if body in ("[removed]", "[deleted]") or not mention.search(body):
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n+", body)
        relevant_text = " ".join(sentence for sentence in sentences if mention.search(sentence))
        compound = analyzer.polarity_scores(relevant_text)["compound"]
        sentiment = "negative" if compound <= threshold else "positive" if compound >= 0.05 else "neutral"
        permalink = comment.get("permalink", "")
        if permalink.startswith("/"):
            permalink = "https://www.reddit.com" + permalink
        results.append({
            "id": comment_id,
            "created_utc": datetime.fromtimestamp(created, timezone.utc).isoformat(),
            "body": body,
            "analyzed_text": relevant_text,
            "compound": compound,
            "sentiment": sentiment,
            "permalink": permalink,
        })
    return sorted(results, key=lambda row: row["compound"])


def demo_comments(now):
    texts = [
        "Dalot was terrible today. His defending was awful.",
        "Dalot was excellent today!",
        "Dalot started at right back.",
        "Dalot was not bad today.",
        "The result was terrible. Dalot was excellent though!",
        "The midfield was terrible today.",
    ]
    comments = [
        {"id": f"demo-{index}", "created_utc": (now - timedelta(hours=index + 1)).timestamp(),
         "body": text, "permalink": ""}
        for index, text in enumerate(texts)
    ]
    comments.append({"id": "demo-old", "created_utc": (now - timedelta(days=8)).timestamp(),
                     "body": "Dalot was terrible last week.", "permalink": ""})
    return comments


def save_results(output, rows, metadata):
    output.mkdir(parents=True, exist_ok=True)
    negative = [row for row in rows if row["sentiment"] == "negative"]
    report = {**metadata, "mentions_analyzed": len(rows), "negative_count": len(negative),
              "negative_percentage": round(100 * len(negative) / len(rows), 1) if rows else 0,
              "comments": rows}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = ["id", "created_utc", "body", "analyzed_text", "compound", "sentiment", "permalink"]
    with (output / "negative_comments.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in negative:
            writer.writerow({key: "'" + value if isinstance(value, str) and value.startswith(
                ("=", "+", "-", "@", "\t", "\r")) else value for key, value in row.items()})
    return report


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddit", default="reddevils")
    parser.add_argument("--player", default="Dalot")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-pages", type=int, default=10, help="100 comments/page; coverage is not guaranteed")
    parser.add_argument("--threshold", type=float, default=-0.05, help="Negative VADER compound cutoff (-1 to below 0)")
    parser.add_argument("--headed", action="store_true", help="Show Chromium while collecting")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="Use synthetic examples, not live Reddit data")
    source.add_argument("--input", type=Path, help="Analyze a JSON array of previously collected comments")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", args.subreddit):
        parser.error("--subreddit must be a community name, such as reddevils, not a URL")
    args.player = args.player.strip()
    if not args.player or args.days < 1 or args.max_pages < 1 or not -1 <= args.threshold < 0:
        parser.error("Provide a player, positive days/max-pages, and a threshold from -1 to below 0")
    return args


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    source = "demo" if args.demo else "file" if args.input else "reddit"
    output = args.output or Path("output") / source
    try:
        if args.demo:
            comments, stop_reason = demo_comments(now), "synthetic_data"
        elif args.input:
            comments = json.loads(args.input.read_text(encoding="utf-8-sig"))
            stop_reason = "input_file"
        else:
            comments, stop_reason = collect_comments(args.subreddit, cutoff, args.max_pages, args.headed)
        if not isinstance(comments, list):
            raise ValueError("Input must be a JSON array of comment objects")
        rows = analyze_comments(comments, args.player, cutoff, now, args.threshold)
        report = save_results(output, rows, {
            "source": source, "subreddit": args.subreddit, "player": args.player,
            "window_start_utc": cutoff.isoformat(), "window_end_utc": now.isoformat(),
            "threshold": args.threshold, "comments_fetched": len(comments),
            "stop_reason": stop_reason, "coverage": "Sample only; complete seven-day coverage is not guaranteed.",
        })
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, PlaywrightError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Source: {source} | r/{args.subreddit} | {args.player} | last {args.days} days (UTC)")
    print(f"Mentions analyzed: {report['mentions_analyzed']}")
    print(f"Negative: {report['negative_count']} ({report['negative_percentage']}% of analyzed mentions)")
    print(f"Collection stopped: {stop_reason}. Coverage is not guaranteed.")
    print(f"Reports: {output.resolve()}")
    if not rows:
        print("No matching comments in the collected sample; this does not prove there were no mentions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())