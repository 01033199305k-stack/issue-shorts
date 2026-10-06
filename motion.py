"""Motion renderer in the reference channel's (@군림보) style.

The frame: black, a two-line title on top (white + yellow) that never moves,
a white panel underneath where いらすとや people and props pop in one by one
as the narration reaches them, and the caption phrase in a black box at the
bottom of the panel (the word being read turns yellow).

Every element is a function of t: the page exposes render(t) and headless
Chrome captures it frame by frame (same idea as news-factory/motion.py), so a
render is reproducible and needs no GPU.

Segment visual spec (script v2):
    "visual": {"bg": "white", "items": [
        {"type": "illust", "q": "タクシー 乗車拒否", "pos": "left", "size": "l", "at": 0.0, "fx": "slide-right"},
        {"type": "text", "text": "45kg", "style": "big", "pos": "top-right", "at": 0.5, "fx": "pop"},
        {"type": "crowd", "q": "男の子", "count": 12, "pos": "center", "at": 0.2},
        {"type": "emoji", "text": "💥", "pos": "right", "size": "m", "at": 0.6, "fx": "shake"}]}
Old v1 "card" specs are converted by card_to_visual().
"""
import datetime as dt
import html as _html
import json
import os
import re
import subprocess
from pathlib import Path

W, H, FPS = 1080, 1920, 30
PANEL_TOP, PANEL_H = 470, 960   # reference proportions: one picture fills a near-square panel
LEAD = 0.18          # visuals land a hair before the voice (J-cut) - late visuals feel slow

POS = {  # centre points in panel coordinates (1080 x 960); the one-line caption owns y > ~860
    "center": (540, 440), "left": (290, 455), "right": (790, 455),
    "top": (540, 120), "bottom": (540, 700),
    "top-left": (270, 140), "top-right": (810, 140),
    "bottom-left": (270, 700), "bottom-right": (810, 700),
}
SIZE = {"s": 260, "m": 440, "l": 600, "xl": 760}
Z = {"illust": 1, "crowd": 1, "emoji": 2, "text": 3}   # words always sit on top of pictures
BG = {
    "white": "#ffffff",
    "sky": "linear-gradient(180deg,#bfe3ff 0%,#eaf6ff 100%)",
    "beach": "linear-gradient(180deg,#8fd3ff 0%,#d8f1ff 55%,#f6e3b4 56%,#f1d79c 100%)",
    "room": "linear-gradient(180deg,#fbf3e6 0%,#f3e4cc 100%)",
    "city": "linear-gradient(180deg,#dfe7f1 0%,#c9d5e4 100%)",
    "paper": "#fffdf3",
    "night": "linear-gradient(180deg,#1b2440 0%,#0b1020 100%)",
    "red": "radial-gradient(circle at 50% 45%,#ff6b6b 0%,#c81e1e 100%)",
}
SHAKE_SFX = {"punch", "stamp", "exclaim"}
CAPTION_LIKE = {"label", "small", "bubble", "red", "big", "stamp"}   # dropped: they repeat the caption


def esc(s) -> str:
    return _html.escape(str(s or "")).replace("\n", "<br>")


def file_url(p) -> str:
    return "file:///" + os.path.abspath(p).replace("\\", "/").lstrip("/")


# ─────────────────────────────────────────── v1 card -> v2 visual
def card_to_visual(c: dict) -> dict:
    k, items = c.get("kind"), []
    if k == "scene":
        glyphs = _split_emoji(c.get("emoji", ""))[:3]
        slots = {1: ["center"], 2: ["left", "right"], 3: ["left", "center", "right"]}.get(len(glyphs), ["center"])
        for n, (g, p) in enumerate(zip(glyphs, slots)):
            items.append({"type": "emoji", "text": g, "pos": p, "size": "m", "at": 0.08 * n, "fx": "pop"})
        if c.get("label"):
            items.append({"type": "text", "text": c["label"], "style": "label", "pos": "top", "at": 0.15, "fx": "pop"})
    elif k == "number":
        if c.get("label"):
            items.append({"type": "text", "text": c["label"], "style": "label", "pos": "top", "at": 0.0, "fx": "pop"})
        items.append({"type": "text", "text": c.get("value", ""), "style": "big", "pos": "center", "at": 0.1, "fx": "pop"})
    elif k == "quote":
        for n, line in enumerate((c.get("lines") or [])[:2]):
            items.append({"type": "text", "text": line, "style": "bubble",
                          "pos": "top-left" if n == 0 else "bottom-right", "at": 0.05 + 0.35 * n, "fx": "pop"})
    elif k == "stamp":
        items.append({"type": "text", "text": c.get("word", ""), "style": "stamp", "pos": "center", "at": 0.1, "fx": "stamp"})
    elif k == "list":
        items.append({"type": "text", "text": c.get("head", ""), "style": "label", "pos": "top", "at": 0.0, "fx": "pop"})
        rows = (c.get("items") or [])[:3]
        for n, row in enumerate(rows):
            items.append({"type": "text", "text": row, "style": "row", "pos": "center",
                          "dy": (n - (len(rows) - 1) / 2) * 120, "at": 0.15 + 0.25 * n, "fx": "slide-left"})
    return {"bg": "white", "items": items}


