"""9:16 frames laid out like @군림보: a black frame, a two-line title (white +
yellow) that stays for the whole short, and one drawn scene panel per segment.

News stills and community screenshots are not ours to reuse, so every panel
is drawn here: HTML -> headless Chrome at 2x -> LANCZOS down to 1080x1920.

Card kinds (fields not listed are ignored):
    scene  - emoji, label, sub
    number - value, label, sub
    quote  - lines, who
    stamp  - word, sub
    list   - head, items

Layout (measured against pipeline/captions.py):
* Title block y 205-515; Shorts' own top UI sits above ~y200. The renderer
  pins y 0-535 so the title never moves while the panel zooms.
* Panel y 540-1150. Captions are bottom-anchored at MarginV 550, so a two-line
  cue spans ~y1200-1370 - just under the panel.
"""
import html as _html
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

W, H, SCALE = 1080, 1920, 2
REPO = Path(__file__).resolve().parent
FONT = (REPO / "assets" / "fonts" / "BlackHanSans-Regular.ttf").resolve().as_posix()
YELLOW = "#FFE14D"
RED = "#FF4D4D"

THEMES = {
    "night": "linear-gradient(160deg,#1d2b4a,#0c1222)",
    "alert": "linear-gradient(160deg,#4a1414,#1a0808)",
    "money": "linear-gradient(160deg,#173d2a,#08180f)",
    "cold":  "linear-gradient(160deg,#2a2f3a,#0f1116)",
    "warm":  "linear-gradient(160deg,#4a3410,#1c1305)",
}

SANS = "'Malgun Gothic','Noto Sans CJK KR','Noto Sans KR',sans-serif"
EMOJI = "'Segoe UI Emoji','Noto Color Emoji','Apple Color Emoji',sans-serif"

CSS = f"""
@font-face {{ font-family: BH; src: url('file:///{FONT.lstrip('/')}'); }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; background:#000; overflow:hidden;
        font-family: BH, {SANS}; color:#fff; }}
.title {{ position:absolute; top:205px; left:30px; right:30px; height:310px;
          display:flex; flex-direction:column; justify-content:center; align-items:center;
          text-align:center; line-height:1.18; letter-spacing:-1px; }}
.title div {{ white-space:nowrap; }}
.t2 {{ color:{YELLOW}; }}
.panel {{ position:absolute; top:540px; left:0; width:{W}px; height:610px; overflow:hidden;
          display:flex; flex-direction:column; justify-content:center; align-items:center;
          text-align:center; padding:40px 70px; }}
.credit {{ display:none; position:absolute; top:18px; left:24px; right:24px; font-family:{SANS};
           font-size:24px; color:rgba(255,255,255,.55); font-weight:700; text-align:left;
           white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.emoji {{ font-family:{EMOJI}; font-size:190px; line-height:1.1; }}
.label {{ font-size:84px; line-height:1.15; margin-top:18px; }}
.sub {{ font-size:46px; color:rgba(255,255,255,.75); margin-top:16px; line-height:1.25; }}
.value {{ font-size:170px; color:{YELLOW}; line-height:1; letter-spacing:-3px; white-space:nowrap; }}
.bubble {{ background:#fff; color:#111; font-size:72px; padding:26px 46px; border-radius:46px;
           margin:14px 0; box-shadow:0 10px 30px rgba(0,0,0,.4); }}
.bubble.r {{ background:{RED}; color:#fff; }}
.who {{ font-size:40px; color:rgba(255,255,255,.7); margin-top:18px; }}
.stamp {{ font-size:190px; color:{RED}; border:16px solid {RED}; border-radius:28px;
          padding:10px 50px 0; transform:rotate(-8deg); line-height:1.15; white-space:nowrap; }}
.head {{ font-size:60px; color:{YELLOW}; margin-bottom:26px; }}
.item {{ font-size:66px; background:rgba(255,255,255,.1); border-radius:22px; padding:18px 34px;
         margin:10px 0; width:100%; text-align:left; line-height:1.2; }}
"""


def e(s):
    return _html.escape(str(s)).replace("\n", "<br>")


def title_size(lines):
    # Measured: Black Han Sans Hangul renders ~0.72em wide (spaces included);
    # keep the longer line inside ~1000px.
    longest = max(len(l) for l in lines)
    return max(64, min(130, int(1000 / (0.76 * max(1, longest)))))


