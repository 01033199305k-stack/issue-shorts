"""Script format shared by every writer (the cloud routine, editor.py) and the
renderer: allowed values, the JSON schema, and the checks a script must pass.

    python rules.py scripts/2026-10-04-1900.json   # prints problems, exit 1 if any

No third-party imports, so the cloud routine can run it as-is.
"""
import json
import re
import sys

SFX = ["none", "whoosh", "dudung", "punch", "exclaim", "stamp", "question", "absurd"]
KINDS = ["scene", "number", "quote", "stamp", "list"]
THEMES = ["night", "alert", "money", "cold", "warm"]
CARD_FIELDS = ["kind", "theme", "emoji", "label", "sub", "value", "lines", "who", "word", "head", "items"]
NEEDS = {"scene": ["emoji"], "number": ["value"], "quote": ["lines"], "stamp": ["word"], "list": ["head", "items"]}

# v2 visual (motion.py): いらすとや scenes built up item by item
V_TYPES = ["illust", "text", "emoji", "crowd"]
V_STYLES = ["big", "label", "small", "red", "stamp", "bubble", "row", "post"]
V_POS = ["center", "left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"]
V_FX = ["pop", "drop", "slide-left", "slide-right", "zoom", "fade", "shake", "stamp", "run-left", "run-right"]
V_BG = ["white", "sky", "beach", "room", "city", "paper", "night", "red"]
V_SIZE = ["s", "m", "l", "xl"]


def _check_visual(i: int, v: dict) -> list[str]:
    p = []
    if v.get("bg", "white") not in V_BG:
        p.append(f"segment {i}: bg {v.get('bg')!r} not in {V_BG}")
    vq = v.get("video")
    vqs = [vq] if isinstance(vq, str) else vq
    if vq is not None and not (isinstance(vqs, list) and 1 <= len(vqs) <= 3 and all(
            isinstance(q, str) and re.fullmatch(r"[A-Za-z0-9 ,'-]{2,40}", q) for q in vqs)):
        p.append(f"segment {i}: video must be 2-40 chars of English search words (or a list of 1-3 such candidates), got {vq!r}")
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
    if not 6 <= len(segs) <= 12:   # hard limit; the 6-8 house target is in lint() so older scripts still render
        p.append(f"{len(segs)} segments (want 6-8: one picture per sentence)")
    total = sum(len(s.get("say") or s.get("text", "")) for s in segs)
    if not 130 <= total <= 290:
        p.append(f"narration {total} chars (want 140-190, about 18-25 s - cut sentences that repeat or explain too much)")
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
        tone = s.get("tone")
        if tone is not None and not (isinstance(tone, str) and len(tone.strip()) <= 40):
            p.append(f"segment {i}: tone must be a short delivery note for the voice (max 40 chars)")
        if "visual" in s:
            p += _check_visual(i, s["visual"])
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
        for k, v in (s.get("card") or {}).items():
            if isinstance(v, str):
                yield f"segment {i} card.{k}", v
    yt = script.get("youtube", {})
    yield "youtube.title", yt.get("title", "")
    yield "youtube.description", yt.get("description", "")
    yield "youtube.tags", " ".join(yt.get("tags", []))


NEWSY = re.compile(r"논란|발언|입장|제동|의혹|촉구|비판|공방|파문|일파만파")
POLITICS = re.compile(r"대통령|국회|의원|장관|여당|야당|민주당|국민의힘|대법원장|헌재소장|총리|선거|탄핵|대선|총선|국감|국정감사")


def lint(script: dict) -> list[str]:
    """House style the routine must satisfy (run.py only warns - a script that is already
    written still renders): no hanja anywhere a viewer reads, and a varied set of pictures."""
    if script.get("skip"):
        return []
    p = []
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
        if its and not is_list and not is_post and not any(it.get("type") in ("illust", "crowd", "emoji") for it in its):
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
    if len(segs) > 9 or total > 200:   # 2026-10-06: 18-25 s like @dolongcha (its 2.2M-view short ran 17 s)
        p.append(f"{len(segs)} sentences / {total} chars - write 6-8 sentences, 140-190 chars (18-25 s)")
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