def _split_emoji(s: str) -> list[str]:
    # group ZWJ sequences / variation selectors with their base character
    out, cur = [], ""
    for ch in s:
        if cur and (ch in "\u200d\ufe0f" or cur.endswith("\u200d") or 0x1F3FB <= ord(ch) <= 0x1F3FF):
            cur += ch
        else:
            if cur.strip():
                out.append(cur)
            cur = ch
    if cur.strip():
        out.append(cur)
    return out


# ─────────────────────────────────────────── captions (phrase cues)
# Korean phrases that must stay on one caption line: a number/determiner and
# the counter after it ("두 번", "한 마리", "3m 넘는" is fine to split).
_BEFORE_COUNTER = {"한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열", "몇", "첫", "그", "이",
                   "저", "이런", "그런", "저런", "어떤", "무슨", "각", "매", "약", "총", "단", "딱", "무려", "안",
                   "못", "더", "덜", "꽤", "너무", "제일", "가장", "아주", "진짜", "또", "다", "온", "새", "옛", "헌"}
_COUNTERS = ("번", "명", "개", "마리", "살", "원", "년", "개월", "가구", "짜리", "쯤", "정도", "킬로", "미터",
             "센티", "퍼센트", "층", "권", "장", "배", "대", "곳", "건", "차례", "시간", "분", "초")
# words that lean on the word before them ("적립해 줌", "삭제돼 버림", "조사 중이고")
_LEANS_BACK = ("줌", "줘", "준", "주고", "줬", "주는", "버림", "버려", "버렸", "버린", "두고", "둠", "뒀", "놓고",
               "놓음", "놨", "중", "대로", "수 ", "뿐", "만큼", "듯", "척", "채")
_PUNCT_END = (",", ".", "?", "!", "…", "·", ")", "\"", "'", "”", "’")


def _break_cost(a: str, b: str) -> float:
    """How bad it is to break a caption between word a and word b (0 = natural)."""
    if a.endswith(_PUNCT_END):
        return 0.0
    if a in _BEFORE_COUNTER or (a[-1:].isdigit() and not b[:1].isdigit()):
        return 100.0
    if any(c.isdigit() for c in a) and any(b.startswith(k) and len(b) - len(k) <= 1 for k in _COUNTERS):
        return 100.0
    if b.startswith(_LEANS_BACK) or b.rstrip(",.?!") in ("수", "것", "거", "데", "적", "때"):
        return 60.0
    if len(a) == 1 or len(b) == 1:
        return 30.0   # a lone one-syllable word left dangling reads as a typo
    return 10.0


def _width(ws) -> int:
    return sum(len(w.text) for w in ws) + max(0, len(ws) - 1)


def _best_lines(ws, line_chars: int, max_lines: int = 2):
    """Split one cue into 1-2 lines at the most natural point; None if it cannot fit."""
    if _width(ws) <= line_chars:
        return 0.0, [ws]
    if max_lines < 2:
        return None
    best = None
    for k in range(1, len(ws)):
        a, b = ws[:k], ws[k:]
        if _width(a) > line_chars or _width(b) > line_chars:
            continue
        c = _break_cost(a[-1].text, b[0].text) * 0.6 + abs(_width(a) - _width(b)) * 0.3
        if best is None or c < best[0]:
            best = (c, [a, b])
    return best


def _phrase_cues(words, line_chars: int, max_words: int, max_lines: int = 2):
    """Split one sentence into caption cues (each 1-2 lines) at natural breaks.
    Dynamic programming over cue boundaries: break costs + a small per-cue cost."""
    n = len(words)
    INF = float("inf")
    dp = [(INF, None, None)] * (n + 1)
    dp[0] = (0.0, None, None)
    for j in range(1, n + 1):
        for i in range(max(0, j - max_words), j):
            if dp[i][0] == INF:
                continue
            fit = _best_lines(words[i:j], line_chars, max_lines)
            if fit is None:
                if j - i == 1:          # a single word longer than the line - show it anyway
                    fit = (50.0, [words[i:j]])
                else:
                    continue
            edge = _break_cost(words[i - 1].text, words[i].text) if i else 0.0
            short = 25.0 if (j - i < n and _width(words[i:j]) <= 5) else 0.0   # no lone "자," / "근데" cue
            c = dp[i][0] + edge + fit[0] + short + 8.0
            if c < dp[j][0]:
                dp[j] = (c, i, fit[1])
    out, j = [], n
    while j > 0:
        _, i, lines = dp[j]
        out.append(lines)
        j = i
    return out[::-1]


