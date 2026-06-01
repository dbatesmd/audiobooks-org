#!/usr/bin/env python3
"""
update_bestsellers.py
Fetches audiobook bestseller data from multiple sources and
rebuilds bestsellers.html for Audiobooks.org

Sources:
  - NYT Books API (audio-fiction + audio-nonfiction)
  - PopVortex (Audible + Apple aggregated chart)
  - LibriVox API (most popular free audiobooks)
  - Project Gutenberg top downloads
  - Project Gutenberg AI audiobooks (Microsoft/MIT curated)

Run locally:   NYT_API_KEY=your_key python3 scripts/update_bestsellers.py
GitHub Action: NYT_API_KEY is stored as a repo secret
"""

import os
import json
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
    """Fetch a NYT audiobook bestseller list. Returns list of book dicts."""
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
            amazon_url = b.get("amazon_product_url", "")
            # Extract ASIN from Amazon URL
            import re
            m = re.search(r"/([A-Z0-9]{10})(?:[/?]|$)", amazon_url)
            if m:
                asin = m.group(1)
            audible_url = f"https://www.audible.com/search?tag={AFFILIATE_TAG}&keywords={requests.utils.quote(b.get('title',''))}"
            out.append({
                "rank":         b.get("rank", 0),
                "title":        b.get("title", ""),
                "author":       b.get("author", ""),
                "description":  b.get("description", ""),
                "weeks":        b.get("weeks_on_list", 0),
                "asin":         asin,
                "link":         audible_url,
                "ai":           asin in AI_ASINS,
            })
        return out
    except Exception as e:
        print(f"  [error] NYT {list_name}: {e}")
        return []


def fetch_popvortex():
    """Scrape PopVortex top audiobooks chart."""
    url = "https://www.popvortex.com/books/charts/best-selling-audiobooks.php"
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")
        books = []
        # Try multiple possible selectors
        items = (soup.select(".mli") or
                 soup.select("li.mli") or
                 soup.select(".chart-item") or
                 soup.select("ol li"))
        for i, item in enumerate(items[:10]):
            title_el  = (item.select_one(".title") or
                         item.select_one("cite") or
                         item.select_one("h4"))
            artist_el = (item.select_one(".artist") or
                         item.select_one(".author") or
                         item.select_one("em"))
            link_el   = item.select_one("a[href]")
            title  = title_el.get_text(strip=True)  if title_el  else f"Title #{i+1}"
            author = artist_el.get_text(strip=True) if artist_el else ""
            link   = link_el["href"]                if link_el   else "#"
            # Append affiliate tag if it's an Audible link
            if "audible.com" in link and "tag=" not in link:
                sep = "&" if "?" in link else "?"
                link += f"{sep}tag={AFFILIATE_TAG}"
            books.append({"rank": i+1, "title": title, "author": author, "link": link, "ai": False})
        return books
    except Exception as e:
        print(f"  [error] PopVortex: {e}")
        return []


def fetch_librivox():
    """Fetch LibriVox popular audiobooks via their API."""
    url = "https://librivox.org/api/feed/audiobooks"
    params = {
        "fields": "id,title,url_librivox,totaltime,authors",
        "sort_order": "catalog_date",  # most recent as proxy for popular
        "limit": "10",
        "format": "json",
    }
    try:
        r = requests.get(url, params=params, timeout=15, headers=HEADERS)
        data = r.json()
        books = data.get("books", [])
        out = []
        for i, b in enumerate(books):
            authors = b.get("authors", [{}])
            fn = authors[0].get("first_name", "") if authors else ""
            ln = authors[0].get("last_name", "")  if authors else ""
            author = f"{fn} {ln}".strip()
            out.append({
                "rank":     i + 1,
                "title":    b.get("title", ""),
                "author":   author,
                "duration": b.get("totaltime", ""),
                "link":     b.get("url_librivox", "#"),
            })
        return out
    except Exception as e:
        print(f"  [error] LibriVox: {e}")
        return []


def fetch_gutenberg():
    """Scrape Project Gutenberg top downloads page."""
    url = "https://www.gutenberg.org/browse/scores/top"
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")
        books = []
        # The page has an ordered list of top ebooks
        ol = soup.find("ol")
        if ol:
            for i, li in enumerate(ol.find_all("li")[:10]):
                a = li.find("a")
                if a:
                    href = a.get("href", "")
                    full_url = ("https://www.gutenberg.org" + href
                                if href.startswith("/") else href)
                    books.append({
                        "rank":  i + 1,
                        "title": a.get_text(strip=True),
                        "link":  full_url,
                    })
        return books
    except Exception as e:
        print(f"  [error] Gutenberg: {e}")
        return []


