"""
Affidian rates feed: daily scraper.

Reads every table on the Affidian rates page, sorts the rows into the
categories in categories.json, checks the results, and writes docs/rates.json.

If any check fails, it leaves the old rates.json alone and exits with an
error, so the screens keep the last good rates and GitHub emails you.

Run locally:   python scraper/fetch_rates.py
Test offline:  python scraper/fetch_rates.py --html saved_page.html
Dry run:       python scraper/fetch_rates.py --dry-run
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "scraper" / "categories.json"
OUTPUT_PATH = ROOT / "docs" / "rates.json"

PERCENT_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
EFFECTIVE_RE = re.compile(
    r"effective\s+(?:as\s+of\s+)?([A-Z][a-z]+\.?)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
    re.IGNORECASE,
)
HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


class FeedError(Exception):
    pass


# ---------- reading the page ----------

def fetch_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 AffidianSignageRatesFeed/1.0"
        )
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise FeedError(f"The rates page returned HTTP {resp.status_code}.")
    return resp.text


def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def table_to_grid(table):
    """Turn an HTML table into a list of rows, expanding rowspan/colspan."""
    grid = []
    pending = {}  # col index -> [text, rows_left]
    for tr in table.find_all("tr"):
        row, col = [], 0
        cells = tr.find_all(["td", "th"])
        ci = 0
        while ci < len(cells) or col in pending:
            if col in pending:
                text, left = pending[col]
                row.append(text)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col][1] = left - 1
                col += 1
                continue
            cell = cells[ci]
            ci += 1
            text = clean(cell.get_text(" "))
            span = int(cell.get("colspan", 1) or 1)
            rspan = int(cell.get("rowspan", 1) or 1)
            for _ in range(span):
                row.append(text)
                if rspan > 1:
                    pending[col] = [text, rspan - 1]
                col += 1
        if any(row):
            grid.append(row)
    return grid


def heading_for(table):
    h = table.find_previous(HEADING_TAGS)
    return clean(h.get_text(" ")) if h else ""


def read_tables(soup):
    tables = []
    for t in soup.find_all("table"):
        grid = table_to_grid(t)
        if len(grid) < 2:
            continue
        first_tr = t.find("tr")
        has_th = first_tr is not None and first_tr.find("th") is not None
        header = grid[0] if (has_th or not PERCENT_RE.search(" ".join(grid[0]))) else []
        body = grid[1:] if header else grid
        tables.append({"section": heading_for(t), "header": header, "rows": body})
    return tables


def find_effective(soup):
    m = EFFECTIVE_RE.search(clean(soup.get_text(" ")))
    if not m:
        return None, None
    month, day, year = m.group(1).rstrip("."), m.group(2), m.group(3)
    text = f"Rates effective as of {month} {int(day)}, {year}"
    iso = None
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            iso = datetime.strptime(f"{month} {day} {year}", fmt).date().isoformat()
            break
        except ValueError:
            pass
    return text, iso


# ---------- sorting rows into categories ----------

def rx(pattern):
    return re.compile(pattern, re.IGNORECASE) if pattern else None


def pick_rate_column(header, rows, rate_header):
    if header:
        pat = rx(rate_header or "apy|apr|rate")
        for i, h in enumerate(header):
            if pat.search(h):
                return i
    # Fallback: last column where most rows hold a percent.
    width = max(len(r) for r in rows)
    for i in range(width - 1, 0, -1):
        hits = sum(1 for r in rows if i < len(r) and PERCENT_RE.search(r[i]))
        if hits >= max(1, len(rows) // 2):
            return i
    return None


def detail_text(row, header, detail_pattern, rate_col):
    if not (detail_pattern and header):
        return ""
    pat = rx(detail_pattern)
    parts = [row[i] for i, h in enumerate(header)
             if i not in (0, rate_col) and i < len(row) and pat.search(h) and row[i]]
    return ", ".join(parts)


def build_category(key, cat, tables):
    rows, seen = [], set()
    for src in cat["sources"]:
        sec_re, inc_re, exc_re = rx(src.get("section")), rx(src.get("include", ".")), rx(src.get("exclude"))
        for t in tables:
            if sec_re and not sec_re.search(t["section"]):
                continue
            rate_col = pick_rate_column(t["header"], t["rows"], cat.get("rate_header"))
            if rate_col is None:
                continue
            for r in t["rows"]:
                name = r[0] if r else ""
                if not name or not inc_re.search(name) or (exc_re and exc_re.search(name)):
                    continue
                cell = r[rate_col] if rate_col < len(r) else ""
                m = PERCENT_RE.search(cell)
                if not m:
                    print(f"  ! {key}: skipped '{name}' (no rate in '{cell}')")
                    continue
                detail = detail_text(r, t["header"], cat.get("detail_columns"), rate_col)
                if src.get("title"):
                    detail = ", ".join(p for p in (name, detail) if p)
                    name = src["title"]
                rate_text = f"{m.group(1)}%"
                dedupe = (name.lower(), detail.lower(), rate_text)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                rows.append({
                    "name": name,
                    "detail": detail,
                    "rate": rate_text,
                    "rate_value": float(m.group(1)),
                })
    return {
        "title": cat["title"],
        "rate_label": cat.get("rate_label", "Rate"),
        "note": cat.get("note", ""),
        "rows": rows,
    }


# ---------- checks ----------

def check(feed, config, previous):
    problems = []
    if not feed["effective_text"]:
        problems.append("No 'Rates effective as of ...' date was found on the page.")
    max_rate = config.get("max_rate_percent", 30)
    for key, cat in feed["categories"].items():
        conf = config["categories"][key]
        if conf.get("required") and not cat["rows"]:
            problems.append(f"'{key}' found no rows. Check its sources in categories.json.")
        for r in cat["rows"]:
            if not (0 <= r["rate_value"] <= max_rate):
                problems.append(f"'{key}': {r['name']} has an out-of-range rate {r['rate']}.")
        if previous and not previous.get("sample"):
            old = len(previous.get("categories", {}).get(key, {}).get("rows", []))
            if old >= 2 and len(cat["rows"]) < old / 2:
                problems.append(
                    f"'{key}' dropped from {old} rows to {len(cat['rows'])}. "
                    "The page layout may have changed."
                )
    return problems


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", help="Read a saved copy of the page instead of downloading it")
    ap.add_argument("--dry-run", action="store_true", help="Check everything but don't write rates.json")
    args = ap.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    url = config["source_url"]

    try:
        html = Path(args.html).read_text(encoding="utf-8") if args.html else fetch_html(url)
    except (requests.RequestException, OSError) as e:
        print(f"FAILED: couldn't load the rates page: {e}")
        return 1
    except FeedError as e:
        print(f"FAILED: {e}")
        return 1

    soup = BeautifulSoup(html, "html.parser")
    tables = read_tables(soup)

    print(f"Found {len(tables)} tables on the page:")
    for t in tables:
        print(f"\n  [{t['section'] or 'no heading'}]  columns: {t['header']}")
        for r in t["rows"]:
            print(f"     {r}")
    print()

    if not tables:
        print("FAILED: no rate tables found. The page may have changed or blocked the request.")
        return 1

    effective_text, effective_date = find_effective(soup)
    feed = {
        "source": url,
        "effective_text": effective_text,
        "effective_date": effective_date,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sample": False,
        "categories": {k: build_category(k, c, tables) for k, c in config["categories"].items()},
    }

    print("Rows per category:")
    for k, c in feed["categories"].items():
        print(f"  {k}: {len(c['rows'])}")
        for r in c["rows"]:
            extra = f"  ({r['detail']})" if r["detail"] else ""
            print(f"     {r['name']}{extra}  {r['rate']}")
    print()

    previous = None
    if OUTPUT_PATH.exists():
        try:
            previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None

    problems = check(feed, config, previous)
    if problems:
        print("FAILED. rates.json was NOT changed. Problems:")
        for p in problems:
            print(f"  - {p}")
        return 1

    if args.dry_run:
        print("All checks passed (dry run, nothing written).")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"All checks passed. Wrote {OUTPUT_PATH.relative_to(ROOT)}. {feed['effective_text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
