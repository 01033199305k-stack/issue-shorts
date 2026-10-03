"""긴급 소재 감지: gather.py 가 inbox/latest.json 을 쓴 뒤 부른다.

지금 막 터진 화제(은행 해킹 같은 [속보], 여러 커뮤니티에 동시에 뜬 글)가 새로 보이면
inbox/urgent.json 을 새로 쓴다. gather.yml 이 그 변경을 보고 긴급 대본 루틴(ROUTINE_URGENT.md)을 깨운다.
여기서는 넓게 거르고, 다룰지 말지 최종 판단은 루틴이 한다 (부적합하면 아무것도 올리지 않는다).

    python urgent.py            # inbox/latest.json 으로 판정만 출력 (파일 안 씀)
"""
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))
URGENT = REPO / "inbox" / "urgent.json"
SEEN = REPO / "inbox" / "urgent_seen.json"

MIN_GAP = dt.timedelta(minutes=60)   # 루틴을 깨우는 최소 간격 (구독 사용량)
MAX_PER_DAY = 6
QUIET = range(1, 7)                  # 01~06시 KST 는 깨우지 않는다 (볼 사람도, 검수할 사람도 없다)
NEWS_CLUSTER = 3                     # 같은 이야기를 '댓글 많은 기사' 1위로 올린 언론사 수

BREAKING = re.compile(r"\[\s*속보\s*\]|\[\s*긴급\s*\]")
STOP = {"속보", "단독", "종합", "종합2보", "긴급", "논란", "결국", "이유", "충격", "공식", "입장", "오늘", "지금"}


def tokens(title: str) -> set[str]:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>", " ", title)
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", t)
    # 조사 떼기 (대충: 끝 한 글자 조사)
    out = {re.sub(r"(은|는|이|가|을|를|에|의|도|만|과|와|로)$", "", w) for w in words}
    return {w for w in out if len(w) >= 2 and w not in STOP}


def similar(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    if ta and tb and len(ta & tb) / min(len(ta), len(tb)) >= 0.4 and len(ta & tb) >= 2:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.5


def covered_titles() -> list[str]:
    """이미 다뤘거나 대본이 있는 소재 제목 (영상 제목·카드 제목·사실 메모)."""
    out = []
    hist = REPO / "state" / "history.json"
    if hist.exists():
        for h in json.loads(hist.read_text(encoding="utf-8"))[-60:]:
            out += [h.get("title") or "", *(h.get("facts_used") or [])[:2]]
    for f in sorted((REPO / "scripts").glob("*.json"))[-40:]:
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out += [s.get("youtube", {}).get("title") or "", " ".join(s.get("title_lines") or [])]
    return [t for t in out if t]


def candidates(inbox: dict) -> list[dict]:
    out = []
    for p in inbox.get("posts", []):
        also, news = p.get("also_on") or [], p.get("in_news")
        if len(also) >= 2 or (also and news):
            out.append({"kind": "community", "title": p["title"], "url": p["url"], "board": p["board"],
                        "why": f"커뮤니티 {1 + len(also)}곳 동시 화제" + (f" + 기사화({news})" if news else ""),
                        "news": p.get("news", [])})
    hot = inbox.get("news_hot", [])
    for n in hot:
        same = [m for m in hot if m is not n and similar(n["title"], m["title"])]
        presses = {n["press"], *(m["press"] for m in same)}
        if BREAKING.search(n["title"]) or len(presses) >= NEWS_CLUSTER:
            why = "[속보] 기사" if BREAKING.search(n["title"]) else ""
            if len(presses) >= 2:
                why += (" + " if why else "") + f"언론사 {len(presses)}곳이 댓글 많은 기사 1위로"
            out.append({"kind": "news", "title": n["title"], "url": n["url"], "press": n["press"], "why": why,
                        "related": [{"press": m["press"], "title": m["title"], "url": m["url"]} for m in same[:4]]})
    # 같은 이야기는 하나로 (앞의 것 = 커뮤니티 동시 화제 우선)
    uniq: list[dict] = []
    for c in out:
        if not any(similar(c["title"], u["title"]) for u in uniq):
            uniq.append(c)
    return uniq


def detect(inbox: dict, now: dt.datetime, write: bool = True) -> list[dict]:
    seen = json.loads(SEEN.read_text(encoding="utf-8")) if SEEN.exists() else {"fired": [], "titles": []}
    cutoff = now - dt.timedelta(hours=48)
    seen["titles"] = [t for t in seen["titles"] if dt.datetime.fromisoformat(t["at"]) > cutoff]
    seen["fired"] = [f for f in seen["fired"] if dt.datetime.fromisoformat(f) > cutoff]
    old = [t["title"] for t in seen["titles"]] + covered_titles()
    fresh = [c for c in candidates(inbox) if not any(similar(c["title"], o) for o in old)]
    print(f"긴급 후보 {len(fresh)}개:", [c["title"][:40] for c in fresh])
    if not fresh:
        return []
    fired = sorted(dt.datetime.fromisoformat(f) for f in seen["fired"])
    today = [f for f in fired if f.astimezone(KST).date() == now.date()]
    why_not = ("조용한 시간(01~06시)" if now.hour in QUIET else
               "직전 호출 60분 안" if fired and now - fired[-1] < MIN_GAP else
               f"오늘 {MAX_PER_DAY}회 다 씀" if len(today) >= MAX_PER_DAY else "")
    if why_not:
        # 본 것으로 치지 않는다 - 다음 수집 때 아직 뜨거우면 그때 깨운다
        print("깨우지 않음:", why_not)
        return []
    if write:
        seen["fired"].append(now.isoformat(timespec="minutes"))
        seen["titles"] += [{"title": c["title"], "at": now.isoformat(timespec="minutes")} for c in fresh]
        SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
        URGENT.write_text(json.dumps({"detected_at": now.isoformat(timespec="minutes"), "candidates": fresh},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        (REPO / ".urgent_fired").touch()   # gather.yml 이 이걸 보고 루틴을 깨운다 (커밋 안 함)
    return fresh


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    inbox = json.loads((REPO / "inbox" / "latest.json").read_text(encoding="utf-8"))
    for c in detect(inbox, dt.datetime.now(KST), write=False):
        print(json.dumps(c, ensure_ascii=False))