def get_gutenberg_ai():
    """Curated list of top Gutenberg AI audiobooks (Microsoft/MIT collection).
    Ordered by Gutenberg download popularity. Update as new titles emerge."""
    return [
        {"rank": 1,  "title": "Frankenstein",                    "author": "Mary Shelley",           "duration": "~8 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_frankenstein_by_mary_wollstonecraft_she"},
        {"rank": 2,  "title": "Dracula",                          "author": "Bram Stoker",             "duration": "~16 hrs", "link": "https://archive.org/details/synapseml_gutenberg_dracula_by_bram_stoker"},
        {"rank": 3,  "title": "Pride and Prejudice",              "author": "Jane Austen",             "duration": "~12 hrs", "link": "https://archive.org/details/synapseml_gutenberg_pride_and_prejudice_by_jane_austen"},
        {"rank": 4,  "title": "The Picture of Dorian Gray",       "author": "Oscar Wilde",             "duration": "~9 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_the_picture_of_dorian_gray_by_oscar_wi"},
        {"rank": 5,  "title": "The Call of the Wild",             "author": "Jack London",             "duration": "~3 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_the_call_of_the_wild_by_jack_london"},
        {"rank": 6,  "title": "Romeo and Juliet",                 "author": "William Shakespeare",     "duration": "~2 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_romeo_and_juliet_by_william_shakespeare"},
        {"rank": 7,  "title": "Moby Dick",                        "author": "Herman Melville",         "duration": "~24 hrs", "link": "https://archive.org/details/synapseml_gutenberg_moby_dick_by_herman_melville"},
        {"rank": 8,  "title": "Alice's Adventures in Wonderland", "author": "Lewis Carroll",           "duration": "~3 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_alice_s_adventures_in_wonderland_by_lewi"},
        {"rank": 9,  "title": "The Scarlet Letter",               "author": "Nathaniel Hawthorne",     "duration": "~8 hrs",  "link": "https://archive.org/details/synapseml_gutenberg_the_scarlet_letter_by_nathaniel_hawthorne"},
        {"rank": 10, "title": "The Yellow Wallpaper",             "author": "Charlotte Perkins Gilman","duration": "~1 hr",   "link": "https://archive.org/details/synapseml_gutenberg_the_yellow_wallpaper_by_charlotte_perkins"},
    ]

# ── HTML builders ────────────────────────────────────────────────────

EMOJI_MAP = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

def book_row_html(book, show_ai_badge=True, show_weeks=False, show_duration=False, show_free=False):
    rank    = book.get("rank", 0)
    title   = book.get("title", "")
    author  = book.get("author", "")
    link    = book.get("link", "#")
    ai      = book.get("ai", False)
    weeks   = book.get("weeks", 0)
    duration= book.get("duration", "")
    top3    = "top" if rank <= 3 else ""

    ai_badge   = '<span class="badge badge-ai">⚙ AI narrated</span>' if (ai and show_ai_badge) else ""
    hot_badge  = '<span class="badge badge-hot">🔥 #1</span>'        if rank == 1 else ""
    weeks_tag  = f'<span class="badge badge-classic">{weeks} wks on list</span>' if (show_weeks and weeks > 1) else ""
    dur_tag    = f'<span class="badge badge-source">{duration}</span>' if (show_duration and duration) else ""
    free_badge = '<span class="badge badge-free">Free</span>'         if show_free else ""

    emoji = EMOJI_MAP[rank - 1] if rank <= 10 else str(rank)

    return f"""
        <div class="book-row{' ai-row' if ai else ''}">
          <div class="book-rank {top3}">{rank}</div>
          <div class="book-thumb">{emoji}</div>
          <div class="book-info">
            <h4>{title}</h4>
            <p>{author}</p>
            <div class="book-tags">{hot_badge}{ai_badge}{weeks_tag}{dur_tag}{free_badge}</div>
          </div>
          <a href="{link}" target="_blank" rel="noopener" class="book-link">Listen ↗</a>
        </div>"""


