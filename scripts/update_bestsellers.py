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


# ── Internal price-check links (chart -> our own pages) ─────────────────
# chart-links.json (repo root) maps normalised titles to price-check slugs.
# A matching chart cell links to OUR /price-check/<slug>/ page instead of
# straight out to a store; unmatched titles keep their outbound links.
import json as _json
def _norm_title(t):
    t = (t or '').lower().replace('&', ' and ')
    t = re.sub(r"['’]", '', t)
    t = re.sub(r'[^a-z0-9]+', ' ', t).strip()
    t = re.sub(r'\s+', ' ', t)
    if t.startswith('the '):
        t = t[4:]
    return t
try:
    _mpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'chart-links.json')
    with open(_mpath, encoding='utf-8') as _f:
        CHART_LINKS = dict(sorted(((k, v) for k, v in _json.load(_f).items() if not k.startswith('_')), key=lambda kv: -len(kv[0])))
except Exception:
    CHART_LINKS = {}
def chart_link_for(title):
    if not CHART_LINKS:
        return None
    t = _norm_title(re.sub(r'\s*\([^)]*\)\s*$', '', title or ''))
    if t in CHART_LINKS:
        return CHART_LINKS[t]
    for key, slug in CHART_LINKS.items():
        if t.startswith(key + ' ') or key.startswith(t + ' '):
            return slug
    return None

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

    internal = chart_link_for(title)
    if internal:
        title_link = f'<a class="cell-title" href="/price-check/{internal}/">{title}</a>'
    else:
        title_link = f'<a class="cell-title" href="{link}" target="_blank" rel="noopener">{title}</a>'

    return f"""
        <div class="cell-rank {top3}">{rank}</div>
        <div class="cell-info">
          {title_link}
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

    def cell_narration(key, book):
        if key == "gutenberg-ai": return "ai"
        if key == "librivox": return "human"
        if key == "popvortex": return "human ai"
        return "ai" if (book and book.get("ai")) else "human"

    ranked = []
    for _key, _label, _sub, books, kwargs in columns:
        ranked.append(({b.get("rank", i + 1): b for i, b in enumerate(books)}, kwargs, books))

    body_rows = ""
    for r in range(1, 11):
        cells = ""
        for (key, _label, _sub, _books, _kwargs), (by_rank, kwargs, books) in zip(columns, ranked):
            book = by_rank.get(r)
            if book is not None:
                cells += f'<td class="chart-cell" data-key="{key}" data-narration="{cell_narration(key, book)}">{chart_cell_html(book, **kwargs)}</td>\n          '
            elif r == 1 and not books:
                cells += f'<td class="chart-cell na" data-key="{key}" data-narration="human ai"><p class="cell-na">Data unavailable — will retry on next update</p></td>\n          '
            else:
                cells += f'<td class="chart-cell empty" data-key="{key}" data-narration="human ai"></td>\n          '
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



# Page design for the rebuilt site (2026-10-29): the charts page carries
# its CSS inline — no external stylesheet — so a stale cached styles.css
# can never leave it unformatted again. Rules = the site bundle (de-scoped)
# plus the chart-table rules.
PAGE_CSS = """.narr-bar{display:flex;justify-content:center;align-items:center;padding:9px 28px;background:#f4f4f2;border-bottom:1px solid #d9d9d2}.narr-inner{display:flex;align-items:center;gap:10px}.narr-label{font-size:12px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:#3a3a36}.narr-group{display:inline-flex;gap:6px}.narr-group button{border:3px solid #c9c9c4;border-radius:4px;padding:5px 16px;font-size:13px;font-weight:700;cursor:pointer;background:#fff;color:#333}.narr-group button.on{border-color:#ff6b00;background:#ffe8d6;color:#8a3c00;font-weight:800}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#eef0f3;color:#17202a;margin:0}.page{max-width:1220px;margin:0 auto;background:#fffdf8;box-shadow:0 12px 34px #0000001a;border:1px solid #e7e0cf;min-height:100vh}.nav{display:flex;justify-content:space-between;align-items:center;padding:16px 28px;border-bottom:1px solid #eee6d2;background:#fff}.logo{font-weight:900;font-size:22px;color:#1b2a4a;text-decoration:none}.logo em{color:#c47b12;font-style:normal}.links{font-size:13.5px;font-weight:700}.links a{margin-left:16px;color:#46505c;text-decoration:none}.links a.hot{color:#a11;border-bottom:2px solid #c0392b;padding-bottom:2px}.ticker{background:#1b2a4a;color:#eef2f7;padding:9px 28px;font-size:13px;display:flex;gap:10px;flex-wrap:wrap}.ticker b{color:#f5b942;letter-spacing:.08em;font-size:11px;text-transform:uppercase;padding-top:2px}.hero{padding:32px 28px 24px;background:#fdf6e9;border-bottom:1px solid #eee6d2}.kicker{font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:#a96f0d}.hero h1,.hero h2{font-family:Georgia,serif;font-size:38px;line-height:1.05;margin:8px 0 10px;color:#1b2a4a;max-width:780px}.hero p{font-size:16px;line-height:1.55;color:#3f4a56;max-width:720px;margin:0}.main{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:0;align-items:start}.news{padding:24px 28px;border-right:1px solid #eee6d2}.block{margin-bottom:30px}.block:last-child{margin-bottom:6px}.blockhead{display:flex;justify-content:space-between;align-items:baseline;gap:14px;border-bottom:2.5px solid #1b2a4a;padding-bottom:8px;margin-bottom:14px}.blockhead h3{font-family:Georgia,serif;font-size:25px;color:#1b2a4a;margin:0}.blockhead a{font-size:13px;font-weight:800;color:#a96f0d;text-decoration:none;white-space:nowrap}.releases{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.rel{border:1px solid #e7e2d4;border-radius:14px;overflow:hidden;background:#fff}.cover{height:92px;display:flex;align-items:flex-end;padding:10px;color:#fff;font-family:Georgia,serif;font-size:15px;line-height:1.2}.rel .body{padding:12px}.rel h5{margin:0 0 4px;font-size:14.5px;color:#1b2a4a}.rel h5 a{color:inherit;text-decoration:none}.rel p{margin:0;font-size:12.5px;color:#66707c;line-height:1.45}.sample{font-size:10.5px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#9aa3ad}table{width:100%;border-collapse:collapse;font-size:13.5px;background:#fff}th,td{padding:10px 11px;border-bottom:1px solid #e9e6da;text-align:left;vertical-align:top}th{background:#1b2a4a;color:#fff;font-size:11.5px;letter-spacing:.05em;text-transform:uppercase}.best{background:#fff8e6;font-weight:700}.headline{padding:12px 0;border-bottom:1px solid #eee6d2}.headline:last-child{border-bottom:0}.headline .date{font-size:11px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#a96f0d}.headline h5{margin:3px 0 4px;font-size:16.5px;color:#1b2a4a}.headline h5 a{color:inherit}.headline p{margin:0;font-size:13.5px;color:#55606b;line-height:1.5}footer{padding:20px 28px;background:#1b2a4a;color:#cbd5e1;font-size:12.5px;line-height:1.6}@media(max-width:900px){.main{grid-template-columns:1fr}.news{border-right:0}.releases{grid-template-columns:1fr}.links{display:none}}.rail{padding:24px 22px;background:#fbf8ef;position:sticky;top:0}.rail h3{font-family:Georgia,serif;color:#1b2a4a;margin:0 0 4px;font-size:21px}.rail p.sub{font-size:13px;color:#66707c;margin:0 0 14px;line-height:1.45}.way{border-radius:14px;padding:16px;margin-bottom:12px;border:1.5px solid;position:relative}.way h4{margin:4px 0 6px;font-size:18px}.way p{font-size:13px;line-height:1.5;color:#44505c;margin:0 0 10px}.way a{font-weight:800;font-size:13px;text-decoration:none}.way a:after{content:"";position:absolute;inset:0;border-radius:14px}.way:hover{filter:brightness(.985)}.price{font-family:Georgia,serif;font-size:24px}.f{background:#eaf4ff;border-color:#b9d6fb}.f h4,.f a{color:#1d4ed8}.c{background:#fff3df;border-color:#f0d39a}.c h4,.c a{color:#975a06}.u{background:#e9f5ec;border-color:#b7dfc0}.u h4,.u a{color:#166534}.start{border:1px solid #e7e2d4;background:#fff;border-radius:14px;padding:16px;position:relative}.start h4{font-family:Georgia,serif;color:#1b2a4a;margin:0 0 6px}.start p{font-size:13px;color:#55606b;line-height:1.5;margin:0}.start a:after{content:"";position:absolute;inset:0;border-radius:14px}.start:hover{filter:brightness(.985)}@media(max-width:900px){.rail{position:static}}
/* ── Badges / Pills ──────────────────────────────────────────── */
.badge {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 20px;
  white-space: nowrap;
}
.badge-teal   { background: var(--teal-pale);  color: var(--teal-dark); }
.badge-amber  { background: var(--amber-mid);  color: var(--amber-dark); }
.badge-purple { background: var(--purple-mid); color: var(--purple-dark); }
.badge-deal   { background: var(--amber-light);color: #633806; }
.badge-trial  { background: var(--teal-light); color: var(--teal-dark); }
.badge-unltd  { background: var(--purple-light);color: var(--purple-dark); }
.badge-new    { background: var(--teal-light); color: var(--teal-dark); }
.badge-hot    { background: #FAECE7; color: #712B13; }
.badge-classic{ background: var(--blue-light); color: #0C447C; }
.section-meta { font-size: 0.8rem; color: var(--text-muted); }
/* ── CHART TABLES ────────────────────────────────────────────── */
.chart-wrap {
  border: 1px solid var(--border); border-radius: var(--radius-lg);
  overflow: hidden; margin-bottom: 24px;
}
.chart-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 18px; background: var(--bg-off);
  border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 10px;
}
.chart-source { display: flex; align-items: center; gap: 10px; }
.chart-logo {
  font-size: 0.78rem; font-weight: 600; padding: 4px 10px;
  border-radius: var(--radius-sm);
}
.chart-date  { font-size: 0.78rem; color: var(--text-muted); }
.chart-tabs  { display: flex; gap: 6px; }
.chart-list { display: none; }
.chart-list.active { display: block; }
.book-tags { display: flex; gap: 4px; margin-top: 3px; }
.chart-note {
  padding: 10px 18px; background: var(--bg-off);
  border-top: 1px solid var(--border);
  font-size: 0.78rem; color: var(--text-muted);
}
.chart-note a { color: var(--teal-mid); }
.chart-header { flex-direction: column; align-items: flex-start; }
.ai-legend {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.8rem; color: var(--purple-dark);
  background: var(--purple-light); padding: 6px 14px;
  border-radius: 20px; border: 1px solid var(--purple-mid); margin-top: 12px;
}
/* Main column */
.bs-main { padding: 24px 28px 32px; }
.bs-disclosure {
  background: #fff8e6; border: 1px solid #e7e2d4; border-radius: 10px;
  padding: 12px 16px; font-size: 13px; color: #5b4a1f; margin-bottom: 20px;
}
.chart-jump { display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 20px; }
.chart-jump a {
  font-size: 0.8rem; font-weight: 600; padding: 6px 14px;
  border-radius: 20px; border: 1.5px solid #e7e2d4; color: #46505c; background: #fff;
  transition: all 0.12s;
}
.chart-jump a:hover { background: #fdf6e9; border-color: #c47b12; color: #a96f0d; }
.blockhead .section-meta { font-size: 12.5px; color: #66707c; }
/* Charts inside the v2 shell (base classes defined above still apply) */
.chart-wrap {
  border: 1px solid #e7e2d4; border-radius: 14px;
  overflow: hidden; margin-bottom: 24px; background: #fff;
}
.chart-header { background: #fdf6e9; border-bottom: 1px solid #eee6d2; }
.badge-ai   { background: var(--purple-light); color: var(--purple-dark); border: 1px solid var(--purple-mid); }
.badge-free { background: var(--teal-light); color: var(--teal-dark); }
.badge-source { background: var(--bg-off); color: var(--text-muted); border: 1px solid var(--border); }
.chart-note { background: #fdf6e9; border-top: 1px solid #eee6d2; color: #66707c; }
.chart-hint { font-size: 12.5px; color: #66707c; }
.chart-reset {
  font: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer;
  padding: 6px 14px; border-radius: 20px; background: #fff;
  border: 1.5px solid #e7e2d4; color: #46505c; transition: all 0.12s;
}
.chart-reset:hover { background: #fdf6e9; border-color: #c47b12; color: #a96f0d; }
.chart-table-wrap {
  overflow-x: auto; border: 1px solid #e7e2d4; border-radius: 14px;
  background: #fff; margin-bottom: 24px;
}
table.chart-table { border-collapse: collapse; width: 100%; min-width: 900px; }
.chart-table th.chart-th {
  background: #1b2a4a; color: #fff; text-align: left; vertical-align: top;
  padding: 12px; width: 20%; cursor: grab;
  border-right: 1px solid rgba(255,255,255,.14);
}
.chart-table th.chart-th:last-child { border-right: none; }
.chart-table th.chart-th.dragging { opacity: .55; }
.th-top { display: flex; align-items: center; gap: 6px; }
.th-label { font-family: Georgia, serif; font-size: 16px; font-weight: 700; flex: 1; }
.col-move {
  font: inherit; font-size: 10px; line-height: 1; cursor: pointer;
  width: 20px; height: 20px; border-radius: 50%; flex: none; padding: 0;
  border: 1px solid rgba(255,255,255,.45); background: transparent; color: #f5b942;
  display: inline-flex; align-items: center; justify-content: center;
}
.col-move:hover { background: rgba(255,255,255,.16); }
.th-sub { font-size: 11px; font-weight: 400; color: #cbd5e1; margin-top: 5px; line-height: 1.45; }
.chart-table td.chart-cell {
  vertical-align: top; padding: 12px; width: 20%;
  border-top: 1px solid #e9e6da; border-right: 1px solid #e9e6da;
}
.chart-table td.chart-cell:last-child { border-right: none; }
.chart-table tbody tr:hover td.chart-cell { background: #fffdf8; }
.chart-cell .cell-rank {
  font-family: Georgia, serif; font-size: 20px; font-weight: 700;
  color: #98a2b3; line-height: 1; margin-bottom: 6px;
}
.chart-cell .cell-rank.top { color: #c47b12; }
.cell-title {
  font-weight: 700; font-size: 14.5px; color: #17202a; line-height: 1.3;
  text-decoration: none; display: inline-block;
}
.cell-title:hover { color: #a96f0d; text-decoration: underline; }
.cell-author { font-size: 12.5px; color: #66707c; margin: 3px 0 0; }
.chart-cell .book-tags { margin-top: 7px; }
.chart-cell.empty { background: #fbfaf6; }
.cell-na { font-size: 13px; color: #66707c; margin: 0; }
.bs-main { padding: 20px 16px 28px; }
.bs-main{padding:24px 28px}
.chart-cell{position:relative}
.chart-cell.narr-hidden .cell-info,.chart-cell.narr-hidden .cell-rank{visibility:hidden}
.chart-cell.narr-hidden::after{content:'—';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#9aa3ad;font-size:18px}
"""

# Narration switch for the charts page: same localStorage key as the rest
# of the site (ab-narration), filtering chart cells by data-narration.
NARR_JS = """
<script>
(function () {
  var KEY = 'ab-narration';
  var mode = 'both';
  try { mode = localStorage.getItem(KEY) || 'both'; } catch (e) {}
  if (['human', 'both', 'ai'].indexOf(mode) < 0) mode = 'both';
  var btns = document.querySelectorAll('.narr-group button');
  function apply() {
    btns.forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-narr') === mode); });
    var cells = document.querySelectorAll('#chart-table td.chart-cell');
    cells.forEach(function (td) {
      var n = td.getAttribute('data-narration') || 'human ai';
      var show = (mode === 'both') || (n.indexOf(mode) >= 0);
      td.classList.toggle('narr-hidden', !show);
    });
  }
  btns.forEach(function (b) {
    b.addEventListener('click', function () {
      mode = b.getAttribute('data-narr');
      try { localStorage.setItem(KEY, mode); } catch (e) {}
      apply();
    });
  });
  apply();
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
  <style>
{PAGE_CSS}
  </style>
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
        <span class="narr-group" role="group" aria-label="Narration filter">
          <button type="button" data-narr="human">Human</button>
          <button type="button" data-narr="both">Both</button>
          <button type="button" data-narr="ai">AI</button>
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
      {NARR_JS}
    </main>

    <footer>
      Independent and reader-supported: we may earn a commission from Audible, Libro.fm, or Chirp links — it never changes which option we recommend first, and the free route is always shown. Prices are checked and dated; if a price is past its freshness window we hide the number rather than show a stale one. Charts updated {TODAY}.
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
