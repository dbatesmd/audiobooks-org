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

def chart_cell_html(book, show_ai=True, show_weeks=False, show_duration=False, show_free=False):
    """Inner markup for one chart-table cell: rank, linked title, author, badges."""
    rank     = book.get("rank", 0)
    title    = book.get("title", "")
    author   = book.get("author", "")
    link     = book.get("link", "#")
    ai       = book.get("ai", False)
    weeks    = book.get("weeks", 0)
    duration = book.get("duration", "")
    top3     = "top" if rank <= 3 else ""

    badges = ""
    if rank == 1:                 badges += '<span class="badge badge-hot">🔥 #1</span>'
    if ai and show_ai:            badges += '<span class="badge badge-ai">⚙ AI narrated</span>'
    if show_weeks and weeks > 1:  badges += f'<span class="badge badge-classic">{weeks} wks on list</span>'
    if show_duration and duration: badges += f'<span class="badge badge-source">{duration}</span>'
    if show_free:                 badges += '<span class="badge badge-free">Free</span>'

    return f"""
        <div class="cell-rank {top3}">{rank}</div>
        <div class="cell-info">
          <a class="cell-title" href="{link}" target="_blank" rel="noopener">{title}</a>
          <p class="cell-author">{author}</p>
          <div class="book-tags">{badges}</div>
        </div>"""


def build_chart_table(data):
    """Render all five charts as ONE table: a column per list, rows by rank.

    Columns are the five unique lists (the old stacked layout showed the NYT
    lists twice — once under an Audible logo; that duplicate is gone, while
    the NYT entries keep their Audible affiliate search links). The column
    order below is the default; visitors can reorder columns in the browser
    (see CHART_REORDER_JS) and the choice persists in localStorage.
    """
    columns = [
        ("nyt-fiction",    "NYT Fiction",    f"NYT Books API · {TODAY} · ⚙ = AI narrated",
         data["nyt_fiction"],    {"show_ai": True,  "show_weeks": True}),
        ("nyt-nonfiction", "NYT Nonfiction", f"NYT Books API · {TODAY} · ⚙ = AI narrated",
         data["nyt_nonfiction"], {"show_ai": True,  "show_weeks": True}),
        ("popvortex",      "PopVortex",      f"Apple iTunes chart · {TODAY}",
         data["popvortex"],      {"show_ai": False}),
        ("librivox",       "LibriVox",       f"Recently added · {TODAY} · Free, no account needed",
         data["librivox"],       {"show_ai": False, "show_duration": True, "show_free": True}),
        ("gutenberg-ai",   "Gutenberg AI",   "Microsoft Neural TTS · Free · No account needed",
         data["gutenberg_ai"],   {"show_ai": False, "show_duration": True, "show_free": True}),
    ]

    head_cells = ""
    for key, label, sub, _books, _kwargs in columns:
        head_cells += f"""
        <th class="chart-th" data-key="{key}" id="col-{key}" draggable="true" scope="col">
          <div class="th-top">
            <button type="button" class="col-move" data-dir="-1" aria-label="Move the {label} column left">◀</button>
            <span class="th-label">{label}</span>
            <button type="button" class="col-move" data-dir="1" aria-label="Move the {label} column right">▶</button>
          </div>
          <div class="th-sub">{sub}</div>
        </th>"""

    ranked = []
    for _key, _label, _sub, books, kwargs in columns:
        ranked.append(({b.get("rank", i + 1): b for i, b in enumerate(books)}, kwargs, books))

    body_rows = ""
    for r in range(1, 11):
        cells = ""
        for (key, _label, _sub, _books, _kwargs), (by_rank, kwargs, books) in zip(columns, ranked):
            book = by_rank.get(r)
            if book is not None:
                cells += f'<td class="chart-cell" data-key="{key}">{chart_cell_html(book, **kwargs)}</td>\n          '
            elif r == 1 and not books:
                cells += f'<td class="chart-cell na" data-key="{key}"><p class="cell-na">Data unavailable — will retry on next update</p></td>\n          '
            else:
                cells += f'<td class="chart-cell empty" data-key="{key}"></td>\n          '
        body_rows += f"      <tr>{cells}</tr>\n"

    return f"""
    <div class="chart-table-wrap">
      <table class="chart-table" id="chart-table">
        <thead>
          <tr>{head_cells}
          </tr>
        </thead>
        <tbody>
{body_rows}        </tbody>
      </table>
    </div>"""


