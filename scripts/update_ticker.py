#!/usr/bin/env python3
"""
update_ticker.py
Rebuilds ticker.json — the homepage "Latest" river on Audiobooks.org —
from the story pool in ticker-pool.json: the five most recent stories
make the cut, newest first.

The pool is curated by hand: a story joins it when it is filed (the
/news/ queue is the usual source). This script only sorts and trims;
it never writes a headline of its own.

Run locally:   python3 scripts/update_ticker.py
GitHub Action: .github/workflows/update-ticker.yml runs it daily and
               commits ticker.json only when it changed.
"""

import json
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
POOL_FILE = ROOT / "ticker-pool.json"
OUT_FILE  = ROOT / "ticker.json"
LIMIT     = 5


def main():
    pool = json.loads(POOL_FILE.read_text(encoding="utf-8"))
    items = [i for i in pool
             if i.get("date") and i.get("headline") and i.get("url")]
    # Newest first. The sort is stable, so stories sharing a date keep
    # their pool order.
    items.sort(key=lambda i: i["date"], reverse=True)
    top = [{"date": i["date"], "headline": i["headline"], "url": i["url"]}
           for i in items[:LIMIT]]
    OUT_FILE.write_text(json.dumps(top, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"ticker: wrote {len(top)} stories to {OUT_FILE.name} "
          f"(pool holds {len(items)})")


if __name__ == "__main__":
    main()
