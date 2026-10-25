"""Layout preview without the voice: the same motion page and the same on-page QA as a real render,
with word timings estimated from syllable counts (no TTS, no stock download - a grey frame stands in
for each stock clip so the scene is laid out as it will be). Takes seconds per script.

    python preview.py scripts/2026-10-21-1800.json [more.json ...]
    -> output/preview/<name>/qa_sheet.jpg  + the issues and bad caption breaks printed

Use it before pushing a hand-written script, and after changing motion.py (run it over many scripts).
"""
import json
import sys
from pathlib import Path

import yaml

import motion
from illust import Picker
from pipeline.tts import Word

REPO = Path(__file__).resolve().parent
SYL_PER_S = 7.0   # the voice at speed 1.3 (2026-10-17: 6.7-8.4 syl/s)


def fake_words(text: str, start: float) -> tuple[list[Word], float]:
    words, t = [], start + 0.04
    for tok in text.split():
        d = max(0.12, sum(1 for c in tok if not c.isascii() or c.isalnum()) / SYL_PER_S)
        words.append(Word(tok, t, t + d))
        t += d + 0.03
    return words, t + 0.06 - start


def grey_clip(work: Path) -> dict:
    d = work / "clip_grey"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "f_0001.jpg"
    if not f.exists():
        from PIL import Image
        Image.new("RGB", (1080, 960), (110, 110, 110)).save(f)
    return {"dir": str(d), "n": 1, "url": "grey"}


def preview(script_path: Path, cfg: dict) -> dict:
    from playwright.sync_api import sync_playwright
    script = json.loads(script_path.read_text(encoding="utf-8"))
    work = REPO / "output" / "preview" / script_path.stem
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("f_*.jpg"):
        old.unlink()
    segments = list(script["segments"])
    egg, egg_q = motion.egg_parts(script.get("like_egg"))
    like = cfg.get("like_cta") or {}
    if egg in motion.EGGS and like.get("enabled", True) and egg in (like.get("eggs") or []):
        segments.append(motion.egg_segment(egg, egg_q))
    times, words, cursor = [], [], 0.0
    for i, seg in enumerate(segments):
        ws, dur = fake_words(seg["text"], cursor)
        dur += 0.16 if i == 0 else float(seg.get("hold", 0.0)) if i == len(segments) - 1 else 0.0
        times.append((round(cursor, 3), round(cursor + dur, 3)))
        words.append(ws)
        cursor += dur
    total = cursor + 0.35
    visuals = [seg.get("visual") or motion.card_to_visual(seg.get("card") or {}) for seg in segments]
    cues = motion.caption_cues(words, int(cfg.get("caption_line_chars", 11)), int(cfg.get("caption_words", 6)),
                               int(cfg.get("caption_lines", 2)), [seg.get("cap") for seg in segments])
    clips = [grey_clip(work) if (v or {}).get("video") or (v or {}).get("pic") else None for v in visuals]
    html, _ = motion.build(segments, visuals, times, cues, script["title_lines"], "", Picker(),
                           REPO / "assets" / "fonts" / "BlackHanSans-Regular.ttf", clips,
                           episode=script.get("episode", 1))
    page = work / "motion.html"
    page.write_text(html, encoding="utf-8")
    issues, frames = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=motion.find_chrome(),
                              args=["--allow-file-access-from-files", "--disable-gpu", "--no-sandbox"])
        pg = b.new_page(viewport={"width": motion.W, "height": motion.H}, device_scale_factor=1)
        pg.goto(motion.file_url(page))
        pg.wait_for_function("window.READY === true", timeout=30000)
        pg.wait_for_timeout(300)
        for t in pg.evaluate("qaTimes()"):
            pg.evaluate("t => render(t)", t)
            found = pg.evaluate("t => qa(t)", t)
            issues += found
            shot = pg.screenshot(type="jpeg", quality=85)
            (work / f"f_{t:05.2f}.jpg").write_bytes(shot)   # full size, to zoom into
            frames.append((round(t, 2), shot, bool(found)))
        b.close()
    sheet = motion.qa_sheet(frames, work / "qa_sheet.jpg")
    return {"sheet": str(sheet), "issues": motion.qa_summary(issues), "breaks": motion.bad_breaks(cues, words),
            "cues": [" / ".join(" ".join(w[0] for w in ln) for ln in c["lines"]) for c in cues]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    bad = 0
    for arg in sys.argv[1:]:
        r = preview(Path(arg), cfg)
        print(f"== {arg}  ->  {r['sheet']}")
        for x in r["issues"]:
            print(f"   화면 {x['t']}s {x['kind']}: '{x['text']}' - {x['msg']} (x{x['seen']})")
        for x in r["breaks"]:
            print(f"   자막 끊김: {x}")
        bad += len(r["issues"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
