"""GitHub Actions side of topic discovery: rank today's hot posts and write
inbox/latest.json for the cloud routine to read.

    python gather.py

The routine's sandbox cannot reach the communities (egress proxy), but the
Actions runner can reach 디시(실베·HIT), 더쿠, 루리웹, 네이트판, 보배드림, 엠팍 and
네이버 뉴스 랭킹 (에펨·개드립·아카라이브는 러너에서 막힌다). Only facts are committed -
titles, URLs, comment counts and the headlines of news links found in the
post - never post bodies or article text, since this repository is public.
"""
import datetime as dt
import difflib
import json
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

import scrape

REPO = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))
NEWS = re.compile(r"(n\.news\.naver\.com|news\.|v\.daum\.net|\.co\.kr|youtube\.com/watch|youtu\.be)")
# 커뮤니티 자체 이미지·첨부 서버는 뉴스가 아니다 (dcimg*.dcinside.co.kr/viewimage.php 등)
NOT_NEWS = re.compile(r"(dcinside|dcimg|theqoo|fmkorea|dogdrip|ruliweb|pann\.nate|bobaedream|mlbpark|pstatic|viewimage|\.(jpe?g|png|gif|webp|mp4)(\?|$))", re.I)


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


def bare(title: str) -> str:
    """'[잡갤] 제목' / '이누야샤)제목' 같은 말머리를 뗀 제목 (기사 제목과 비교용)."""
    return re.sub(r"^\s*(\[[^\]]{1,12}\]|[^\s)]{1,10}\))\s*", "", title)


def match_news(posts: list[dict], news: list[dict]) -> None:
    """커뮤니티 글 제목이 '댓글 많은 기사' 제목과 겹치면 기사 링크를 붙이고 점수를 올린다."""
    for p in posts:
        t = bare(p["title"])
        best = max(news, key=lambda n: difflib.SequenceMatcher(None, t, n["title"]).ratio(), default=None)
        if best and difflib.SequenceMatcher(None, t, best["title"]).ratio() > 0.5:
            p["in_news"] = best["press"]
            p["news"] = [{"url": best["url"], "headline": best["title"]}]
            p["score"] = round(p["score"] + 0.3, 3)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    posts, warns = scrape.collect()
    try:
        news = scrape.news_ranking()
    except Exception as ex:
        news = []
        warns.append(f"네이버 랭킹: {type(ex).__name__} {str(ex)[:100]}")
    used = used_posts()
    ranked = scrape.rank(posts)
    match_news(ranked, news)
    ranked = sorted((p for p in ranked if p["url"] not in used), key=lambda r: -r["score"])[:40]
    for p in ranked[:20]:
        if p.get("news"):
            continue
        time.sleep(0.5)   # 글 본문은 한 사이트에 몰아서 여러 번 들어가니 간격을 둔다
        links = [l for l in scrape.post_body(p["url"]).get("links", [])
                 if NEWS.search(l) and not NOT_NEWS.search(l)][:3]
        p["news"] = [{"url": l, "headline": headline(l)} for l in links]
    out = {"generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
           "warnings": warns, "posts": ranked,
           "news_hot": [n for n in news if n["url"] not in used][:40]}
    path = REPO / "inbox" / "latest.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(ranked)} posts ({', '.join(sorted({p['board'] for p in ranked}))}), "
          f"{len(out['news_hot'])} news; warnings: {warns}")
    return 0 if ranked else 1


if __name__ == "__main__":
    sys.exit(main())