# Column-reorder behaviour for the chart table. This is a PLAIN string on
# purpose: build_html() interpolates it into its f-string as a value, so the
# JavaScript braces below need no doubling. The visitor's column order is
# stored in localStorage only — no cookies, no server state, no account.
CHART_REORDER_JS = """
<script>
(function () {
  var STORAGE_KEY = 'ab_chart_order_v1';
  var table = document.getElementById('chart-table');
  if (!table || !table.tHead) return;
  var headRow = table.tHead.rows[0];

  function currentOrder() {
    var keys = [];
    for (var i = 0; i < headRow.cells.length; i++) {
      keys.push(headRow.cells[i].getAttribute('data-key'));
    }
    return keys;
  }
  var defaultOrder = currentOrder();

  function moveColumn(from, to) {
    if (from === to) return;
    for (var i = 0; i < table.rows.length; i++) {
      var row = table.rows[i];
      if (from < 0 || to < 0 || from >= row.cells.length || to >= row.cells.length) continue;
      var cell = row.cells[from];
      var ref = row.cells[to];
      if (from < to) { row.insertBefore(cell, ref.nextSibling); }
      else { row.insertBefore(cell, ref); }
    }
  }

  function applyOrder(order) {
    var now = currentOrder();
    var target = [];
    var i, idx;
    for (i = 0; i < order.length; i++) {
      if (now.indexOf(order[i]) > -1) target.push(order[i]);
    }
    for (i = 0; i < now.length; i++) {
      if (target.indexOf(now[i]) === -1) target.push(now[i]);
    }
    for (i = 0; i < target.length; i++) {
      idx = currentOrder().indexOf(target[i]);
      if (idx > -1 && idx !== i) moveColumn(idx, i);
    }
  }

  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(currentOrder())); } catch (e) {}
  }
  function load() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : null;
      return (parsed && parsed.length) ? parsed : null;
    } catch (e) { return null; }
  }

  var saved = load();
  if (saved) applyOrder(saved);

  table.addEventListener('click', function (e) {
    var btn = e.target;
    while (btn && !(btn.classList && btn.classList.contains('col-move'))) btn = btn.parentNode;
    if (!btn) return;
    var th = btn;
    while (th && th.tagName !== 'TH') th = th.parentNode;
    if (!th) return;
    var dir = parseInt(btn.getAttribute('data-dir'), 10) || 0;
    moveColumn(th.cellIndex, th.cellIndex + dir);
    save();
  });

  var dragIdx = null;
  headRow.addEventListener('dragstart', function (e) {
    var th = e.target;
    while (th && th.tagName !== 'TH') th = th.parentNode;
    if (!th) return;
    dragIdx = th.cellIndex;
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', th.getAttribute('data-key') || ''); } catch (err) {}
    th.classList.add('dragging');
  });
  headRow.addEventListener('dragover', function (e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  });
  headRow.addEventListener('drop', function (e) {
    e.preventDefault();
    var th = e.target;
    while (th && th.tagName !== 'TH') th = th.parentNode;
    if (th && dragIdx !== null) {
      moveColumn(dragIdx, th.cellIndex);
      save();
    }
    dragIdx = null;
  });
  headRow.addEventListener('dragend', function () {
    dragIdx = null;
    for (var i = 0; i < headRow.cells.length; i++) headRow.cells[i].classList.remove('dragging');
  });

  var reset = document.getElementById('chart-reset');
  if (reset) {
    reset.addEventListener('click', function () {
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
      applyOrder(defaultOrder);
    });
  }
})();
</script>"""


def build_html(data):
    chart_table = build_chart_table(data)

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
  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-Y5MZPXSL29"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-Y5MZPXSL29');
  </script>
</head>
<body class="v2">
  <div class="page">
    <header class="nav">
      <a class="logo" href="/">Audiobooks<em>.org</em></a>
      <nav class="links">
        <a href="/">News</a>
        <a class="hot" href="/bestsellers/">Bestsellers</a>
        <a href="/free-books/">Free</a>
        <a href="/price-check/">Cheap</a>
        <a href="/unlimited/">Unlimited</a>
        <a href="/ai-audiobooks/">AI in Audiobooks</a>
      </nav>
    </header>

    <div class="narr-bar">
      <div class="narr-inner">
        <span class="narr-label">Narration:</span>
        <span class="narr-group" role="img" aria-label="Narration filter (set on the home page)">
          <span class="nbtn">Human</span>
          <span class="nbtn on">Both</span>
          <span class="nbtn">AI</span>
        </span>
      </div>
    </div>

    <div class="ticker"><b>Latest</b><span>Charts refreshed daily — NYT, Audible, Apple, LibriVox and Gutenberg AI bestsellers · Last updated {TODAY}</span></div>

    <section class="hero">
      <div class="kicker">Live charts</div>
      <h1>Audiobook Bestsellers</h1>
      <p>Five charts updated daily — NYT, Audible, PopVortex, LibriVox, and Gutenberg AI. Paid and free, all in one place.</p>
      <div class="ai-legend">⚙ AI narrated badge marks synthetic-voice titles in paid charts</div>
    </section>

    <main class="bs-main">
      <div class="bs-disclosure">
        ℹ️ <strong>Affiliate disclosure:</strong> Paid chart links earn a small commission at no extra cost to you. Free chart links earn nothing — we include them because they're genuinely great.
      </div>

      <div class="chart-jump">
        <a href="#col-nyt-fiction">NYT Fiction</a>
        <a href="#col-nyt-nonfiction">NYT Nonfiction</a>
        <a href="#col-popvortex">PopVortex</a>
        <a href="#col-librivox">LibriVox 🔓</a>
        <a href="#col-gutenberg-ai">Gutenberg AI 🔓</a>
      </div>

      <div class="blockhead">
        <h3>All charts</h3>
        <span class="section-meta">Auto-updated daily · Last updated {TODAY}</span>
      </div>

      <div class="chart-tools">
        <span class="chart-hint">Drag a column header — or use its ◀ ▶ buttons — to put your favourite list first. Your layout is remembered on this device.</span>
        <button type="button" class="chart-reset" id="chart-reset">Reset view</button>
      </div>

      {chart_table}
      {CHART_REORDER_JS}
    </main>

    <footer>
      Independent and reader-supported: we may earn a commission from Audible, Libro.fm, or Chirp links — it never changes which option we recommend first, and the free route is always shown. Charts updated {TODAY}.
    </footer>
  </div>

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
