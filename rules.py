"""Script format shared by every writer (the cloud routine, editor.py) and the
renderer: allowed values, the JSON schema, and the checks a script must pass.

    python rules.py scripts/2026-10-02-morning.json   # prints problems, exit 1 if any

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
    if not 6 <= len(segs) <= 10:
        p.append(f"{len(segs)} segments (want 7-9)")
    total = sum(len(s.get("say") or s.get("text", "")) for s in segs)
    if not 220 <= total <= 420:
        p.append(f"narration {total} chars (want 260-360)")
    for i, s in enumerate(segs):
        for k in ("text", "say", "sfx", "card"):
            if k not in s:
                p.append(f"segment {i}: missing {k}")
        if any(k not in s for k in ("text", "say", "sfx", "card")):
            continue
        if s["sfx"] not in SFX:
            p.append(f"segment {i}: sfx {s['sfx']!r} not in {SFX}")
        if not s["text"].strip() or not s["say"].strip():
            p.append(f"segment {i}: empty text/say")
        if len(s["say"].split()) < max(1, len(s["text"].split()) // 2):
            p.append(f"segment {i}: say/text word counts diverge (same content, same order)")
        if re.search(r"[0-9A-Za-z]", s["say"]) and not re.search(r"[0-9A-Za-z]", s["text"]):
            p.append(f"segment {i}: say has digits/latin that text lacks")
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    problems = validate(json.loads(open(sys.argv[1], encoding="utf-8").read()))
    for x in problems:
        print("PROBLEM:", x)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