def chart_section(section_id, logo_html, date_str, tabs):
    """
    tabs: list of (tab_label, tab_id, books, kwargs)
    kwargs passed to book_row_html
    """
    tab_headers = ""
    tab_contents = ""
    for i, (label, tid, books, kwargs) in enumerate(tabs):
        active = "active" if i == 0 else ""
        tab_headers += f'<div class="ctab {active}" onclick="switchTab(this,\'{tid}\')">{label}</div>\n'
        rows = "".join(book_row_html(b, **kwargs) for b in books) if books else '<div class="book-row"><div class="book-info"><h4>Data unavailable — will retry on next update</h4></div></div>'
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
    nyt_fiction    = data["nyt_fiction"]
    nyt_nonfiction = data["nyt_nonfiction"]
    popvortex      = data["popvortex"]
    librivox       = data["librivox"]
    gutenberg      = data["gutenberg"]
    gutenberg_ai   = data["gutenberg_ai"]

    # Count AI books across all paid lists
    ai_count = sum(1 for b in nyt_fiction + nyt_nonfiction + popvortex if b.get("ai"))

    audible_section = chart_section(
        "audible",
        '<span class="chart-logo logo-amazon">AUDIBLE</span>',
        f"Via NYT · {TODAY} · ⚙ = AI narrated",
        [
            ("Fiction",    "aud-fiction",    nyt_fiction,    {"show_ai_badge": True, "show_weeks": True}),
            ("Nonfiction", "aud-nonfiction", nyt_nonfiction, {"show_ai_badge": True, "show_weeks": True}),
        ]
    )

    popvortex_section = chart_section(
        "popvortex",
        '<span class="chart-logo" style="background:#e8f4fd;color:#0a6ebd;">PopVortex</span>',
        f"Audible + Apple aggregated · {TODAY}",
        [
            ("Top Audiobooks", "pv-top", popvortex, {"show_ai_badge": False}),
        ]
    )

    nyt_section = chart_section(
        "nyt",
        '<span class="chart-logo logo-nyt">NYT</span>',
        f"New York Times · {TODAY}",
        [
            ("Fiction",    "nyt-fiction",    nyt_fiction,    {"show_ai_badge": True, "show_weeks": True}),
            ("Nonfiction", "nyt-nonfiction", nyt_nonfiction, {"show_ai_badge": True, "show_weeks": True}),
        ]
    )

    librivox_section = chart_section(
        "librivox",
        '<span class="chart-logo" style="background:#e1f5ee;color:#085041;">LibriVox</span>',
        f"Recently added · {TODAY} · Free, no account needed",
        [
            ("Latest Titles", "lv-latest", librivox, {"show_ai_badge": False, "show_duration": True, "show_free": True}),
        ]
    )

    gutenberg_section = chart_section(
        "gutenberg",
        '<span class="chart-logo" style="background:#eeedfe;color:#3c3489;">Gutenberg</span>',
        f"Most downloaded ebooks · {TODAY} · Free public domain",
        [
            ("Most Downloaded", "gut-top", gutenberg, {"show_ai_badge": False, "show_free": True}),
        ]
    )

    gutenberg_ai_section = chart_section(
        "gutenberg-ai",
        '<span class="chart-logo" style="background:#eeedfe;color:#3c3489;">Gutenberg AI</span>',
        f"Microsoft Neural TTS · Free · No account needed",
        [
            ("AI Narrated Classics", "gut-ai", gutenberg_ai, {"show_ai_badge": False, "show_duration": True, "show_free": True}),
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
  <meta name="description" content="Live audiobook bestseller charts — NYT, Audible, PopVortex, LibriVox, and Project Gutenberg. Updated daily." />
  <meta property="og:title" content="Audiobook Bestsellers — Audiobooks.org" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="https://audiobooks.org/bestsellers.html" />
  <link rel="stylesheet" href="/styles.css" />
  <style>
    .chart-list {{ display: none; }}
    .chart-list.active {{ display: block; }}
    .ctab {{ cursor: pointer; }}
    /* AI row highlight */
    .ai-row {{ background: #f9f8ff; }}
    .badge-ai {{
      background: var(--purple-light);
      color: var(--purple-dark);
      border: 1px solid var(--purple-mid);
    }}
    .badge-free {{ background: var(--teal-light); color: var(--teal-dark); }}
    .badge-source {{ background: var(--bg-off); color: var(--text-muted); border: 1px solid var(--border); }}
    .chart-jump {{
      display: flex; gap: 8px; flex-wrap: wrap;
      margin: 24px 0 8px;
    }}
    .chart-jump a {{
      font-size: 0.8rem; font-weight: 500;
      padding: 6px 14px; border-radius: 20px;
      border: 1.5px solid var(--border);
      color: var(--text-muted);
      transition: all 0.12s;
    }}
    .chart-jump a:hover {{
      background: var(--teal-light);
      border-color: var(--teal-mid);
      color: var(--teal-dark);
    }}
    .ai-legend {{
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 0.8rem; color: var(--purple-dark);
      background: var(--purple-light);
      padding: 6px 14px; border-radius: 20px;
      border: 1px solid var(--purple-mid);
      margin-top: 12px;
    }}
  </style>
</head>
<body>
<a href="#main" class="skip-link">Skip to content</a>

<nav class="nav" aria-label="Primary">
  <div class="container">
    <div class="nav-inner">
      <a href="/index.html" class="nav-logo" aria-label="Audiobooks.org home">
        <div class="nav-logo-icon" aria-hidden="true">🎧</div>
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
    <p>Six charts updated daily — NYT, Audible, PopVortex, LibriVox, Project Gutenberg, and Gutenberg AI. Paid and free, all in one place.</p>
    <div class="ai-legend">⚙ AI narrated badge marks synthetic-voice titles in paid charts</div>
  </div>
</div>

<main id="main">
  <div class="container">

    <div class="disclosure" style="margin-top:24px;">
      ℹ️ <strong>Affiliate disclosure:</strong> Paid chart links earn a small commission at no extra cost to you. Free chart links earn nothing — we include them because they're genuinely great.
    </div>

    <!-- Jump links -->
    <div class="chart-jump">
      <a href="#audible">Audible</a>
      <a href="#nyt">NYT</a>
      <a href="#popvortex">PopVortex</a>
      <a href="#librivox">LibriVox 🔓</a>
      <a href="#gutenberg">Gutenberg 🔓</a>
      <a href="#gutenberg-ai">Gutenberg AI 🔓</a>
    </div>

    <div class="section-header" style="margin-top:8px;">
      <div>
        <h2>📊 All charts</h2>
        <p class="section-meta">Auto-updated daily via GitHub Actions · Last updated {TODAY}</p>
      </div>
    </div>

    {audible_section}
    <div style="height:24px;"></div>
    {nyt_section}
    <div style="height:24px;"></div>
    {popvortex_section}
    <div style="height:24px;"></div>
    {librivox_section}
    <div style="height:24px;"></div>
    {gutenberg_section}
    <div style="height:24px;"></div>
    {gutenberg_ai_section}

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
  function switchTab(clickedTab, targetId) {{
    const wrap = clickedTab.closest('.chart-wrap');
    wrap.querySelectorAll('.ctab').forEach(t => t.classList.remove('active'));
    wrap.querySelectorAll('.chart-list').forEach(l => l.classList.remove('active'));
    clickedTab.classList.add('active');
    document.getElementById(targetId).classList.add('active');
  }}
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"Fetching bestseller data — {TODAY}")

    print("  Fetching NYT audio-fiction...")
    nyt_fiction = fetch_nyt("audio-fiction")

    print("  Fetching NYT audio-nonfiction...")
    nyt_nonfiction = fetch_nyt("audio-nonfiction")

    print("  Fetching PopVortex...")
    popvortex = fetch_popvortex()

    print("  Fetching LibriVox...")
    librivox = fetch_librivox()

    print("  Fetching Project Gutenberg top downloads...")
    gutenberg = fetch_gutenberg()

    print("  Loading Gutenberg AI curated list...")
    gutenberg_ai = get_gutenberg_ai()

    data = {
        "nyt_fiction":    nyt_fiction,
        "nyt_nonfiction": nyt_nonfiction,
        "popvortex":      popvortex,
        "librivox":       librivox,
        "gutenberg":      gutenberg,
        "gutenberg_ai":   gutenberg_ai,
    }

    html = build_html(data)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"  ✓ Written to {OUTPUT_FILE}")

    # Print summary
    print(f"\nSummary:")
    print(f"  NYT fiction:     {len(nyt_fiction)} titles")
    print(f"  NYT nonfiction:  {len(nyt_nonfiction)} titles")
    print(f"  PopVortex:       {len(popvortex)} titles")
    print(f"  LibriVox:        {len(librivox)} titles")
    print(f"  Gutenberg:       {len(gutenberg)} titles")
    print(f"  Gutenberg AI:    {len(gutenberg_ai)} titles")
    ai_total = sum(1 for b in nyt_fiction + nyt_nonfiction if b.get("ai"))
    if ai_total:
        print(f"  AI-badged titles: {ai_total}")


if __name__ == "__main__":
    main()
