#!/usr/bin/env python3
"""
update_bestsellers.py
Fetches audiobook bestseller data from multiple sources and
rebuilds bestsellers.html for Audiobooks.org

Sources:
  - NYT Books API (audio-fiction + audio-nonfiction)
  - PopVortex (Apple iTunes aggregated chart)
  - LibriVox API (most popular free audiobooks)
  - Project Gutenberg AI audiobooks (Microsoft/MIT curated)

Run locally:   NYT_API_KEY=your_key python3 scripts/update_bestsellers.py
GitHub Action: NYT_API_KEY is stored as a repo secret
"""

import os
import re
import datetime
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
NYT_API_KEY   = os.environ.get("NYT_API_KEY", "")
AFFILIATE_TAG = "audiobooksorg"
TODAY         = datetime.date.today().strftime("%B %d, %Y")
OUTPUT_FILE   = Path(__file__).parent.parent / "bestsellers.html"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Audiobooks.org/1.0)"}

# Known AI-narrated Audible ASINs — add more as you discover them
AI_ASINS = {
    "B0FBL8KT8J", "B0DCCL4WJD", "B0F1CYD1PT", "B0GHSY86WQ",
    "B0CY734PFD", "B0CZ7KBKK9", "B0DDJ4JNBM", "B0CY85MFWJ",
    "B0CW8M55WH", "B0D64NLQ2B", "B0FQV8M9NZ", "B0H3478K1Q",
    "B0H2JF8KJD",
}

# ── Data fetchers ────────────────────────────────────────────────────

def fetch_nyt(list_name):
    """Fetch a NYT audiobook bestseller list."""
    if not NYT_API_KEY:
        print("  [skip] No NYT_API_KEY set")
        return []
    url = f"https://api.nytimes.com/svc/books/v3/lists/current/{list_name}.json"
    try:
        r = requests.get(url, params={"api-key": NYT_API_KEY}, timeout=15)
        r.raise_for_status()
        books = r.json().get("results", {}).get("books", [])
        out = []
        for b in books[:10]:
            asin = ""
            m = re.search(r"/([A-Z0-9]{10})(?:[/?]|$)", b.get("amazon_product_url", ""))
            if m:
                asin = m.group(1)
            link = f"https://www.audible.com/search?tag={AFFILIATE_TAG}&keywords={requests.utils.quote(b.get('title', ''))}"
            out.append({
                "rank":   b.get("rank", 0),
                "title":  b.get("title", ""),
                "author": b.get("author", ""),
                "weeks":  b.get("weeks_on_list", 0),
                "asin":   asin,
                "link":   link,
                "ai":     asin in AI_ASINS,
            })
        return out
    except Exception as e:
        print(f"  [error] NYT {list_name}: {e}")
        return []


def fetch_popvortex():
    """Scrape PopVortex top audiobooks — parses cover image alt text."""
    url = "https://www.popvortex.com/books/charts/best-selling-audiobooks.php"
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")
        books = []

        # Each entry has a cover image with alt="Title - Author Cover Art"
        imgs = soup.find_all("img", alt=lambda x: x and "Cover Art" in x)

        for i, img in enumerate(imgs[:10]):
            alt = img.get("alt", "").replace(" Cover Art", "").strip()
            # Format is "Title - Author" (author is last segment after " - ")
            if " - " in alt:
                parts = alt.rsplit(" - ", 1)
                title  = parts[0].strip()
                author = parts[1].strip()
            else:
                title  = alt
                author = ""

            # Walk up DOM to find links near this entry
            parent = img.parent
            audible_link = apple_link = None
            for _ in range(8):
                if parent is None:
                    break
                audible_link = parent.find("a", href=lambda x: x and "amazon.com" in x)
                apple_link   = parent.find("a", href=lambda x: x and "apple.com" in x)
                if audible_link or apple_link:
                    break
                parent = parent.parent

            # Build Audible search link with our tag
            link = "#"
            if audible_link:
                kw = re.search(r"keywords=([^&]+)", audible_link["href"])
                if kw:
                    link = f"https://www.audible.com/search?tag={AFFILIATE_TAG}&keywords={kw.group(1)}"
            elif apple_link:
                link = apple_link["href"]
            else:
                link = f"https://www.audible.com/search?tag={AFFILIATE_TAG}&keywords={requests.utils.quote(title + ' ' + author)}"

            books.append({
                "rank":   i + 1,
                "title":  title,
                "author": author,
                "link":   link,
                "ai":     False,
            })

        return books
    except Exception as e:
        print(f"  [error] PopVortex: {e}")
        return []