def caption_cues(words, line_chars: int = 11, max_words: int = 6, max_lines: int = 2) -> list[dict]:
    """[{s, e, lines:[[(text, start, end), ...], ...]}] - at most 2 lines per cue,
    broken at punctuation and never between a number/determiner and its counter."""
    cues = []
    for seg in words:
        for lines in _phrase_cues(seg, line_chars, max_words, max_lines):
            cues.append({"s": lines[0][0].start, "e": lines[-1][-1].end,
                         "lines": [[(w.text, round(w.start, 3), round(w.end, 3)) for w in ln] for ln in lines]})
    # hold each phrase until the next one starts (no flicker between words)
    for a, b in zip(cues, cues[1:]):
        a["e"] = max(a["e"], b["s"])
    return cues


# ─────────────────────────────────────────── HTML
CSS = """
@font-face { font-family: BH; src: url('FONT'); }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1080px; height:1920px; background:#000; overflow:hidden; }
body { font-family: BH, 'Malgun Gothic', 'Noto Sans CJK KR', sans-serif; color:#fff; }
#title { position:absolute; top:150px; left:30px; right:30px; height:310px; display:flex;
  flex-direction:column; justify-content:center; align-items:center; text-align:center;
  line-height:1.18; letter-spacing:-1px; }
#title div { white-space:nowrap; }
#title .t2 { color:#FFE14D; }
#panel { position:absolute; top:470px; left:0; width:1080px; height:960px; overflow:hidden; background:#fff; }
#cam { position:absolute; inset:0; transform-origin:540px 430px; }
.sc { position:absolute; inset:0; visibility:hidden; }
.it { position:absolute; left:0; top:0; will-change:transform,opacity; }
.it img { width:100%; height:100%; object-fit:contain; display:block; }
.emo { font-family:'Segoe UI Emoji','Noto Color Emoji','Apple Color Emoji',sans-serif; line-height:1;
  display:flex; align-items:center; justify-content:center; }
.tx { white-space:nowrap; text-align:center; line-height:1.1; }
.tx.big { color:#111; background:#FFE14D; padding:10px 34px 4px; border-radius:18px; font-size:150px;
  box-shadow:0 10px 0 rgba(0,0,0,.18); }
.tx.label { color:#111; font-size:84px; -webkit-text-stroke:0; text-shadow:
  -5px -5px 0 #fff, 5px -5px 0 #fff, -5px 5px 0 #fff, 5px 5px 0 #fff, 0 6px 0 #fff, 0 -6px 0 #fff, 6px 0 0 #fff, -6px 0 0 #fff; }
.tx.small { color:#222; font-size:52px; text-shadow:   /* white rim: small words often land on a picture */
  -4px -4px 0 #fff, 4px -4px 0 #fff, -4px 4px 0 #fff, 4px 4px 0 #fff, 0 5px 0 #fff, 0 -5px 0 #fff, 5px 0 0 #fff, -5px 0 0 #fff; }
.tx.red { color:#e01e1e; font-size:120px; text-shadow:0 6px 0 rgba(0,0,0,.15); }
.tx.stamp { color:#e01e1e; border:14px solid #e01e1e; border-radius:24px; padding:8px 40px 0; font-size:150px; }
.tx.bubble { color:#111; background:#fff; border:7px solid #111; border-radius:46px; padding:20px 40px 12px;
  font-size:72px; box-shadow:0 8px 0 rgba(0,0,0,.15); }
.tx.row { color:#111; background:#fff; border:6px solid #111; border-radius:20px; padding:16px 32px 8px;
  font-size:64px; text-align:left; }
/* opening 'community post' card (@dolongcha style): board line, post title, writer line */
.tx.post { color:#111; background:#fff; text-align:left; white-space:normal; padding:0 40px;
  font-family:'Noto Sans CJK KR','Malgun Gothic',sans-serif; font-weight:500; flex-direction:column;
  align-items:flex-start !important; justify-content:center; }
.post .board { color:#19b35b; font-size:40px; font-weight:700; margin-bottom:38px; }
.post .ttl { line-height:1.3; letter-spacing:-1px; white-space:pre-line; }
.post .meta { display:flex; align-items:center; gap:18px; margin-top:44px; color:#999; font-size:34px; }
.post .meta b { color:#333; font-weight:700; }
.post .ava { width:70px; height:70px; border-radius:50%; background:#e6e6e6; }
#credit { display:none; position:absolute; top:14px; left:20px; right:20px; font-family:'Malgun Gothic','Noto Sans CJK KR',sans-serif;
  font-weight:700; font-size:24px; color:rgba(0,0,0,.42); white-space:nowrap; overflow:hidden; z-index:5; }
#credit.dark { color:rgba(255,255,255,.55); }
/* stock footage behind a scene's items, swapped frame by frame; '자료화면' so it never passes as the real event */
.bgv { position:absolute; left:0; top:0; width:1080px; height:960px; object-fit:cover; z-index:0; }
.tag { position:absolute; right:18px; top:16px; z-index:4; font-family:'Noto Sans CJK KR','Malgun Gothic',sans-serif;
  font-weight:700; font-size:30px; color:#fff; background:rgba(0,0,0,.5); padding:4px 14px; border-radius:8px; }
/* one-line caption laid over the bottom of the panel, like the reference: the picture keeps the panel */
#cap { position:absolute; left:0; right:0; top:1430px; height:0; z-index:9; }
#cap .box { position:absolute; left:50%; bottom:30px; transform:translateX(-50%); background:rgba(0,0,0,.82);
  padding:8px 24px 2px; border-radius:6px; text-align:center; font-size:62px; line-height:1.22; white-space:nowrap; }
#cap span { color:#fff; }
#cap span.on { color:#FFE14D; }
"""

