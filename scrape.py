"""Hot posts from Korean communities, ranked by how much people argue.

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
import time
import urllib.error
import urllib.request
from html import unescape

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# 에펨·개드립은 GitHub Actions 러너에서 막힌다(430/403, 2026-10-03 확인) - PC에서 돌릴 때만 들어온다.
# 아카라이브·뽐뿌·오유·클리앙도 러너에서 막혀서 넣지 않았다.
BOARDS = {
    "디시 실베": "https://gall.dcinside.com/board/lists/?id=dcbest",
    "디시 HIT": "https://gall.dcinside.com/board/lists/?id=hit",
    "에펨 포텐": "https://www.fmkorea.com/best",
    "더쿠 HOT": "https://theqoo.net/hot",
    "개드립": "https://www.dogdrip.net/dogdrip?sort_index=popular",
    "루리웹 베스트": "https://bbs.ruliweb.com/best/all",
    "네이트판": "https://pann.nate.com/talk/ranking",
    "보배드림 베스트": "https://www.bobaedream.co.kr/list?code=best",
    "엠팍 불펜": "https://mlbpark.donga.com/mp/b.php?b=bullpen",
}
# 최신글 목록이라 댓글이 막 달리기 시작한 글이 섞인다 - 이 수보다 적으면 열기를 그만큼 깎는다
MIN_COMMENTS = {"엠팍 불펜": 30}
NEWS_RANKING = "https://news.naver.com/main/ranking/popularMemo.naver"   # 언론사별 댓글 많은 기사


def get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
    # 네이버 랭킹 등 일부는 아직 EUC-KR
    euc = re.search(r"euc-kr|ks_c_5601", ctype, re.I) or re.search(rb'<meta[^>]+charset=["\']?(euc-kr|ks_c_5601)', raw[:3000], re.I)
    return raw.decode("cp949" if euc else "utf-8", errors="replace")


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


def parse_rw(h):
    seen = set()
    for tr in re.findall(r'<tr class="table_body blocktarget[^"]*">.*?</tr>', h, re.S):
        a = re.search(r'<a class="subject_link[^"]*" href="([^"]+)"', tr)
        t = re.search(r'<(?:strong|span) class="text_over">(.*?)</(?:strong|span)>', tr, re.S)
        if not (a and t) or "/market/" in a.group(1) or "/board/1020/" in a.group(1):   # 핫딜(쇼핑) 줄은 뺀다
            continue
        url = "https://bbs.ruliweb.com" + unescape(a.group(1)).split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        c = re.search(r'num_reply[^>]*>\s*\((\d+)\)', tr)
        v = re.search(r'class="hit">\s*([\d,]+)', tr)
        yield {"title": text(t.group(1)), "url": url,
               "views": num(v.group(1)) if v else 0, "comments": int(c.group(1)) if c else 0}


def parse_pann(h):
    body = h[h.find('class="post_wrap"'):]
    for li in body.split("<li>")[1:]:
        a = re.search(r'<h2><a href="(/talk/\d+)"[^>]*title="([^"]*)"', li)
        if not a:
            continue
        c = re.search(r'reple-num">\((\d+)\)', li)
        v = re.search(r'class="count">[^<\d]*([\d,]+)', li)
        yield {"title": text(a.group(2)), "url": "https://pann.nate.com" + a.group(1),
               "views": num(v.group(1)) if v else 0, "comments": int(c.group(1)) if c else 0}


def parse_bobae(h):
    for tr in re.findall(r'<tr itemscope itemtype="http://schema.org/Article">.*?</tr>', h, re.S):
        a = re.search(r'class="bsubject"[^>]*?href="([^"]+)"[^>]*?title="([^"]*)"', tr, re.S)
        if not a:
            continue
        no = re.search(r"No=(\d+)", unescape(a.group(1)))
        if not no:
            continue
        c = re.search(r'totreply">(\d+)', tr)
        v = re.search(r'class="count"[^>]*>([\d,]+)', tr)
        yield {"title": text(a.group(2)), "url": "https://www.bobaedream.co.kr/view?code=best&No=" + no.group(1),
               "views": num(v.group(1)) if v else 0, "comments": int(c.group(1)) if c else 0}


def parse_mlb(h):
    for tr in re.findall(r"<tr>.*?</tr>", h, re.S):
        a = re.search(r"<div class='tit'>\s*<a href='([^']+)'[^>]*class='txt'>(.*?)</a>", tr, re.S)
        if not a:
            continue
        pid = re.search(r"id=(\d+)", unescape(a.group(1)))
        if not pid:
            continue
        c = re.search(r"replycnt'>\[(\d+)\]", tr)
        v = re.search(r"viewV'>([\d,]+)", tr)
        yield {"title": text(a.group(2)), "url": f"https://mlbpark.donga.com/mp/b.php?b=bullpen&id={pid.group(1)}&m=view",
               "views": num(v.group(1)) if v else 0, "comments": int(c.group(1)) if c else 0}


PARSERS = {"디시 실베": parse_dc, "디시 HIT": parse_dc, "에펨 포텐": parse_fm, "더쿠 HOT": parse_tq,
           "개드립": parse_dd, "루리웹 베스트": parse_rw, "네이트판": parse_pann, "보배드림 베스트": parse_bobae,
           "엠팍 불펜": parse_mlb}


def news_ranking(per_press: int = 1) -> list[dict]:
    """네이버 '댓글 많은' 기사: 언론사마다 상위 per_press 건. 커뮤니티 글과 제목이 겹치면
    그 글에 기사 링크를 붙이고 점수를 올리는 데 쓴다 (기사 자체도 후보로 남긴다)."""
    out = []
    for box in re.findall(r'<div class="rankingnews_box">.*?</ul>', get(NEWS_RANKING), re.S):
        press = re.search(r'rankingnews_name">(.*?)</strong>', box)
        items = re.findall(r'<a href="(https://n\.news\.naver\.com/article/\d+/\d+)[^"]*" class="list_title[^"]*"[^>]*>(.*?)</a>',
                           box, re.S)
        for i, (url, title) in enumerate(items[:per_press]):
            out.append({"title": text(title), "url": url, "press": text(press.group(1)) if press else "", "rank": i + 1})
    return out

# Post bodies: the first matching container is the article.
BODY_PATTERNS = [
    r'<div class="write_div".*?</div>\s*</div>',            # dcinside
    r'<article.*?</article>',                                # theqoo / fmkorea
    r'class="[^"]*xe_content[^"]*".*?</div>',               # theqoo(rhymix_content xe_content) / fmkorea / dogdrip
    r'class="ed article-wrapper.*?class="ed article-footer', # dogdrip
    r'class="rd_body.*?class="rd_ft',
    r'class="view_content.*?class="(?:admin_ui )?board_main_bottom',  # ruliweb
    r'id="contentArea".*?class="(?:tvp_area|btnbox|reply)',           # nate pann
    r'class="bodyCont".*?</div>',                                      # bobaedream
    r'id=["\']contentDetail["\'].*?(?:ar_txt_tool|</div>\s*</div>)',    # mlbpark
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


def get_list(url: str) -> str:
    """목록 페이지: 연결 시간 초과(디시가 가끔 그런다)면 잠깐 쉬고 한 번만 다시 시도.
    차단(4xx)은 다시 시도하지 않는다."""
    try:
        return get(url)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError):
        time.sleep(15)
        return get(url, timeout=30)


def collect() -> tuple[list[dict], list[str]]:
    posts, warnings = [], []
    for board, url in BOARDS.items():
        try:
            rows = list(PARSERS[board](get_list(url)))
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
    for board, rows in by_board.items():
        ordered = sorted(rows, key=lambda r: r["comments"])
        floor = MIN_COMMENTS.get(board, 0)
        for i, r in enumerate(ordered):
            r["heat"] = (i + 1) / len(ordered) * (min(1.0, r["comments"] / floor) if floor else 1.0)
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
