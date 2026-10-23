"""Script format shared by every writer (the cloud routine, editor.py) and the
renderer: allowed values, the JSON schema, and the checks a script must pass.

    python rules.py scripts/2026-10-04-1900.json   # prints problems, exit 1 if any

No third-party imports, so the cloud routine can run it as-is.
"""
import json
import re
from pathlib import Path
import sys

SFX = ["none", "whoosh", "dudung", "punch", "exclaim", "stamp", "question", "absurd"]
KINDS = ["scene", "number", "quote", "stamp", "list"]
THEMES = ["night", "alert", "money", "cold", "warm"]
CARD_FIELDS = ["kind", "theme", "emoji", "label", "sub", "value", "lines", "who", "word", "head", "items"]
NEEDS = {"scene": ["emoji"], "number": ["value"], "quote": ["lines"], "stamp": ["word"], "list": ["head", "items"]}

# v2 visual (motion.py): いらすとや scenes built up item by item
V_TYPES = ["illust", "text", "emoji", "crowd", "doc", "sms", "price", "warn"]
# 2026-10-12 @통찰맨 look: story props drawn by the renderer (motion._prop) and place photos behind the people
PROPS = ["doc", "sms", "price", "warn"]
PLACES = sorted(x.stem for x in (Path(__file__).resolve().parent / "assets" / "places").glob("*.jpg"))
# photos that look Korean (Seoul crosswalk, apartment blocks, a covered market) - wrong behind a story abroad
KOREAN_PLACES = ["street", "apartment", "market"]
ABROAD = re.compile(r"미국|일본|중국|영국|호주|캐나다|독일|프랑스|이탈리아|스페인|러시아|인도|태국|베트남|대만|필리핀|브라질|멕시코|뉴질랜드")
# いらすとや draws these as Japan-specific pictures - fine for a story set in Japan,
# wrong for a Korean story (2026-10-12: a Seoul->Jeonju story showed a map of Japan)
JP_ONLY_WORDS = ["日本", "地図", "日の丸", "国旗", "都道府県", "東京", "富士山", "神社", "鳥居", "着物", "和服", "新幹線", "円"]
V_STYLES = ["big", "label", "small", "red", "stamp", "bubble", "row", "post"]
V_POS = ["center", "left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"]
V_FX = ["pop", "drop", "slide-left", "slide-right", "zoom", "fade", "shake", "stamp", "run-left", "run-right", "sparkle"]
# 2026-10-08 @dolongcha-style editing: caption colour per sentence, camera moves and cut transitions
CAPS = ["narr", "hit", "quote", "shout", "sweet", "react"]
V_CAM = ["punch", "push", "pull"]
V_TR = ["whoosh", "flash"]
V_BG = ["white", "sky", "beach", "room", "city", "paper", "night", "red"] + [x for x in PLACES if x != "beach"]
V_SIZE = ["s", "m", "l", "xl"]