JS = r"""
const C = x => x < 0 ? 0 : x > 1 ? 1 : x;
const eo = x => 1 - Math.pow(1 - C(x), 3);
const eb = x => { x = C(x); const a = 1.7, b = a + 1; return 1 + b * Math.pow(x - 1, 3) + a * Math.pow(x - 1, 2); };
const bounce = x => { x = C(x); const n = 7.5625, d = 2.75;
  if (x < 1/d) return n*x*x; if (x < 2/d) return n*(x-=1.5/d)*x+.75; if (x < 2.5/d) return n*(x-=2.25/d)*x+.9375; return n*(x-=2.625/d)*x+.984375; };
const D = window.DATA;
const scenes = [...document.querySelectorAll('.sc')];
const cam = document.getElementById('cam');
const panel = document.getElementById('panel');
const credit = document.getElementById('credit');
const capEl = document.getElementById('cap');
let lastCue = -2;

function fmtNum(v, dec) { const s = v.toFixed(dec); const [a, b] = s.split('.');
  return a.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (b ? '.' + b : ''); }

function item(el, d, t, s) {
  // items that open the scene start 0.14 s before the cut, so the cut lands on them mid-pop
  const t0 = s.start + d.at * (s.end - s.start) - D.lead - (d.at < 0.05 ? 0.14 : 0);
  const p = (t - t0) / 0.42, life = t - t0;
  let x = d.x, y = d.y, sc = 1, rot = d.rot || 0, op = 1;
  if (p <= 0) { el.style.opacity = 0; return; }
  switch (d.fx) {
    case 'pop': sc = .35 + .65 * eb(p); op = C(p * 3); break;
    case 'drop': y = d.y - 420 * (1 - bounce(p * .8)); op = C(p * 4); break;
    case 'slide-left': x = d.x + 700 * (1 - eo(p)); op = C(p * 3); break;
    case 'slide-right': x = d.x - 700 * (1 - eo(p)); op = C(p * 3); break;
    case 'zoom': sc = .15 + .85 * eo(p); op = C(p * 2); break;
    case 'fade': op = eo(p); break;
    case 'shake': sc = .35 + .65 * eb(p); op = C(p * 3); x += Math.sin(life * 55) * 18 * Math.max(0, 1 - life / .5); break;
    case 'stamp': sc = 2.6 - 1.6 * eo(p * 1.4); op = C(p * 4); rot = -9; break;
    case 'run-left': x = d.x + 260 - 520 * C(life / Math.max(.8, s.end - t0)); op = C(p * 3); y += Math.abs(Math.sin(life * 9)) * -14; break;
    case 'run-right': x = d.x - 260 + 520 * C(life / Math.max(.8, s.end - t0)); op = C(p * 3); y += Math.abs(Math.sin(life * 9)) * -14; break;
    default: sc = .35 + .65 * eb(p); op = C(p * 3);
  }
  // idle life: illustrations breathe so nothing on screen is ever frozen
  if (d.type === 'illust' || d.type === 'emoji') { y += Math.sin(life * 2.4 + d.seed) * 6; sc *= 1 + Math.sin(life * 1.7 + d.seed) * .012; }
  el.style.opacity = op;
  el.style.transform = `translate(${x - d.w / 2}px, ${y - d.h / 2}px) scale(${sc}) rotate(${rot}deg)`;
  if (d.num) {   // count-up
    const k = eo((t - t0) / .7);
    el.textContent = d.num.pre + fmtNum(d.num.v * k, d.num.dec) + d.num.post;
  }
  if (d.type === 'crowd') {
    const kids = el.children, n = kids.length;
    for (let i = 0; i < n; i++) { const q = (life - i * .05) / .25; kids[i].style.opacity = C(q * 2);
      kids[i].style.transform = `scale(${.3 + .7 * eb(q)})`; }
  }
}

window.render = function (t) {
  let shake = 0;
  const waits = [];
  scenes.forEach((el, i) => {
    const s = D.scenes[i];
    const on = t >= s.start - D.lead && (i === scenes.length - 1 || t < D.scenes[i + 1].start - D.lead);
    el.style.visibility = on ? 'visible' : 'hidden';
    if (!on) return;
    const pin = (t - (s.start - D.lead)) / .16;
    el.style.transform = `scale(${1.05 - .05 * eo(pin) + .03 * C((t - s.start) / Math.max(1, s.end - s.start))})`;
    el.style.transformOrigin = '540px 430px';
    panel.style.background = s.bg;
    credit.className = s.dark ? 'dark' : '';
    if (s.clip) {   // stock clip: next frame (loops if the sentence outlasts the clip)
      const k = Math.floor(Math.max(0, t - (s.start - D.lead)) * D.fps) % s.clip.n + 1;
      const img = el.querySelector('.bgv');
      if (img.dataset.k != k) { img.dataset.k = k; img.src = s.clip.base + String(k).padStart(4, '0') + '.jpg';
        waits.push(img.decode().catch(() => {})); }
    }
    s.items.forEach((d, j) => item(el.children[j], d, t, s));
    if (s.shake) { const k = t - s.start + D.lead; if (k >= 0 && k < .38) shake = (1 - k / .38); }
    s.items.forEach(d => { if (d.fx === 'stamp') { const k = t - (s.start + d.at * (s.end - s.start) - D.lead) - .2;
      if (k >= 0 && k < .3) shake = Math.max(shake, 1 - k / .3); } });
  });
  cam.style.transform = shake ? `translate(${Math.sin(t * 90) * 16 * shake}px, ${Math.cos(t * 75) * 12 * shake}px)` : '';
  // captions
  let k = -1;
  for (let i = 0; i < D.caps.length; i++) if (t >= D.caps[i].s - .05 && t < D.caps[i].e) { k = i; break; }
  if (k !== lastCue) {
    capEl.innerHTML = k < 0 ? '' : '<div class="box">' + D.caps[k].lines.map(
      ln => ln.map(w => `<span>${w[0]}</span>`).join(' ')).join('<br>') + '</div>';
    lastCue = k;
  }
  if (k >= 0) {
    const box = capEl.firstChild, p = (t - D.caps[k].s + .05) / .14;
    box.style.transform = `translateX(-50%) scale(${.92 + .08 * eo(p)})`;
    const spans = box.querySelectorAll('span'); let n = 0;
    D.caps[k].lines.forEach(ln => ln.forEach(w => { spans[n].className = t >= w[1] - .03 ? 'on' : ''; n++; }));
  }
  return Promise.all(waits);   // capture waits until the clip frame is decoded
};
window.READY = true;
"""


