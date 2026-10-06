"""Build assets/irasutoya.json.gz - every いらすとや post title with its image URL - from
the site's Blogger feed (150 posts a page, ~170 pages, a few minutes).

    python illust_index.py

illust.search() looks titles up in this file instead of the site's search page: from
GitHub's runners that page answers 429 for whole videos (2026-10-06: 19-25 failed
searches per video, those scenes went out blank). Only the images are fetched from the
site's CDN, which has never refused. Re-run now and then to pick up new drawings.
"""
import gzip
import json
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "assets" / "irasutoya.json.gz"
FEED = "https://www.irasutoya.com/feeds/posts/summary?alt=json&max-results=150&start-index={}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def page(start: int) -> dict:
    for attempt in range(5):
        try:
            req = urllib.request.Request(FEED.format(start), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["feed"]
        except Exception as ex:
            print(f"  page {start}: {ex} - retry")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"feed page {start} kept failing")


def main() -> None:
    rows, start, total = [], 1, None
    while total is None or start <= total:
        feed = page(start)
        total = int(feed["openSearch$totalResults"]["$t"])
        entries = feed.get("entry", [])
        if not entries:
            break
        for e in entries:
            thumb = (e.get("media$thumbnail") or {}).get("url")
            if thumb:   # notices and index pages have no drawing
                rows.append([e["title"]["$t"], thumb])
        start += len(entries)
        print(f"  {start - 1}/{total}")
        time.sleep(0.5)
    OUT.write_bytes(gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()))
    print(f"{len(rows)} drawings -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