def _check_visual(i: int, v: dict) -> list[str]:
    p = []
    if v.get("bg", "white") not in V_BG:
        p.append(f"segment {i}: bg {v.get('bg')!r} not in {V_BG}")
    if v.get("cam") is not None and v.get("cam") not in V_CAM:
        p.append(f"segment {i}: cam {v.get('cam')!r} not in {V_CAM}")
    if v.get("tr") is not None and v.get("tr") not in V_TR:
        p.append(f"segment {i}: tr {v.get('tr')!r} not in {V_TR}")
    vq = v.get("video")
    vqs = [vq] if isinstance(vq, str) else vq
    if vq is not None and not (isinstance(vqs, list) and 1 <= len(vqs) <= 3 and all(
            isinstance(q, str) and re.fullmatch(r"[A-Za-z0-9 ,'-]{2,40}", q) for q in vqs)):
        p.append(f"segment {i}: video must be 2-40 chars of English search words (or a list of 1-3 such candidates), got {vq!r}")
    ph = v.get("photo")
    if ph is not None and not (isinstance(ph, dict) and isinstance(ph.get("who"), str) and 2 <= len(ph["who"]) <= 20
                               and (ph.get("src") is None or re.match(r"https?://", str(ph["src"])))):
        p.append(f"segment {i}: photo must be {{\"who\": \"<agency, e.g. 강원소방본부>\", \"src\": \"<article URL, optional>\"}}")
    items = v.get("items") or []
    if not 1 <= len(items) <= 6:
        p.append(f"segment {i}: visual needs 1-6 items (has {len(items)})")
    for j, it in enumerate(items):
        tag = f"segment {i} item {j}"
        typ = it.get("type")
        if typ not in V_TYPES:
            p.append(f"{tag}: type {typ!r} not in {V_TYPES}")
            continue
        q = it.get("q", "")
        if typ in ("illust", "crowd") and not (any(str(x).strip() for x in q) if isinstance(q, list) else str(q).strip()):
            p.append(f"{tag}: {typ} needs q (いらすとや search words in Japanese, or a list of alternatives)")
        qs = q if isinstance(q, list) else [q]
        bad = [w for w in JP_ONLY_WORDS for x in qs if w in str(x)]
        if typ in ("illust", "crowd") and bad:
            p.append(f"{tag}: q has {sorted(set(bad))} - いらすとや draws these as Japan; this story is not set in Japan, so show the place with text/emoji instead")
        if typ in PROPS:
            p += _check_prop(tag, it)
            continue
        if typ in ("text", "emoji") and not str(it.get("text", "")).strip():
            p.append(f"{tag}: {typ} needs text")
        if typ == "text" and it.get("style", "label") not in V_STYLES:
            p.append(f"{tag}: style {it.get('style')!r} not in {V_STYLES}")
        if typ == "text" and it.get("style") == "post":
            if i != 0:
                p.append(f"{tag}: post card only opens the video (segment 0)")
            if len(str(it.get("text", ""))) > 24 or str(it.get("text", "")).count("\n") > 1:
                p.append(f"{tag}: post title max 24 chars in at most 2 lines: {it.get('text')!r}")
        elif typ == "text" and len(str(it.get("text", ""))) > 16:
            p.append(f"{tag}: text too long for the panel (max 16): {it.get('text')!r}")
        if it.get("pos", "center") not in V_POS:
            p.append(f"{tag}: pos {it.get('pos')!r} not in {V_POS}")
        if it.get("fx", "pop") not in V_FX:
            p.append(f"{tag}: fx {it.get('fx')!r} not in {V_FX}")
        if it.get("size", "m") not in V_SIZE:
            p.append(f"{tag}: size {it.get('size')!r} not in {V_SIZE}")
        try:
            if not 0 <= float(it.get("at", 0)) <= 0.9:
                p.append(f"{tag}: at must be 0-0.9 (fraction of the sentence)")
        except (TypeError, ValueError):
            p.append(f"{tag}: at must be a number")
    return p

def _check_prop(tag: str, it: dict) -> list[str]:
    """Words on a prop are read off the screen: few and short, like the reference's 계약서 / 문자."""
    p, typ = [], it.get("type")
    lines = it.get("lines") or []
    if typ == "doc":
        if not 1 <= len(str(it.get("title", ""))) <= 8:
            p.append(f"{tag}: doc needs a title of 1-8 chars (계약서, 청구서, 영수증, 판결문): {it.get('title')!r}")
        if not (isinstance(lines, list) and 1 <= len(lines) <= 4 and all(1 <= len(str(x)) <= 14 for x in lines)):
            p.append(f"{tag}: doc needs 1-4 lines of max 14 chars: {lines!r}")
        if it.get("mark") is not None and not (isinstance(it["mark"], int) and 0 <= it["mark"] < len(lines)):
            p.append(f"{tag}: mark must be the index of one of its lines")
    elif typ == "sms":
        if not 1 <= len(str(it.get("from", ""))) <= 10:
            p.append(f"{tag}: sms needs from (sender, max 10 chars)")
        if not (isinstance(lines, list) and 1 <= len(lines) <= 3 and all(1 <= len(str(x)) <= 12 for x in lines)):
            p.append(f"{tag}: sms needs 1-3 bubbles of max 12 chars: {lines!r}")
    elif typ == "price":
        if not 1 <= len(str(it.get("new", ""))) <= 8 or len(str(it.get("label", ""))) > 10 or len(str(it.get("old", ""))) > 10:
            p.append(f"{tag}: price needs new (max 8 chars), label/old max 10: {it!r}")
    return p


