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
import html as _html
import json
import os
import re
import subprocess
from pathlib import Path

W, H, FPS = 1080, 1920, 30
PANEL_TOP, PANEL_H = 520, 845
LEAD = 0.18          # visuals land a hair before the voice (J-cut) - late visuals feel slow

POS = {  # centre points in panel coordinates (1080 x 845); the caption box owns y > ~650
    "center": (540, 395), "left": (290, 405), "right": (790, 405),
    "top": (540, 112), "bottom": (540, 575),
    "top-left": (270, 130), "top-right": (810, 130),
    "bottom-left": (270, 575), "bottom-right": (810, 575),
}
SIZE = {"s": 240, "m": 390, "l": 520, "xl": 640}
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
def caption_cues(words, line_chars: int = 11, max_words: int = 6) -> list[dict]:
    """[{s, e, lines:[[(text, start, end), ...], ...]}] - at most 2 lines per cue."""
    from pipeline.captions import _group_by_lines, _wrap
    cues = []
    for seg in words:
        for cue in _group_by_lines(seg, max_words, line_chars):
            lines = _wrap(cue.words, line_chars)
            cues.append({"s": cue.start, "e": cue.end,
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
#title { position:absolute; top:205px; left:30px; right:30px; height:310px; display:flex;
  flex-direction:column; justify-content:center; align-items:center; text-align:center;
  line-height:1.18; letter-spacing:-1px; }
#title div { white-space:nowrap; }
#title .t2 { color:#FFE14D; }
#panel { position:absolute; top:520px; left:0; width:1080px; height:845px; overflow:hidden; background:#fff; }
#cam { position:absolute; inset:0; transform-origin:540px 380px; }
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
.tx.small { color:#333; font-size:52px; }
.tx.red { color:#e01e1e; font-size:120px; text-shadow:0 6px 0 rgba(0,0,0,.15); }
.tx.stamp { color:#e01e1e; border:14px solid #e01e1e; border-radius:24px; padding:8px 40px 0; font-size:150px; }
.tx.bubble { color:#111; background:#fff; border:7px solid #111; border-radius:46px; padding:20px 40px 12px;
  font-size:72px; box-shadow:0 8px 0 rgba(0,0,0,.15); }
.tx.row { color:#111; background:#fff; border:6px solid #111; border-radius:20px; padding:16px 32px 8px;
  font-size:64px; text-align:left; }
#credit { position:absolute; top:14px; left:20px; right:20px; font-family:'Malgun Gothic','Noto Sans CJK KR',sans-serif;
  font-weight:700; font-size:24px; color:rgba(0,0,0,.42); white-space:nowrap; overflow:hidden; z-index:5; }
#credit.dark { color:rgba(255,255,255,.55); }
#cap { position:absolute; left:0; right:0; top:1365px; height:0; z-index:9; }
#cap .box { position:absolute; left:50%; bottom:22px; transform:translateX(-50%); background:#000;
  padding:10px 26px 4px; border-radius:6px; text-align:center; font-size:68px; line-height:1.22; white-space:nowrap; }
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
  scenes.forEach((el, i) => {
    const s = D.scenes[i];
    const on = t >= s.start - D.lead && (i === scenes.length - 1 || t < D.scenes[i + 1].start - D.lead);
    el.style.visibility = on ? 'visible' : 'hidden';
    if (!on) return;
    const pin = (t - (s.start - D.lead)) / .16;
    el.style.transform = `scale(${1.05 - .05 * eo(pin) + .03 * C((t - s.start) / Math.max(1, s.end - s.start))})`;
    el.style.transformOrigin = '540px 380px';
    panel.style.background = s.bg;
    credit.className = s.dark ? 'dark' : '';
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


def title_size(lines) -> int:
    longest = max(len(l) for l in lines)
    return max(64, min(130, int(1000 / (0.76 * max(1, longest)))))


def build(segments, visuals, times, cues, title, credit, picker, font_path) -> tuple[str, list]:
    """segments: [{sfx}], visuals: [{bg, items}], times: [(start, end)]."""
    scenes_html, scenes_data = [], []
    for i, (seg, vis, (st, en)) in enumerate(zip(segments, visuals, times)):
        items = vis.get("items") or [{"type": "emoji", "text": "🤔", "pos": "center", "size": "l", "fx": "pop"}]
        bg_key = vis.get("bg", "white")
        parts, data = [], []
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
                w, h = _fit(path, side)
                d.update(w=w, h=h)
                parts.append(f'<div class="it" style="width:{w}px;height:{h}px;z-index:{Z[typ]}">'
                             f'<img src="{file_url(path)}"></div>')
            elif typ == "crowd":
                n = max(2, min(40, int(it.get("count", 10))))
                cols = min(n, 10 if n > 20 else 6 if n > 6 else n)
                rows = -(-n // cols)
                cell = min(int(900 / cols), int(560 / rows))
                d.update(w=cols * cell, h=rows * cell)
                kids = "".join(f'<img src="{file_url(path)}" style="width:{cell}px;height:{cell}px;object-fit:contain;'
                               f'position:absolute;left:{(k % cols) * cell}px;top:{(k // cols) * cell}px">' for k in range(n))
                parts.append(f'<div class="it" style="width:{d["w"]}px;height:{d["h"]}px;z-index:{Z["crowd"]}">{kids}</div>')
            elif typ == "emoji":
                side = int(SIZE.get(it.get("size", "m"), 400) * 0.8)
                d.update(w=side, h=side)
                parts.append(f'<div class="it emo" style="width:{side}px;height:{side}px;font-size:{int(side * .82)}px;'
                             f'z-index:{Z["emoji"]}">{esc(it.get("text", ""))}</div>')
            else:
                style = it.get("style", "label")
                text = str(it.get("text", ""))
                base = {"big": 150, "label": 84, "small": 52, "red": 120, "stamp": 150, "bubble": 72, "row": 64}.get(style, 84)
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
            # keep the item inside the panel: below the credit line, above the caption box
            # (drop starts 420 px above its resting place, so clamping the rest position is enough)
            if d["h"] < PANEL_H - 200:
                d["y"] = min(max(d["y"], d["h"] / 2 + 44), PANEL_H - 150 - d["h"] / 2)
            d["x"] = min(max(d["x"], d["w"] / 2 + 10), W - d["w"] / 2 - 10) if d["w"] < W - 20 else W / 2
            data.append(d)
        scenes_html.append(f'<div class="sc">{"".join(parts)}</div>')
        scenes_data.append({"start": st, "end": en, "items": data, "bg": BG.get(bg_key, BG["white"]),
                            "dark": bg_key in ("night", "red"), "shake": seg.get("sfx") in SHAKE_SFX})
    t1, t2 = title
    css = CSS.replace("FONT", file_url(font_path))
    payload = {"scenes": scenes_data, "caps": cues, "lead": LEAD}
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