def fetch_librivox():
    """Fetch LibriVox recently added audiobooks via their API."""
    url = "https://librivox.org/api/feed/audiobooks"
    params = {
        "fields": "id,title,url_librivox,totaltime,authors",
        "sort_order": "catalog_date",
        "limit": "10",
        "format": "json",
    }
    try:
        r = requests.get(url, params=params, timeout=15, headers=HEADERS)
        data = r.json()
        out = []
        for i, b in enumerate(data.get("books", [])):
            authors = b.get("authors", [{}])
            fn = authors[0].get("first_name", "") if authors else ""
            ln = authors[0].get("last_name", "")  if authors else ""
            out.append({
                "rank":     i + 1,
                "title":    b.get("title", ""),
                "author":   f"{fn} {ln}".strip(),
                "duration": b.get("totaltime", ""),
                "link":     b.get("url_librivox", "#"),
            })
        return out
    except Exception as e:
        print(f"  [error] LibriVox: {e}")
        return []


def get_gutenberg_ai():
    """Curated top Gutenberg AI audiobooks (Microsoft/MIT), ordered by Gutenberg popularity."""
    return [
        {"rank": 1,  "title": "Frankenstein",                    "author": "Mary Shelley",            "duration": "~8 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_frankenstein_by_mary_wollstonecraft_she"},
        {"rank": 2,  "title": "Dracula",                          "author": "Bram Stoker",              "duration": "~16 hrs", "link": "https://archive.org/details/synapseml_gutenberg_dracula_by_bram_stoker"},
        {"rank": 3,  "title": "Pride and Prejudice",              "author": "Jane Austen",              "duration": "~12 hrs", "link": "https://archive.org/details/synapseml_gutenberg_pride_and_prejudice_by_jane_austen"},
        {"rank": 4,  "title": "The Picture of Dorian Gray",       "author": "Oscar Wilde",              "duration": "~9 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_the_picture_of_dorian_gray_by_oscar_wi"},
        {"rank": 5,  "title": "The Call of the Wild",             "author": "Jack London",              "duration": "~3 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_the_call_of_the_wild_by_jack_london"},
        {"rank": 6,  "title": "Romeo and Juliet",                 "author": "William Shakespeare",      "duration": "~2 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_romeo_and_juliet_by_william_shakespeare"},
        {"rank": 7,  "title": "Moby Dick",                        "author": "Herman Melville",          "duration": "~24 hrs", "link": "https://archive.org/details/synapseml_gutenberg_moby_dick_by_herman_melville"},
        {"rank": 8,  "title": "Alice's Adventures in Wonderland", "author": "Lewis Carroll",            "duration": "~3 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_alice_s_adventures_in_wonderland_by_lewi"},
        {"rank": 9,  "title": "The Scarlet Letter",               "author": "Nathaniel Hawthorne",      "duration": "~8 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_the_scarlet_letter_by_nathaniel_hawthorne"},
        {"rank": 10, "title": "The Yellow Wallpaper",             "author": "Charlotte Perkins Gilman", "duration": "~1 hr",   "link": "https://archive.org/details/synapseml_gutenberg_the_yellow_wallpaper_by_charlotte_perkins"},
    ]


# ── HTML builders ────────────────────────────────────────────────────

EMOJI = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

def book_row_html(book, show_ai=True, show_weeks=False, show_duration=False, show_free=False):
    rank     = book.get("rank", 0)
    title    = book.get("title", "")
    author   = book.get("author", "")
    link     = book.get("link", "#")
    ai       = book.get("ai", False)
    weeks    = book.get("weeks", 0)
    duration = book.get("duration", "")
    top3     = "top" if rank <= 3 else ""
    emoji    = EMOJI[rank - 1] if 1 <= rank <= 10 else str(rank)

    badges = ""
    if rank == 1:               badges += '<span class="badge badge-hot">🔥 #1</span>'
    if ai and show_ai:          badges += '<span class="badge badge-ai">⚙ AI narrated</span>'
    if show_weeks and weeks > 1:badges += f'<span class="badge badge-classic">{weeks} wks on list</span>'
    if show_duration and duration: badges += f'<span class="badge badge-source">{duration}</span>'
    if show_free:               badges += '<span class="badge badge-free">Free</span>'

    return f"""
        <div class="book-row{' ai-row' if ai else ''}">
          <div class="book-rank {top3}">{rank}</div>
          <div class="book-thumb">{emoji}</div>
          <div class="book-info">
            <h4>{title}</h4>
            <p>{author}</p>
            <div class="book-tags">{badges}</div>
          </div>
          <a href="{link}" target="_blank" rel="noopener" class="book-link">Listen ↗</a>
        </div>"""


