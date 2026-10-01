"""GitHub Actions side of topic discovery: rank today's hot posts and write
inbox/latest.json for the cloud routine to read.

    python gather.py

The routine's sandbox cannot reach the communities (egress proxy), but the
Actions runner can reach 디시 실베 and 더쿠 HOT. Only facts are committed -
titles, URLs, comment counts and the headlines of news links found in the
post - never post bodies or article text, since this repository is public.
"""
import datetime as dt
import json
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path

import scrape

REPO = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))
NEWS = re.compile(r"(n\.news\.naver\.com|news\.|v\.daum\.net|\.co\.kr|youtube\.com/watch|youtu\.be)")


def used_posts() -> set[str]:
    used = set()
    hist = REPO / "state" / "history.json"
    if hist.exists():
        used |= {h.get("source_post") for h in json.loads(hist.read_text(encoding="utf-8"))}
    for f in (REPO / "scripts").glob("*.json"):
        try:
            used.add(json.loads(f.read_text(encoding="utf-8")).get("source_post"))
        except ValueError:
            pass
    return {u for u in used if u}


def headline(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": scrape.UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            h = r.read(200_000).decode("utf-8", errors="replace")
    except Exception:
        return ""
    m = (re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', h)
         or re.search(r"<title[^>]*>(.*?)</title>", h, re.S))
    return re.sub(r"\s+", " ", unescape(m.group(1))).strip()[:140] if m else ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    posts, warns = scrape.collect()
    used = used_posts()
    ranked = [p for p in scrape.rank(posts) if p["url"] not in used][:20]
    for p in ranked[:12]:
        links = [l for l in scrape.post_body(p["url"]).get("links", []) if NEWS.search(l)][:3]
        p["news"] = [{"url": l, "headline": headline(l)} for l in links]
    out = {"generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
           "warnings": warns, "posts": ranked}
    path = REPO / "inbox" / "latest.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(ranked)} posts ({', '.join(sorted({p['board'] for p in ranked}))}); warnings: {warns}")
    return 0 if ranked else 1


if __name__ == "__main__":
    sys.exit(main())