def fit(text, base, width=940, em=0.72):
    """Shrink a one-line display string that would overflow the panel."""
    longest = max((len(l) for l in str(text).split("\n")), default=1)
    return min(base, int(width / (em * max(1, longest))))


def panel_body(c):
    k = c["kind"]
    if k == "scene":
        out = f'<div class="emoji">{e(c.get("emoji", ""))}</div>'
        if c.get("label"):
            out += f'<div class="label" style="font-size:{fit(c["label"], 84)}px">{e(c["label"])}</div>'
    elif k == "number":
        out = (f'<div class="value" style="font-size:{fit(c["value"], 170, em=0.62)}px">{e(c["value"])}</div>'
               f'<div class="label" style="font-size:{fit(c.get("label", ""), 84)}px">{e(c.get("label", ""))}</div>')
    elif k == "quote":
        out = "".join(f'<div class="bubble{" r" if i % 2 else ""}" style="font-size:{fit(l, 72, 860)}px">{e(l)}</div>'
                      for i, l in enumerate(c.get("lines") or []))
        if c.get("who"):
            out += f'<div class="who">{e(c["who"])}</div>'
    elif k == "stamp":
        out = f'<div class="stamp" style="font-size:{fit(c["word"], 190, 760)}px">{e(c["word"])}</div>'
    elif k == "list":
        out = f'<div class="head">{e(c.get("head", ""))}</div>' + "".join(
            f'<div class="item" style="font-size:{fit(i, 66, 860)}px">{e(i)}</div>' for i in (c.get("items") or []))
    else:
        raise ValueError(f"unknown card kind: {k}")
    if c.get("sub"):
        out += f'<div class="sub" style="font-size:{fit(c["sub"], 46)}px">{e(c["sub"])}</div>'
    return out


def card_html(title, credit, c):
    t1, t2 = title
    bg = THEMES.get(c.get("theme", "night"), THEMES["night"])
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>'
            f'<div class="title" style="font-size:{title_size([t1, t2])}px"><div>{e(t1)}</div>'
            f'<div class="t2">{e(t2)}</div></div>'
            f'<div class="panel" style="background:{bg}"><div class="credit">{e(credit)}</div>'
            f'{panel_body(c)}</div></body></html>')


def find_chrome():
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError("Chrome not found")


def shoot(chrome, html_path, png_path, profile):
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/").lstrip("/")
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
           f"--user-data-dir={profile}", f"--force-device-scale-factor={SCALE}",
           "--virtual-time-budget=3000", f"--screenshot={png_path}", f"--window-size={W},{H}", url]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not os.path.exists(png_path):
        raise RuntimeError(f"capture failed: {png_path}\n{(r.stderr or '')[:600]}")
    im = Image.open(png_path)
    if im.size != (W, H):
        im.convert("RGB").resize((W, H), Image.LANCZOS).save(png_path)


def render_cards(title, credit, cards, outdir: Path) -> list[Path]:
    outdir = Path(outdir)
    htmldir = outdir / "_html"
    htmldir.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    profile = tempfile.mkdtemp(prefix="issuecards-")
    paths = []
    try:
        for i, c in enumerate(cards):
            hp = htmldir / f"{i:02d}.html"
            hp.write_text(card_html(title, credit, c), encoding="utf-8")
            pp = outdir / f"{i:02d}.png"
            shoot(chrome, hp, pp, profile)
            paths.append(pp)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return paths


def check_cards(paths) -> list[str]:
    """Measured guards: the title must stay inside the frame and the panel
    content must not touch its edges (a sign some text overflowed)."""
    problems = []
    for p in paths:
        im = Image.open(p).convert("L")
        t = im.crop((0, 180, W, 535)).point(lambda v: 255 if v > 60 else 0).getbbox()
        if t and (t[0] < 12 or t[2] > W - 12):
            problems.append(f"{p.name}: title touches the frame edge {t}")
        body = im.crop((0, 600, W, 1150)).point(lambda v: 255 if v > 200 else 0).getbbox()
        if body and (body[0] < 8 or body[2] > W - 8):
            problems.append(f"{p.name}: panel content touches the edge {body}")
    return problems
