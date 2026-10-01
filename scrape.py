"""Hot posts from four Korean communities, ranked by how much people argue.

    python scrape.py            # prints the ranked list as JSON

Each board is parsed from its public list page. A board that fails (blocked,
layout change) is skipped with a warning - the run continues on the rest.
Comment count is the main signal (the reference channel's hits are the posts
people fight about); a story that trends on several boards at once gets a
boost.
"""
import difflib
import json
import re
import sys
import urllib.request
from html import unescape

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

BOARDS = {
    "디시 실베": "https://gall.dcinside.com/board/lists/?id=dcbest",
    "에펨 포텐": "https://www.fmkorea.com/best",
    "더쿠 HOT": "https://theqoo.net/hot",
    "개드립": "https://www.dogdrip.net/dogdrip?sort_index=popular",
}


def get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def text(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", s))).strip()


def num(s) -> int:
    m = re.search(r"[\d,]+", s or "")
    return int(m.group().replace(",", "")) if m else 0


def parse_dc(h):
    for tr in re.findall(r'<tr class="ub-content us-post.*?</tr>', h, re.S):
        a = re.search(r'<a\s+href="(/board/view[^"]+)"[^>]*>(.*?)</a>', tr, re.S)
        if not a:
            continue
        rp = re.search(r'reply_num">\[(\d+)', tr)
        v = re.search(r'gall_count">([^<]*)', tr)
        yield {"title": text(a.group(2)), "url": "https://gall.dcinside.com" + unescape(a.group(1)),
               "views": num(v.group(1)) if v else 0, "comments": int(rp.group(1)) if rp else 0}


def parse_fm(h):
    for li in re.findall(r'<li class="li .*?</li>', h, re.S):
        t = re.search(r'ellipsis-target">(.*?)</span>', li, re.S)
        u = re.search(r"document_srl=(\d+)", li)
        if not (t and u):
            continue
        c = re.search(r'comment_count">\[(\d+)', li)
        v = re.search(r'class="count">(\d+)', li)
        yield {"title": text(t.group(1)), "url": "https://www.fmkorea.com/" + u.group(1),
               "votes": int(v.group(1)) if v else 0, "comments": int(c.group(1)) if c else 0}


def parse_tq(h):
    body = h[h.find("<tbody"):]
    for tr in re.findall(r"<tr(?![^>]*notice)[^>]*>.*?</tr>", body, re.S):
        a = re.search(r'class="title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>(.*?)</td>', tr, re.S)
        if not a:
            continue
        c = re.search(r'replyNum">([\d,]+)', a.group(3))
        v = re.search(r'm_no">([\d,]+)', tr)
        yield {"title": text(a.group(2)), "url": "https://theqoo.net" + a.group(1),
               "views": num(v.group(1)) if v else 0, "comments": num(c.group(1)) if c else 0}


def parse_dd(h):
    for li in re.findall(r'<li class="ed flex flex-left flex-middle webzine">.*?</li>', h, re.S):
        a = re.search(r'href="/dogdrip/(\d+)[^"]*" class="ed title-link"[^>]*>(.*?)</a>\s*(?:<span[^>]*>(\d+))?', li, re.S)
        if not a:
            continue
        up = re.search(r'fa-thumbs-up"></i></span>\s*<span[^>]*>(\d+)', li)
        yield {"title": text(a.group(2)), "url": "https://www.dogdrip.net/dogdrip/" + a.group(1),
               "votes": int(up.group(1)) if up else 0, "comments": int(a.group(3) or 0)}


PARSERS = {"디시 실베": parse_dc, "에펨 포텐": parse_fm, "더쿠 HOT": parse_tq, "개드립": parse_dd}

# Post bodies: the first matching container is the article.
BODY_PATTERNS = [
    r'<div class="write_div".*?</div>\s*</div>',            # dcinside
    r'<article.*?</article>',                                # theqoo / fmkorea
    r'class="xe_content".*?</div>',                          # fmkorea / dogdrip
    r'class="ed article-wrapper.*?class="ed article-footer', # dogdrip
    r'class="rd_body.*?class="rd_ft',
]


def post_body(url: str, limit: int = 1800) -> dict:
    """Plain text of a post plus any links in it (news articles, videos) -
    the editor needs those to find the original reporting."""
    try:
        h = get(url)
    except Exception as ex:
        return {"text": "", "links": [], "error": str(ex)[:120]}
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    chunk = ""
    for pat in BODY_PATTERNS:
        m = re.search(pat, h, re.S)
        if m:
            chunk = m.group(0)
            break
    links = sorted(set(re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+|'
                                  r'(?:n\.)?news\.[\w.]+/[^\s"<>]+|v\.daum\.net/v/\d+|[\w.]+\.co\.kr/[^\s"<>]+)', chunk)))
    body = re.sub(r"<br\s*/?>|</p>|</div>", "\n", chunk)
    body = re.sub(r"\n\s*\n+", "\n", text_keep_lines(body)).strip()
    return {"text": body[:limit], "links": links[:8]}


def text_keep_lines(s: str) -> str:
    return "\n".join(re.sub(r"[ \t]+", " ", unescape(re.sub(r"<[^>]+>", "", line))).strip()
                     for line in s.split("\n"))


def collect() -> tuple[list[dict], list[str]]:
    posts, warnings = [], []
    for board, url in BOARDS.items():
        try:
            rows = list(PARSERS[board](get(url)))
            if not rows:
                warnings.append(f"{board}: 목록 파싱 0건 (레이아웃 변경 또는 차단 페이지)")
            for r in rows:
                r["board"] = board
            posts += rows
        except Exception as ex:
            warnings.append(f"{board}: {type(ex).__name__} {str(ex)[:100]}")
    return posts, warnings


def rank(posts: list[dict]) -> list[dict]:
    # Comment percentile within each board, so boards with different scales mix.
    by_board: dict[str, list[dict]] = {}
    for p in posts:
        by_board.setdefault(p["board"], []).append(p)
    for rows in by_board.values():
        ordered = sorted(rows, key=lambda r: r["comments"])
        for i, r in enumerate(ordered):
            r["heat"] = (i + 1) / len(ordered)
    # Same story on several boards = it is genuinely the talk of the day.
    for p in posts:
        others = {q["board"] for q in posts if q["board"] != p["board"] and
                  difflib.SequenceMatcher(None, p["title"], q["title"]).ratio() > 0.55}
        p["also_on"] = sorted(others)
        p["score"] = round(p["heat"] + 0.5 * len(others), 3)
    return sorted(posts, key=lambda r: -r["score"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    posts, warns = collect()
    for w in warns:
        print("WARN", w, file=sys.stderr)
    print(json.dumps(rank(posts)[:30], ensure_ascii=False, indent=1))
