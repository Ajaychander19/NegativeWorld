# NegativeWorld

A basic Python project to find negative sentiment in **r/reddevils comments
mentioning Dalot from the last 7 days**. No API key, training, GPU, database,
or web server is required. Python 3.10+ is required.

Inspired by the NLP idea in [nontoxic-world](https://github.com/Zaid-Al-Habbal/nontoxic-world),
but intentionally much smaller. This is **sentiment analysis, not multi-label
toxicity detection**. Negative football criticism is not necessarily toxic.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

The explicit Python path avoids PowerShell activation-policy issues.
On macOS/Linux use `.venv/bin/python` instead.

## Run

Collect live Reddit comments and analyze Dalot over the rolling last 7 days:

```powershell
.\.venv\Scripts\python.exe main.py
```

Try the complete analysis/export flow offline with clearly labelled synthetic examples:

```powershell
.\.venv\Scripts\python.exe main.py --demo
```

Optional settings:

```powershell
.\.venv\Scripts\python.exe main.py --subreddit reddevils --player Dalot --days 7 --max-pages 10 --headed
```

`--headed` shows the browser; it does not bypass Reddit access restrictions.
`--max-pages` defaults to 10 pages of up to 100 comments, with a two-second
pause between pages. Stop if Reddit blocks or rate-limits access; do not
increase traffic or attempt to evade restrictions. Follow Reddit's terms
and applicable data-access requirements. For reliable larger-scale coverage,
use Reddit-authorized API access rather than this public-listing prototype.

## How It Works

1. Playwright opens Reddit's public newest-comments JSON listing in Chromium
   and follows pagination. It scans community comments, not just posts with
   Dalot in their titles, so older threads with new comments can be included.
2. Keep comments timestamped within `[now - 7 days, now]` in UTC, deduplicate
   IDs, and match the whole word `Dalot`, case-insensitively.
3. Use VADER, a lightweight lexicon/rule-based NLP sentiment analyzer, on
   sentences explicitly mentioning the player. A compound score of `<= -0.05`
   is negative; `>= 0.05` is positive; other scores are neutral. Scores range
   from -1 to +1 and are **not probabilities**. `--threshold -0.3` selects
   more strongly negative comments.
4. Export all matching comments and a negative-only CSV, sorted most negative first.

## Results

Live results are saved to `output/reddit/`, demo results to `output/demo/`,
and imported results to `output/file/`. Override with `--output PATH`.
Each run overwrites the two reports in its output directory.

- `report.json`: source, UTC window, collection stop reason, fetched count,
  matching count, negative count/percentage, and all analyzed mentions.
- `negative_comments.csv`: negative comments, analyzed sentences, score,
  timestamp, and Reddit link. Open in a spreadsheet; formula-like text is escaped.

No usernames are saved. The negative percentage describes **only the collected
matching comments**, not the community as a whole. A result of zero can mean
that the collected sample contained no matches, not that no negative comments exist.

## Coverage And Accuracy

Reddit may return 403/429, require login, or cap accessible listings. Even if
the cutoff is reached, this is a best-effort sample, **not an exhaustive search
of all comments in seven days**. Pagination is not a stable historical archive.
The script reports errors instead of silently substituting demo data.

VADER handles basic negation but can miss sarcasm, football slang, implied
references, and multilingual text. A negative sentence mentioning Dalot may
criticize someone else; this is not a target-aware trained classifier. Only
sentences explicitly naming him are scored, so pronoun-only follow-up criticism
can be missed. Review the exported comments manually before drawing conclusions.

## Analyze An Authorized Export

If live Reddit access is unavailable, supply a JSON array with this format:

```json
[
  {
    "id": "example-comment-id",
    "body": "Dalot was disappointing today.",
    "created_utc": 1794960000,
    "permalink": "/r/reddevils/comments/post_id/post_title/comment_id/"
  }
]
```

`created_utc` is Unix time in seconds. Use actual timestamps from your export;
the rolling time-window filter still applies. `permalink` is optional.
This input is an array, not the nested raw Reddit listing or generated report.

```powershell
.\.venv\Scripts\python.exe main.py --input comments.json
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Tests cover sentiment, negation, sentence selection, date boundaries,
deduplication, player matching, exports, pagination, and blocked access.
They use mocked collection and do not require Reddit or an installed browser.