def _num(text: str):
    m = re.match(r"^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$", text or "")
    if not m:
        return None
    v = float(m.group(2).replace(",", ""))
    if v == 0:
        return None
    dec = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
    return {"pre": m.group(1), "v": v, "dec": dec, "post": m.group(3)}


def _fit(path, side: int) -> tuple[int, int]:
    """Box for an illustration: the long edge is `side`, but a wide image may
    grow to 1.6x side in width so it is not shrunk to a sliver."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            bbox = im.getbbox() if im.mode in ("RGBA", "LA") else None
            w, h = (bbox[2] - bbox[0], bbox[3] - bbox[1]) if bbox else im.size
    except Exception:
        return side, side
    ar = w / max(1, h)
    if ar >= 1:
        bw = int(min(side * 1.6, side * ar))
        return bw, int(bw / ar)
    return int(side * ar), side


CAP_BOX_LINE, CAP_BOX_PAD, CAP_BOTTOM = 62 * 1.22, 10, 30   # mirrors #cap .box in CSS
ZOOM_ROOM = 30      # the camera zooms up to 1.08x around y=430 - the bottom edge drifts ~25 px


def _item_floor(cues, st, en) -> float:
    """Lowest panel y an item may reach in this scene: above the tallest caption box
    shown while the scene is on screen (a one-line box starts near y=845), minus zoom drift."""
    lines = max((len(c["lines"]) for c in cues if c["s"] < en and c["e"] > st - LEAD), default=2)
    box_top = PANEL_H - CAP_BOTTOM - (CAP_BOX_LINE * max(1, lines) + CAP_BOX_PAD)
    return box_top - ZOOM_ROOM


def _unstack(data, floor) -> None:
    """Two word boxes must not cover each other (bubble ping-pong: top-left + top-right bubbles
    wider than half the panel). A later box that overlaps an earlier one drops just below it,
    or sits just above it when there is no room below. Stamps are meant to land on top - skipped."""
    placed = []
    for d in data:
        if d["type"] != "text" or d["fx"] == "stamp":
            continue
        for _ in range(len(placed)):
            hit = next((o for o in placed if abs(d["x"] - o["x"]) < (d["w"] + o["w"]) / 2 - 4
                        and abs(d["y"] - o["y"]) < (d["h"] + o["h"]) / 2 - 4), None)
            if not hit:
                break
            below = hit["y"] + hit["h"] / 2 + 12 + d["h"] / 2
            above = hit["y"] - hit["h"] / 2 - 12 - d["h"] / 2
            if below <= floor - d["h"] / 2:
                d["y"] = below
            elif above >= d["h"] / 2 + 24:
                d["y"] = above
            else:
                break
        placed.append(d)


def _separate(parts, data, pics, floor) -> None:
    """A picture must not sit under the words above it: when text items overlap it by
    more than ~12% of their height, move the picture below all of them (shrinking an
    illustration to the free band above the caption box). Stamps are skipped - they are
    meant to land on top of the thing - and a band under ~200 px is not worth squeezing into."""
    import re as _re
    for j, pd in enumerate(data):
        if pd["type"] == "text":
            continue
        p_top, p_bot = pd["y"] - pd["h"] / 2, pd["y"] + pd["h"] / 2
        lo = 0.0
        for td in data:
            if td["type"] != "text" or td["fx"] == "stamp" or td["y"] > pd["y"]:
                continue
            if abs(pd["x"] - td["x"]) >= (pd["w"] + td["w"]) / 2:      # side by side
                continue
            t_top, t_bot = td["y"] - td["h"] / 2, td["y"] + td["h"] / 2
            if min(t_bot, p_bot) - max(t_top, p_top) > 0.12 * td["h"]:
                lo = max(lo, t_bot + 6)
        if not lo or floor - lo < 200:
            continue
        band = floor - lo
        w, h = pd["w"], pd["h"]
        if h > band:
            if j not in pics:
                continue
            w, h = _fit(pics[j][0], int(pics[j][1] * band / h))
            parts[j] = _re.sub(r"width:\d+px;height:\d+px", f"width:{w}px;height:{h}px", parts[j], count=1)
            pd["w"], pd["h"] = w, h
        pd["y"] = max(pd["y"], lo + h / 2)


def title_size(lines) -> int:
    longest = max(len(l) for l in lines)
    return max(64, min(130, int(1000 / (0.76 * max(1, longest)))))


def _hero(items: list, has_clip: bool, picker=None) -> list:
    """Reference look: one big picture owns the panel. A scene's lone illustration grows to
    l/xl and moves to the centre; a picture-less scene blows its first emoji up instead of
    leaving a small icon in an empty white box. Two pictures go side by side at m or larger.
    Pictures いらすとや has no match for are dropped first, so the layout is planned on what shows."""
    if picker:
        items = [it for it in items if it.get("type") not in ("illust", "crowd") or picker.fetch(it.get("q", ""))]
    items = [dict(it) for it in items[:4]]
    # one line of words on screen, like the reference: the caption already says the sentence, so a
    # panel label/bubble/number/stamp line reads as a second subtitle. Kept: the post card and the
    # vote board (rows + its heading).
    has_rows = sum(1 for it in items if it.get("style") == "row") >= 2
    items = [it for it in items if not (it.get("type", "text") == "text" and it.get("style", "label") in CAPTION_LIKE
                                        and not (has_rows and it.get("style", "label") == "label"))]
    post = next((it for it in items if it.get("style") == "post"), None)
    if post:   # the post card is the whole scene: centred, nothing else competes with it
        post["pos"], post["dx"], post["dy"] = "center", 0, 0
        return [post] + [it for it in items if it.get("type") == "emoji"][:1]
    extra = [it for it in items if it.get("type") in ("illust", "crowd")][2:]
    items = [it for it in items if not any(it is x for x in extra)]   # 3 pictures = thumbnails; keep two
    pics = [it for it in items if it.get("type") in ("illust", "crowd")]
    others = [it for it in items if it not in pics]
    rows = [it for it in items if it.get("type") == "text" and it.get("style") == "row"]
    if len(rows) > 1:   # list rows: even spacing for the bigger row font, centred in the panel
        for k, it in enumerate(rows):
            it["pos"], it["dx"], it["dy"] = "center", 0, (k - (len(rows) - 1) / 2) * 170
    if len(pics) == 1 and rows:
        pics[0]["size"], pics[0]["pos"], pics[0]["dx"], pics[0]["dy"] = "s", "bottom-right", 0, 0
    elif len(pics) == 1 and pics[0].get("type") == "illust":
        hero = pics[0]
        hero["size"] = "xl" if len(others) <= 1 else "l"
        if hero.get("pos", "center") in ("left", "right", "top-left", "top-right", "bottom-left", "bottom-right", "bottom"):
            hero["pos"], hero["dx"], hero["dy"] = "center", 0, 0
        for it in others:   # side emoji stickers keep their corner; words go above the picture
            if it.get("type") == "text" and it.get("pos", "center") == "center" and it.get("style") not in ("stamp",):
                it["pos"] = "top"
    elif len(pics) == 2:   # two people/props side by side
        for it, side in zip(pics, ("left", "right")):   # m each: two l/xl pictures overlap in the middle
            it["size"], it["pos"], it["dx"], it["dy"] = "m", side, 0, 0
    elif not pics and not has_clip:
        emo = next((it for it in items if it.get("type") == "emoji"), None)
        if emo:
            emo["size"], emo["pos"], emo["dx"], emo["dy"] = "xl", "center", 0, 0
    return items


def build(segments, visuals, times, cues, title, credit, picker, font_path, clips=None) -> tuple[str, list]:
    """segments: [{sfx}], visuals: [{bg, items}], times: [(start, end)],
    clips: per scene None or {dir, n} from stock.clip_frames (background footage)."""
    scenes_html, scenes_data = [], []
    clips = clips or [None] * len(segments)
    for i, (seg, vis, (st, en)) in enumerate(zip(segments, visuals, times)):
        items = vis.get("items") or [{"type": "emoji", "text": "🤔", "pos": "center", "size": "l", "fx": "pop"}]
        items = _hero(items, bool(clips[i] if i < len(clips) else None), picker) or             [{"type": "emoji", "text": "🤔", "pos": "center", "size": "xl", "fx": "pop"}]
        bg_key = vis.get("bg", "white")
        parts, data = [], []
        pics = {}
        floor = _item_floor(cues, st, en)
        room = floor - 24      # usable height between the top margin and the caption box
        for j, it in enumerate(items[:6]):
            typ = it.get("type", "text")
            cx, cy = POS.get(it.get("pos", "center"), POS["center"])
            cy += float(it.get("dy", 0))
            cx += float(it.get("dx", 0))
            at = min(0.9, max(0.0, float(it.get("at", 0.0))))
            fx = it.get("fx") or ("stamp" if it.get("style") == "stamp" else "pop")
            d = {"type": typ, "x": cx, "y": cy, "at": at, "fx": fx, "seed": (i * 7 + j) % 10}
            if typ in ("illust", "crowd"):
                path = picker.fetch(it.get("q", "")) if picker else None
                if not path:   # fallback: emoji, or the query text as a label
                    typ = d["type"] = "emoji" if it.get("emoji") else "text"
                    it = dict(it, text=it.get("emoji") or it.get("label") or "", style="label")
            if typ == "illust":
                side = SIZE.get(it.get("size", "m"), 390)
                pics[j] = (path, side)
                w, h = _fit(path, side)
                if h > room:   # taller than the space above the caption: shrink, keep the shape
                    w, h = _fit(path, int(side * room / h))
                d.update(w=w, h=h)
                parts.append(f'<div class="it" style="width:{w}px;height:{h}px;z-index:{Z[typ]}">'
                             f'<img src="{file_url(path)}"></div>')
            elif typ == "crowd":
                n = max(2, min(40, int(it.get("count", 10))))
                cols = min(n, 10 if n > 20 else 6 if n > 6 else n)
                rows = -(-n // cols)
                cell = min(int(900 / cols), int(min(560, room) / rows))
                d.update(w=cols * cell, h=rows * cell)
                kids = "".join(f'<img src="{file_url(path)}" style="width:{cell}px;height:{cell}px;object-fit:contain;'
                               f'position:absolute;left:{(k % cols) * cell}px;top:{(k // cols) * cell}px">' for k in range(n))
                parts.append(f'<div class="it" style="width:{d["w"]}px;height:{d["h"]}px;z-index:{Z["crowd"]}">{kids}</div>')
            elif typ == "emoji":
                side = min(int(SIZE.get(it.get("size", "m"), 400) * 0.8), int(room))
                d.update(w=side, h=side)
                parts.append(f'<div class="it emo" style="width:{side}px;height:{side}px;font-size:{int(side * .82)}px;'
                             f'z-index:{Z["emoji"]}">{esc(it.get("text", ""))}</div>')
            elif it.get("style") == "post":
                text = str(it.get("text", ""))
                longest = max((len(x) for x in text.split("\n")), default=1)
                fs = min(92, int(860 / (0.95 * max(1, longest))))
                lines = max(1, text.count("\n") + 1)
                w, h = 1000, int(fs * 1.3 * lines + 280)
                d.update(w=w, h=h, type="text")
                today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y.%m.%d")
                parts.append(f'<div class="it tx post" style="width:{w}px;height:{h}px;z-index:{Z["text"]};display:flex">'
                             f'<div class="board">🔥 썰가챠 썰 게시판 ›</div><div class="ttl" style="font-size:{fs}px">{esc(text)}</div>'
                             f'<div class="meta"><div class="ava"></div><b>익명</b><span>{today}</span></div></div>')
            else:
                style = it.get("style", "label")
                text = str(it.get("text", ""))
                base = {"big": 160, "label": 96, "small": 58, "red": 130, "stamp": 160, "bubble": 80, "row": 80}.get(style, 96)
                longest = max((len(x) for x in text.split("\n")), default=1)
                fs = min(base, int(960 / (0.74 * max(1, longest))))
                lines = max(1, text.count("\n") + 1)
                w = int(min(1040, 0.74 * fs * longest + (140 if style in ("big", "stamp", "bubble", "row") else 30)))
                h = int(fs * 1.2 * lines + (60 if style in ("big", "stamp", "bubble", "row") else 10))
                d.update(w=w, h=h)
                if style in ("big", "red") and (n := _num(text)) and fx in ("pop", "zoom", "shake", "drop"):
                    d["num"] = n
                parts.append(f'<div class="it tx {style}" style="width:{w}px;height:{h}px;font-size:{fs}px;'
                             f'z-index:{Z["text"]};display:flex;align-items:center;justify-content:center">{esc(text)}</div>')
            # keep the item inside the panel: above the caption box of this scene
            # (drop starts 420 px above its resting place, so clamping the rest position is enough)
            d["y"] = min(max(d["y"], d["h"] / 2 + 24), max(floor - d["h"] / 2, d["h"] / 2 + 24))
            margin = 60 if d["fx"] == "stamp" else 10   # a stamp lands rotated ~9 deg - its corners swing out
            d["x"] = min(max(d["x"], d["w"] / 2 + margin), W - d["w"] / 2 - margin) if d["w"] < W - 2 * margin else W / 2
            data.append(d)
        _unstack(data, floor)
        _separate(parts, data, pics, floor)
        clip = clips[i] if i < len(clips) else None
        if clip:   # after the items so el.children[j] still indexes them
            base = file_url(Path(clip["dir"]) / "f_")
            parts.append(f'<img class="bgv" src="{base}0001.jpg"><div class="tag">자료화면</div>')
        scenes_html.append(f'<div class="sc">{"".join(parts)}</div>')
        scenes_data.append({"start": st, "end": en, "items": data, "bg": BG.get(bg_key, BG["white"]),
                            "dark": bg_key in ("night", "red"), "shake": seg.get("sfx") in SHAKE_SFX,
                            "clip": {"base": base, "n": clip["n"]} if clip else None})
    t1, t2 = title
    css = CSS.replace("FONT", file_url(font_path))
    payload = {"scenes": scenes_data, "caps": cues, "lead": LEAD, "fps": FPS}
    html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{css}</style></head><body>'
            f'<div id="title" style="font-size:{title_size([t1, t2])}px"><div>{esc(t1)}</div><div class="t2">{esc(t2)}</div></div>'
            f'<div id="panel"><div id="credit">{esc(credit)}</div><div id="cam">{"".join(scenes_html)}</div></div>'
            f'<div id="cap"></div><script>window.DATA={json.dumps(payload, ensure_ascii=False)};</script>'
            f'<script>{JS}</script></body></html>')
    return html, [s["start"] for s in scenes_data[1:]]


def find_chrome() -> str:
    import shutil
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if (p := shutil.which(name)):
            return p
    raise RuntimeError("Chrome not found")


def capture(html_path: Path, out_mp4: Path, total: float) -> Path:
    from playwright.sync_api import sync_playwright
    frames = int(round(total * FPS))
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_mp4)], stdin=subprocess.PIPE)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=find_chrome(),
                              args=["--allow-file-access-from-files", "--disable-gpu", "--no-sandbox"])
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.goto(file_url(html_path))
        pg.wait_for_function("window.READY === true", timeout=30000)
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        for f in range(frames):
            pg.evaluate("t => render(t)", f / FPS)
            ff.stdin.write(pg.screenshot(type="jpeg", quality=92))
        b.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")
    return out_mp4