def chart_section(section_id, logo_html, date_str, tabs):
    tab_headers = ""
    tab_contents = ""
    for i, (label, tid, books, kwargs) in enumerate(tabs):
        active = "active" if i == 0 else ""
        tab_headers += f'<div class="ctab {active}" onclick="switchTab(this,\'{tid}\')">{label}</div>\n'
        if books:
            rows = "".join(book_row_html(b, **kwargs) for b in books)
        else:
            rows = '<div class="book-row"><div class="book-info"><h4>Data unavailable — will retry on next update</h4></div></div>'
        tab_contents += f'<div class="chart-list {active}" id="{tid}">{rows}<div class="chart-note">Updated {TODAY}</div></div>\n'

    return f"""
    <div class="chart-wrap" id="{section_id}">
      <div class="chart-header">
        <div class="chart-source">{logo_html}<span class="chart-date">{date_str}</span></div>
        <div class="chart-tabs">{tab_headers}</div>
      </div>
      {tab_contents}
    </div>"""


def build_html(data):
    nyt_f   = data["nyt_fiction"]
    nyt_nf  = data["nyt_nonfiction"]
    pv      = data["popvortex"]
    lv      = data["librivox"]
    gut_ai  = data["gutenberg_ai"]

    audible_sec = chart_section(
        "audible",
        '<span class="chart-logo logo-amazon">AUDIBLE</span>',
        f"Via NYT Books API · {TODAY} · ⚙ = AI narrated",
        [
            ("Fiction",    "aud-f",  nyt_f,  {"show_ai": True,  "show_weeks": True}),
            ("Nonfiction", "aud-nf", nyt_nf, {"show_ai": True,  "show_weeks": True}),
        ]
    )
    nyt_sec = chart_section(
        "nyt",
        '<span class="chart-logo logo-nyt">NYT</span>',
        f"New York Times · {TODAY}",
        [
            ("Fiction",    "nyt-f",  nyt_f,  {"show_ai": True,  "show_weeks": True}),
            ("Nonfiction", "nyt-nf", nyt_nf, {"show_ai": True,  "show_weeks": True}),
        ]
    )
    pv_sec = chart_section(
        "popvortex",
        '<span class="chart-logo" style="background:#e8f4fd;color:#0a6ebd;">PopVortex</span>',
        f"Apple iTunes chart · {TODAY}",
        [
            ("Top Audiobooks", "pv-top", pv, {"show_ai": False}),
        ]
    )
    lv_sec = chart_section(
        "librivox",
        '<span class="chart-logo" style="background:#e1f5ee;color:#085041;">LibriVox</span>',
        f"Recently added · {TODAY} · Free, no account needed",
        [
            ("Latest Titles", "lv-top", lv, {"show_ai": False, "show_duration": True, "show_free": True}),
        ]
    )
    gut_ai_sec = chart_section(
        "gutenberg-ai",
        '<span class="chart-logo" style="background:#eeedfe;color:#3c3489;">Gutenberg AI</span>',
        f"Microsoft Neural TTS · Free · No account needed",
        [
            ("AI Narrated Classics", "gut-ai", gut_ai, {"show_ai": False, "show_duration": True, "show_free": True}),
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" href="/favicon.ico" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Audiobook Bestsellers — Audiobooks.org</title>
  <link rel="canonical" href="https://audiobooks.org/bestsellers.html" />
  <meta name="description" content="Live audiobook bestseller charts — NYT, Audible, PopVortex, LibriVox, and Gutenberg AI. Updated daily." />
  <link rel="stylesheet" href="/styles.css" />
  <style>
    .chart-list {{ display: none; }}
    .chart-list.active {{ display: block; }}
    .ctab {{ cursor: pointer; }}
    .ai-row {{ background: #f9f8ff; }}
    .badge-ai   {{ background: var(--purple-light); color: var(--purple-dark); border: 1px solid var(--purple-mid); }}
    .badge-free {{ background: var(--teal-light);   color: var(--teal-dark); }}
    .badge-source {{ background: var(--bg-off); color: var(--text-muted); border: 1px solid var(--border); }}
    .chart-jump {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 24px 0 8px; }}
    .chart-jump a {{
      font-size: 0.8rem; font-weight: 500; padding: 6px 14px;
      border-radius: 20px; border: 1.5px solid var(--border); color: var(--text-muted);
      transition: all 0.12s;
    }}
    .chart-jump a:hover {{ background: var(--teal-light); border-color: var(--teal-mid); color: var(--teal-dark); }}
    .ai-legend {{
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 0.8rem; color: var(--purple-dark);
      background: var(--purple-light); padding: 6px 14px;
      border-radius: 20px; border: 1px solid var(--purple-mid); margin-top: 12px;
    }}
  </style>
</head>
<body>
<a href="#main" class="skip-link">Skip to content</a>

<nav class="nav" aria-label="Primary">
  <div class="container">
    <div class="nav-inner">
      <a href="/index.html" class="nav-logo">
        <div class="nav-logo-icon">🎧</div>
        <span><span>Audio</span>books.org</span>
      </a>
      <div class="nav-links" id="nav-links">
        <a href="/index.html"          class="nav-link">Home</a>
        <a href="/paid-platforms.html" class="nav-link">Paid platforms</a>
        <a href="/free-sources.html"   class="nav-link">Free sources</a>
        <a href="/ai-audiobooks.html"  class="nav-link">AI picks</a>
        <a href="/bestsellers.html"    class="nav-link active" aria-current="page">Bestsellers</a>
      </div>
      <a href="/paid-platforms.html#audible" class="btn btn-primary nav-cta">Start listening</a>
      <button class="nav-hamburger" aria-label="Toggle menu" aria-expanded="false" aria-controls="nav-links"
        onclick="const l=document.getElementById('nav-links');const o=l.classList.toggle('open');this.setAttribute('aria-expanded',o);">☰</button>
    </div>
  </div>
</nav>

<div class="page-hero amber">
  <div class="container">
    <span class="badge badge-amber" style="margin-bottom:12px;display:inline-block;">📊 Live charts</span>
    <h1>Audiobook Bestsellers</h1>
    <p>Five charts updated daily — NYT, Audible, PopVortex, LibriVox, and Gutenberg AI. Paid and free, all in one place.</p>
    <div class="ai-legend">⚙ AI narrated badge marks synthetic-voice titles in paid charts</div>
  </div>
</div>

<main id="main">
  <div class="container">

    <div class="disclosure" style="margin-top:24px;">
      ℹ️ <strong>Affiliate disclosure:</strong> Paid chart links earn a small commission at no extra cost to you. Free chart links earn nothing — we include them because they're genuinely great.
    </div>

    <div class="chart-jump">
      <a href="#audible">Audible</a>
      <a href="#nyt">NYT</a>
      <a href="#popvortex">PopVortex</a>
      <a href="#librivox">LibriVox 🔓</a>
      <a href="#gutenberg-ai">Gutenberg AI 🔓</a>
    </div>

    <div class="section-header" style="margin-top:8px;">
      <div>
        <h2>📊 All charts</h2>
        <p class="section-meta">Auto-updated daily via GitHub Actions · Last updated {TODAY}</p>
      </div>
    </div>

    {audible_sec}
    <div style="height:24px;"></div>
    {nyt_sec}
    <div style="height:24px;"></div>
    {pv_sec}
    <div style="height:24px;"></div>
    {lv_sec}
    <div style="height:24px;"></div>
    {gut_ai_sec}

  </div>
</main>

<footer class="footer">
  <div class="container">
    <div class="footer-inner">
      <span class="footer-copy">© 2026 Audiobooks.org · Affiliate links help keep this site free · Charts updated {TODAY}</span>
      <nav class="footer-links">
        <a href="#">About</a>
        <a href="#">Privacy</a>
        <a href="#">Contact</a>
      </nav>
    </div>
  </div>
</footer>

<script>
  function switchTab(t, id) {{
    const w = t.closest('.chart-wrap');
    w.querySelectorAll('.ctab').forEach(x => x.classList.remove('active'));
    w.querySelectorAll('.chart-list').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(id).classList.add('active');
  }}
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"Fetching bestseller data — {TODAY}")

    print("  NYT audio-fiction...")
    nyt_f = fetch_nyt("audio-fiction")

    print("  NYT audio-nonfiction...")
    nyt_nf = fetch_nyt("audio-nonfiction")

    print("  PopVortex...")
    pv = fetch_popvortex()

    print("  LibriVox...")
    lv = fetch_librivox()

    print("  Gutenberg AI (curated)...")
    gut_ai = get_gutenberg_ai()

    html = build_html({
        "nyt_fiction":    nyt_f,
        "nyt_nonfiction": nyt_nf,
        "popvortex":      pv,
        "librivox":       lv,
        "gutenberg_ai":   gut_ai,
    })

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"  ✓ Written to {OUTPUT_FILE}")
    print(f"\n  NYT fiction:    {len(nyt_f)}")
    print(f"  NYT nonfiction: {len(nyt_nf)}")
    print(f"  PopVortex:      {len(pv)}")
    print(f"  LibriVox:       {len(lv)}")
    print(f"  Gutenberg AI:   {len(gut_ai)}")


if __name__ == "__main__":
    main()