CARD_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "theme": {"type": "string", "enum": THEMES},
        "emoji": {"type": "string"}, "label": {"type": "string"}, "sub": {"type": "string"},
        "value": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}},
        "who": {"type": "string"}, "word": {"type": "string"}, "head": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
    },
    "required": CARD_FIELDS,
}

SCRIPT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "skip": {"type": "boolean"}, "skip_reason": {"type": "string"},
        "slug": {"type": "string"},
        "title_lines": {"type": "array", "items": {"type": "string"}},
        "credit": {"type": "string"},
        "segments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"text": {"type": "string"}, "say": {"type": "string"},
                           "sfx": {"type": "string", "enum": SFX}, "card": CARD_SCHEMA},
            "required": ["text", "say", "sfx", "card"]}},
        "youtube": {"type": "object", "additionalProperties": False,
                    "properties": {"title": {"type": "string"}, "description": {"type": "string"},
                                   "tags": {"type": "array", "items": {"type": "string"}}},
                    "required": ["title", "description", "tags"]},
        "source_post": {"type": "string"},
        "facts_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["skip", "skip_reason", "slug", "title_lines", "credit", "segments",
                 "youtube", "source_post", "facts_used"],
}


def validate(script: dict) -> list[str]:
    """Problems that would break the render or the format; empty = fine."""
    p = []
    for k in SCRIPT_SCHEMA["required"]:
        if k not in script:
            p.append(f"missing field: {k}")
    if p:
        return p
    if script["skip"]:
        return [] if script["skip_reason"].strip() else ["skip=true needs skip_reason"]
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,6}", script["slug"]):
        p.append(f"slug must be lowercase kebab-case ascii: {script['slug']!r}")
    in_japan = "일본" in " ".join(str(x.get("text", "")) for x in script["segments"])
    tl = script["title_lines"]
    if len(tl) != 2:
        p.append("title_lines must have exactly 2 lines")
    else:
        for i, line in enumerate(tl):
            if not 2 <= len(line) <= 13:
                p.append(f"title line {i + 1} is {len(line)} chars (max 11, hard limit 13): {line!r}")
    if len(script["credit"]) > 44:
        p.append(f"credit is {len(script['credit'])} chars (max 40)")
    segs = script["segments"]
    if not 6 <= len(segs) <= 12:   # hard limit; the 7-9 house target is in lint() so older scripts still render
        p.append(f"{len(segs)} segments (want the title + 7-9: one picture per sentence)")
    total = sum(len(s.get("say") or s.get("text", "")) for s in segs)
    if not 130 <= total <= 290:
        p.append(f"narration {total} chars (want 170-230, about 24-30 s - cut sentences that repeat or explain too much)")
    queries = {json.dumps(it.get("q"), ensure_ascii=False) for s in segs for it in (s.get("visual") or {}).get("items", [])
               if it.get("type") in ("illust", "crowd") and it.get("q")}
    n_video = sum(1 for s in segs if (s.get("visual") or {}).get("video"))
    if n_video > 6:   # hard limit (render refuses); the house limit of 2 is in lint()
        p.append(f"{n_video} scenes with stock video (max 6)")
    if len(queries) > 20:
        p.append(f"{len(queries)} different illustrations - いらすとや licence allows 20 per video")
    for i, s in enumerate(segs):
        for k in ("text", "say", "sfx"):
            if k not in s:
                p.append(f"segment {i}: missing {k}")
        if "visual" not in s and "card" not in s:
            p.append(f"segment {i}: missing visual")
        if any(k not in s for k in ("text", "say", "sfx")) or ("visual" not in s and "card" not in s):
            continue
        if s["sfx"] not in SFX:
            p.append(f"segment {i}: sfx {s['sfx']!r} not in {SFX}")
        if not s["text"].strip() or not s["say"].strip():
            p.append(f"segment {i}: empty text/say")
        if len(s["say"].split()) < max(1, len(s["text"].split()) // 2):
            p.append(f"segment {i}: say/text word counts diverge (same content, same order)")
        if re.search(r"[0-9A-Za-z]", s["say"]) and not re.search(r"[0-9A-Za-z]", s["text"]):
            p.append(f"segment {i}: say has digits/latin that text lacks")
        if len(re.sub(r"[^0-9A-Za-z가-힣]", "", s["say"])) < 6:
            p.append(f"segment {i}: say too short to check against the transcript - put a reaction (헐, 와) in front of a real sentence, not alone")
        if re.search(r"[ㄱ-ㅎㅏ-ㅣ]", s["say"]):
            p.append(f"segment {i}: say has bare jamo (ㅋㅋ, ㄹㅇ ...) the voice cannot read")
        if s.get("cap") is not None and s.get("cap") not in CAPS:
            p.append(f"segment {i}: cap {s.get('cap')!r} not in {CAPS}")
        if s.get("like") is not None and not isinstance(s.get("like"), bool):
            p.append(f"segment {i}: like must be true/false (true on the one sentence the like nudge plays over)")
        tone = s.get("tone")
        if tone is not None and not (isinstance(tone, str) and len(tone.strip()) <= 40):
            p.append(f"segment {i}: tone must be a short delivery note for the voice (max 40 chars)")
        if s.get("join") is not None and (not isinstance(s["join"], bool) or (s["join"] and not 0 < i < len(segs) - 1)):
            p.append(f"segment {i}: join must be true/false, and only on a body sentence that runs on into the next "
                     "(not the title card or the last sentence)")
        if "visual" in s:
            vp = _check_visual(i, s["visual"])
            if in_japan:
                vp = [x for x in vp if "draws these as Japan" not in x]
            p += vp
            continue
        c = s["card"]
        missing = [f for f in CARD_FIELDS if f not in c]
        if missing:
            p.append(f"segment {i}: card missing fields {missing} (use \"\" or [])")
            continue
        if c["kind"] not in KINDS or c["theme"] not in THEMES:
            p.append(f"segment {i}: bad kind/theme {c['kind']!r}/{c['theme']!r}")
            continue
        if any(not c[f] for f in NEEDS[c["kind"]]):
            p.append(f"segment {i}: {c['kind']} card needs {NEEDS[c['kind']]}")
        if c["kind"] == "number" and len(c["value"]) > 8:
            p.append(f"segment {i}: number value too long ({len(c['value'])} > 7): {c['value']!r}")
        if c["kind"] == "stamp" and len(c["word"]) > 5:
            p.append(f"segment {i}: stamp word too long: {c['word']!r}")
    yt = script["youtube"]
    if not yt.get("title") or len(yt["title"]) > 100:
        p.append("youtube.title empty or over 100 chars")
    if not script["source_post"].startswith("http"):
        p.append("source_post must be the community post URL")
    return p


HANJA = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def _shown_strings(script: dict):
    """Every string a viewer reads: title, captions, panel text, YouTube title/description/tags."""
    yield "title", " ".join(script.get("title_lines", []))
    for i, s in enumerate(script.get("segments", [])):
        yield f"segment {i} text", s.get("text", "")
        yield f"segment {i} say", s.get("say", "")
        for it in (s.get("visual") or {}).get("items", []):
            if it.get("type") in ("text", "emoji"):
                yield f"segment {i} panel text", str(it.get("text", ""))
            if it.get("type") in PROPS:
                yield f"segment {i} {it['type']}", " ".join(str(it.get(k, "")) for k in ("title", "from", "label", "old", "new")) \
                    + " " + " ".join(str(x) for x in it.get("lines") or [])
        for k, v in (s.get("card") or {}).items():
            if isinstance(v, str):
                yield f"segment {i} card.{k}", v
    yt = script.get("youtube", {})
    yield "youtube.title", yt.get("title", "")
    yield "youtube.description", yt.get("description", "")
    yield "youtube.tags", " ".join(yt.get("tags", []))


# Emergency / service numbers are read digit by digit: 112 = 일일이, 119 = 일일구, 1330 = 일삼삼공
# (2026-10-17 사용자: "112면 백십이가 아니라 일일이"). A counter after the number makes it a quantity
# ("119명" = 백십구 명), so only bare numbers count.
SERVICE_NUM = re.compile(r"(?<![\d,.])(112|119|114|120|182|117|110|1330|1345|1366|1388|1577|1588|1644|1661|1899|911|999)(?![\d,.])"
                         r"(?!\s?(명|m|미터|원|개|년|kg|킬로|살|층|대|곳|건|%|퍼센트|일|시|분|초|마리|장|배|km|cm|만|억|천|번째|호|위))")
DIGIT_KO = dict(zip("0123456789", ["공", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]))


def service_number_problems(script: dict) -> list[str]:
    p = []
    for i, s in enumerate(script.get("segments", [])):
        for m in SERVICE_NUM.finditer(s.get("text", "")):
            spoken = "".join(DIGIT_KO[c] for c in m.group(1))
            if spoken not in re.sub(r"\s", "", s.get("say", "")):
                p.append(f"segment {i}: {m.group(1)} is a service number - say it digit by digit {spoken!r} "
                         f"(not 백십이 style), e.g. say \"{spoken}에 신고함\"")
    return p


# YouTube's topic like animations: dog/cat/car checked on Shorts by the user (2026-10-17); the rest as reported for
# long videos (2025-10) and used on Shorts too (사용자 2026-10-17: "보도 기준으로 적용"). A topic that turns
# out not to change on our videos comes out of here and config like_cta.eggs.
EGG_WORDS = {"dog": r"강아지|반려견|댕댕|애견|견주|유기견|진돗개|푸들|리트리버|시바견|(?<![가-힣])개(가|를|는|한테|에게|의|랑|와) ",
             "cat": r"고양이|냥이|길냥|반려묘|유기묘",
             "food": r"음식|요리|식당|맛집|메뉴|셰프|짜장면|짬뽕|치킨|피자|햄버거|라면|김밥|떡볶이|도시락|빵|케이크|반찬|국밥|삼겹살|초밥",
             "car": r"자동차|차량|운전|주차|타이어|교통사고|블랙박스|고속도로|외제차|벤츠|BMW|테슬라|택시",
             "learning": r"공부|시험|수능|학원|논술|과학|교육|수업|숙제|대학|입시",
             "music": r"노래|가수|음악|콘서트|공연|피아노|기타|밴드|아이돌|작곡|버스킹",
             "travel": r"여행|비행기|공항|항공|관광|호텔|기내|해외",
             "comedy": r"코미디|개그|몰카|예능|웃음",
             "horror": r"공포|귀신|괴담|흉가|폐가|심령|무당",
             "soccer": r"축구|월드컵|K리그|프리미어리그|손흥민",
             "baseball": r"야구|KBO|투수|타자|홈런|메이저리그",
             "basketball": r"농구|NBA|KBL|덩크"}
EGGS_OFF = {"food"}   # 2026-10-22 사용자: 떡볶이·케이크·미역국 편에서 눌러도 포크·숟가락으로 안 변함
EGGS_ON = set(EGG_WORDS) - EGGS_OFF

NEWSY = re.compile(r"논란|발언|입장|제동|의혹|촉구|비판|공방|파문|일파만파")
POLITICS = re.compile(r"대통령|국회|의원|장관|여당|야당|민주당|국민의힘|대법원장|헌재소장|총리|선거|탄핵|대선|총선|국감|국정감사")


def lint(script: dict) -> list[str]:
    """House style the routine must satisfy (run.py only warns - a script that is already
    written still renders): no hanja anywhere a viewer reads, and a varied set of pictures."""
    if script.get("skip"):
        return []
    p = service_number_problems(script)
    for where, text in _shown_strings(script):
        if (m := HANJA.search(text)):
            p.append(f"{where}: hanja {m.group(0)!r} - write it in hangul (李 -> 이재명 대통령/이 대통령, 美 -> 미국)")
    uses = {}
    for s in script.get("segments", []):
        for it in (s.get("visual") or {}).get("items", []):
            q = it.get("q")
            if it.get("type") in ("illust", "crowd") and q:
                key = (q[0] if isinstance(q, list) else q).strip()
                uses[key] = uses.get(key, 0) + 1
    for q, n in uses.items():
        if n > 2:
            p.append(f"illustration {q!r} appears {n} times - max 2; pick a different prop/person/pose for the other scenes")
    n_scenes = sum(1 for s in script.get("segments", []) if any(
        it.get("type") in ("illust", "crowd") for it in (s.get("visual") or {}).get("items", [])))
    if len(uses) < min(5, n_scenes):
        p.append(f"only {len(uses)} different illustrations - use at least 5 (the licence allows 20), a new picture for each scene")
    for i, s in enumerate(script.get("segments", [])):
        v = s.get("visual") or {}
        its = v.get("items", [])
        if len(its) > 4:
            p.append(f"segment {i}: {len(its)} items - max 4 (one big picture + a word or two reads better than a busy slide)")
        is_list = sum(1 for it in its if it.get("style") == "row") >= 2   # ①②③ list / final vote board
        is_post = any(it.get("style") == "post" for it in its)          # opening community-post card
        if its and not is_list and not is_post and not any(it.get("type") in ["illust", "crowd", "emoji"] + PROPS for it in its):
            p.append(f"segment {i}: words only - add the picture that shows the sentence (stock video often finds nothing; the renderer makes a lone picture big)")
        if sum(1 for it in its if it.get("type") in ("illust", "crowd")) > 2:
            p.append(f"segment {i}: more than 2 pictures - one big picture (or two side by side) per scene")
    vids = [bool((s.get("visual") or {}).get("video")) for s in script.get("segments", [])]
    if sum(vids) < 2:   # 2026-10-06~07: six videos in a row went out with no footage at all
        p.append(f"only {sum(vids)} scenes with stock video - give 2-3 sentences a real clip of the place/thing they name "
                 "(ROUTINE video: a list of 2-3 English candidates per scene)")
    if sum(vids) > 3:
        p.append(f"{sum(vids)} scenes with stock video (max 3 - the illustrations are still the channel's look)")
    if vids and vids[0] and any(it.get("style") == "post" for it in (script["segments"][0].get("visual") or {}).get("items", [])):
        p.append("segment 0: the opening post card takes no stock video")
    if any(a and b for a, b in zip(vids, vids[1:])):
        p.append("two stock-video scenes in a row - put a picture scene between the clips")
    segs_ = script.get("segments", [])
    bgs = [(s.get("visual") or {}).get("bg", "white") for s in segs_]
    kinds = [it.get("type") for s in segs_ for it in (s.get("visual") or {}).get("items", [])]
    n_place = sum(1 for b, v in zip(bgs, vids) if b in PLACES and not v)
    if n_place < 3:   # 2026-10-12: @통찰맨 puts every person in a real room/street; our white panel looked empty
        p.append(f"only {n_place} scenes on a place photo - put the people in 3+ scenes where the story happens "
                 f"(bg one of {PLACES}, ROUTINE 장소 사진)")
    if sum(kinds.count(k) for k in ("doc", "sms", "price")) > 3 or kinds.count("warn") > 1:
        p.append("max 3 props (doc/sms/price) and 1 warn per video - they are the key evidence, not decoration")
    story = " ".join(s.get("text", "") for s in segs_)
    if ABROAD.search(story) and not re.search(r"한국|국내|서울", story):
        bad = sorted({b for b in bgs if b in KOREAN_PLACES})
        if bad:
            p.append(f"bg {bad} are Korean-looking photos but this story is set abroad - use office/store/road/... instead")
    titles = " ".join(script.get("title_lines", [])) + " " + (script.get("youtube") or {}).get("title", "")
    if (m := NEWSY.search(titles)):
        p.append(f"title uses news word {m.group(0)!r} - write a curiosity title (\"~하는 ○○\", \"○○가 ~한 이유\"), not a headline")
    if (m := POLITICS.search(titles)):
        p.append(f"title names politics ({m.group(0)!r}) - politicians/parties/elections are off-topic for this channel (ROUTINE 2)")
    segs = script.get("segments", [])
    for i, s in enumerate(segs):
        its = (s.get("visual") or {}).get("items", [])
        rows = sum(1 for it in its if it.get("style") == "row") >= 2
        for it in its:
            st = it.get("style", "label")
            if it.get("type") == "text" and st in ("label", "small", "bubble", "red", "big", "stamp") and not (rows and st == "label"):
                p.append(f"segment {i}: text style {st!r} repeats the caption (two subtitles on screen) - "
                         "use a picture/emoji; panel words only as the post card or the vote board")
    total = sum(len(s.get("say") or s.get("text", "")) for s in segs)
    # 2026-10-17: 18-25 s squeezed the setup out - comments "뭔소린지?", "설명으로만 들어서는 모르겠음".
    # One more setup sentence: title + 7-9 sentences, 170-230 chars (24-30 s)
    if len(segs) > 10 or total > 235:
        p.append(f"{len(segs)} sentences / {total} chars - write the title + 7-9 sentences, 170-230 chars (24-30 s)")
    if total < 165:
        p.append(f"only {total} chars - too compressed for a first-time viewer to follow; add the setup sentence "
                 "(who / what happened / why it matters) - target 170-230 chars")
    post = next((it for it in ((segs[0].get("visual") or {}).get("items", []) if segs else [])
                 if it.get("style") == "post"), None)
    if post:   # 2026-10-07: @dolongcha/@군림보 read the title aloud first; ours jumped straight into the story
        squash = lambda t: re.sub(r"[^0-9A-Za-z가-힣]", "", str(t))
        if squash(segs[0].get("text", "")) != squash(post.get("text", "")):
            p.append(f"segment 0: read the post card title aloud - text must be the card words "
                     f"{post.get('text', '')!r} (line break -> space), the hook goes to segment 1")
    # caption colours and cuts are accents: used everywhere they stop meaning anything (ROUTINE 자막 색)
    caps = [s.get("cap", "narr") for s in segs]
    for name, most in (("hit", 2), ("quote", 2), ("shout", 2), ("sweet", 2), ("react", 1)):
        if caps.count(name) > most:
            p.append(f"cap {name!r} on {caps.count(name)} sentences - max {most} per video")
    if caps and caps[0] != "narr":
        p.append("segment 0: the post-card title is read as plain narration - no cap")
    if any(c == "react" for c in caps[:-2]):
        p.append("cap 'react' is the closing reaction - only in the last two sentences")
    for i, s in enumerate(segs):   # shout/react are drawn huge: a long sentence turns into a stream of bursts
        if s.get("cap") in ("shout", "react") and len(s.get("text", "")) > 18:
            p.append(f"segment {i}: cap {s['cap']!r} wants a short line (max 18 chars, like \"너 한 번만 더 울어!\"), "
                     f"got {len(s['text'])} - split the narration off into its own sentence")
    trs = [(s.get("visual") or {}).get("tr") for s in segs]
    if trs.count("whoosh") > 3 or trs.count("flash") > 1:
        p.append(f"{trs.count('whoosh')} whoosh / {trs.count('flash')} flash cuts - max 3 whoosh and 1 flash (a reveal) per video")
    if trs and trs[0]:
        p.append("segment 0: the video opens on the post card - no transition")
    # 2026-10-17 ending (사용자: "마지막에 댓글 유도형 질문은 별로"): no question to the viewer - the video ends
    # on the payoff and loops; the like nudge (renderer) plays over the reveal teaser instead
    if segs:
        last = segs[-1]
        if re.search(r"\?\s*$|님들|여러분", last.get("text", "")):
            p.append("last sentence asks the viewer something - end on the payoff instead (the answer / one-line "
                     "reaction, cap hit/react), no question, no 님들 (ROUTINE 마지막)")
        if sum(1 for it in (last.get("visual") or {}).get("items", []) if it.get("style") == "row") >= 2:
            p.append("last scene is a vote board - the ending is the payoff picture, not a poll")
        if not any(s.get("cap") in ("hit", "react") for s in segs[-2:]):
            p.append("the payoff is not marked - give one of the last two sentences cap 'hit' (the answer) or 'react'")
    # 2026-10-17 retention curves (28 shorts, 10/7-10/15): the hook sentence right after the title loses
    # 4.1 %/s on average vs 1.6 %/s for story sentences. Worst hooks opened on a time/place setting
    # ("새벽 2시, 35주 산모가..." 6.5 %/s, "한일 결승 당일, ..." 5.3) or were an empty tease ("근데 데려간
    # 이유가 더 의외임." 5.4); the best added a concrete new picture ("전화 받은 공무원이 자기 컵라면 들고
    # 뛰쳐나감." 2.8, "카메라 달린 AI 안경이 걸렸음." 2.4).
    if len(segs) > 1:
        hook = segs[1].get("text", "")
        if re.match(r"^[^,.]{1,14}(새벽|아침|저녁|밤|낮|오후|오전|당일|날|길|중|때|\d+시|지난|최근)[^,.]{0,4},\s", hook) or                 re.match(r"^(새벽|아침|저녁|밤|지난|최근|당일)[^,.]{0,12},\s", hook):
            p.append(f"segment 1 (hook) opens on a time/place setting {hook[:20]!r} - viewers leave here fastest; "
                     "open on the strangest concrete thing that happened, put the setting later")
        if re.search(r"따로 있|더 (의외|어이없|황당|놀라)|이유가 (더|따로)|아니었음|공개됨|반전", hook):
            p.append(f"segment 1 (hook) is a tease {hook[:24]!r} - right after the title it must show something new "
                     "(who did what, the number); the tease belongs in segment 2 or later")
    # 10/7-10/15: titles with the story's number kept 61.4 % of feed viewers vs 55.1 % without
    story_digits = re.findall(r"\d+", " ".join(s.get("text", "") for s in segs[1:]))
    head = " ".join(script.get("title_lines", [])) + " " + (segs[0].get("text", "") if segs else "")
    if story_digits and not re.search(r"\d|하루|이틀|사흘|나흘|열흘|[한두세네] ?(번|명|살|장|개|달|시간|마리)", head):
        p.append("the story has a number but the title/card has none - put the most striking number in "
                 "title_lines or the card title (titles with a number kept 61% vs 55% of viewers)")
    # like easter egg (2026-10-17): the like button turns into a topic icon when that thing is ON SCREEN as it
    # is pressed (사용자 test on the 10/10 dog short). The renderer draws the thing big under the last line; the
    # thing must come from the story (사용자: "보도에 있는 것 중에 하나 골라서"), so the line is never a bluff.
    egg = script.get("like_egg")
    if egg is not None:
        topic = egg.get("topic") if isinstance(egg, dict) else egg
        if topic not in EGGS_ON:
            p.append(f"like_egg {egg!r} - only {sorted(EGGS_ON)} are reported to change the button; leave it out otherwise")
        elif not re.search(EGG_WORDS[topic], " ".join([script.get("youtube", {}).get("title", "")] + [s.get("text", "") for s in segs])):
            p.append(f"like_egg {topic!r} but the story never names it ({EGG_WORDS[topic]}) - pick a thing that is in "
                     "the story, or drop like_egg")
    brief = str(script.get("brief", ""))
    if "이해검사:" not in brief:
        p.append("brief has no '이해검사:' line - write who / what / how it ended in one sentence using only the script's words")
    if not any(k in kinds for k in ("doc", "sms", "price")) and "증거없음:" not in brief:
        p.append("no evidence prop - show the story's real paper/text/price (doc/sms/price from the reports) in one scene, "
                 "or write '증거없음: <why>' in brief (viewer comment, 레이디 가가 편: \"사실이면 영상이라도 올리던가\")")
    sfx = [s.get("sfx") for s in segs]
    if len(sfx) > 1 and sfx[0] == "dudung" and sfx[1] == "question":
        p.append("opening sfx dudung -> question is the pattern every video used - open by the hook's mood (see ROUTINE sfx)")
    return p


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    script = json.loads(open(sys.argv[1], encoding="utf-8").read())
    problems = validate(script) + lint(script)
    for x in problems:
        print("PROBLEM:", x)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
