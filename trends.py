"""What people are searching and talking about right now - written into inbox/latest.json as "trends".

    python trends.py            # prints both lists

2026-10-27 사용자: "치이카와를 제외하더라도 유행에 민감하게 반응은 해야지". The inbox only ranked posts by
comments, so a word every board was using (a character, a snack, a game, a meme) never showed up as such.
  - google: Google Trends daily searches for Korea (public RSS, no key) with the news headlines it attaches,
  - buzz: words that several different boards put in their hot-post titles at once.
Only words, counts, headlines and URLs are kept (the repository is public).
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

import scrape

GT_RSS = "https://trends.google.com/trending/rss?geo=KR"
HT = "{https://trends.google.com/trending/rss}"
# title words that every board uses whatever is trending
STOP = set("""오늘 지금 진짜 근데 이거 그냥 너무 요즘 이번 우리 사람 사람들 여자 남자 한국 한국인 일본 중국 미국 근황 레전드 논란 충격
결국 역대급 후기 정리 사진 영상 이유 상황 반응 댓글 실시간 속보 단독 공식 발표 대한 관련 정도 하는 하고 했다 있는 없는 이게 이건 어제
내일 와이프 남편 엄마 아빠 회사 친구 ㅋㅋ ㅋㅋㅋ ㄷㄷ 지금도 다시 처음 마지막 생각 문제 사건 사고 해외 국내 the
jpg jpeg gif png webp mp4 txt 펌 유머 이슈 갤러리 manhwa
때문 의외 충격적인 충격적 여성 남성 여자들 남자들 이유가 이유는 엄청난 미친 대박 ㄹㅇ 혹시 무슨 어떻게 왜 진짜로 완전 같은 하는법
그래서 그리고 하지만 이제 아직 벌써 계속 제일 가장 많이 많은 모든 모두 자기 본인 가족 아이 애들 직장인 한국에서 나라 중국인 일본인
좋은 나쁜 만에 모르 news 미녀 만화 현역 오늘자 다른 화난 누나 형님""".split())
WORD = re.compile(r"[가-힣A-Za-z0-9]{2,}")
# verb/adjective forms (했는데, 먹었다, 좋은) are not things people search
VERBISH = re.compile(r"(는데|었|았|했|겠|하는|한다|됐|된다|ㄴ다|니까|어서|아서|라고|는지)")
JOSA = re.compile(r"(은|는|이|가|을|를|의|에|에서|에게|으로|로|와|과|도|만|까지|부터|이랑|랑|한테|께서)$")


def google(limit: int = 20) -> list[dict]:
    root = ET.fromstring(scrape.get(GT_RSS))
    out = []
    for it in root.iter("item"):
        news = [{"title": (n.findtext(f"{HT}news_item_title") or "").strip(),
                 "url": (n.findtext(f"{HT}news_item_url") or "").strip()} for n in it.findall(f"{HT}news_item")][:2]
        out.append({"keyword": (it.findtext("title") or "").strip(),
                    "traffic": (it.findtext(f"{HT}approx_traffic") or "").strip(), "news": news})
    return out[:limit]


def _stem(w: str) -> str:
    s = JOSA.sub("", w) if len(w) > 2 else w
    return s if len(s) >= 2 else w


def buzz(posts: list[dict], limit: int = 15) -> list[dict]:
    """Words in hot-post titles of at least two different boards (sites), most boards first."""
    sites, titles = defaultdict(set), defaultdict(list)
    for p in posts:
        for w in {_stem(w) for w in WORD.findall(p.get("title", ""))}:
            if w in STOP or w.isdigit() or VERBISH.search(w):
                continue
            sites[w].add(scrape.site(p.get("board", "")))
            if len(titles[w]) < 3:
                titles[w].append(p["title"])
    hot = [w for w in sites if len(sites[w]) >= 2]
    hot.sort(key=lambda w: (-len(sites[w]), -len(titles[w])))
    # drop a word that is only a piece of a longer hot word with the same boards (치이 / 치이카와)
    hot = [w for w in hot if not any(w != o and w in o and sites[o] == sites[w] for o in hot)]
    return [{"word": w, "boards": sorted(sites[w]), "titles": titles[w]} for w in hot[:limit]]


def collect(posts: list[dict]) -> tuple[dict, list[str]]:
    out, warns = {"google": [], "buzz": []}, []
    try:
        out["google"] = google()
    except Exception as ex:
        warns.append(f"구글 트렌드: {type(ex).__name__} {str(ex)[:100]}")
    out["buzz"] = buzz(posts)
    return out, warns


if __name__ == "__main__":
    import json
    sys.stdout.reconfigure(encoding="utf-8")
    posts, _ = scrape.collect()
    t, w = collect(posts)
    print(json.dumps(t, ensure_ascii=False, indent=1)[:4000], w)
