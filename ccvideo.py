"""YouTube footage licensed CC BY for scene backgrounds - the real place/thing a sentence talks about.

    clip = clip_frames("seoul subway line 2", 4.2, work_dir / "cc_03", fps=30)

2026-10-25 (사용자: "재사용 허용 ccby된 영상들 찾아서 ... 추가하면 좋을거같은데" → 화면 출처 표기 OK):
Pixabay/Pexels have "a subway", not "Seoul Line 2"; YouTube's Creative Commons filter has the real ones.
CC BY asks for credit, and the description carries no sources (2026-10-04), so the credit goes on the
footage itself: the corner tag reads "영상: <channel> · CC BY" while the clip is on screen.

The script asks with "visual": {"cc": ["seoul subway line 2", "seoul subway train"], "video": [...]} - the
`video` words stay as the fallback when nothing here passes. A clip is taken only when
  - yt-dlp's full metadata says "Creative Commons Attribution" (the search filter alone is not trusted),
  - neither title nor channel looks like a broadcaster, a re-upload, a vlog or a person on camera
    (people re-upload news under CC BY - that is not theirs to license; a stranger's face must not stand
    in for someone in the story),
  - the query's first word and one more of its words are in the title or tags (stock.py's rule).
Videos up to 10 min are downloaded whole (720p H.264) and a few seconds from the middle are used.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import stock

PANEL = stock.PANEL
CACHE = Path.home() / ".cache" / "issue-shorts" / "cc"
CC_FILTER = "EgIwAQ%3D%3D"   # YouTube search "Creative Commons" filter
# not the uploader's own footage, or not footage of a place/thing
NOT_OWN = re.compile(r"\b(kbs|mbc|sbs|jtbc|ytn|mbn|tv ?chosun|channel ?a|yonhap|연합뉴스|뉴스|news|cnn|bbc|nhk|fox|abc|nbc|"
                     r"cbs|reuters|ap|afp|sky|reupload|re-upload|full episode|episode|ep\.?\s?\d|clip|highlights?|"
                     r"trailer|teaser|mv|m/v|music video|official|lyrics?|cover|reaction|react|podcast|interview|"
                     r"vlog|브이로그|asmr|mukbang|먹방|review|unboxing|tutorial|how to|meme|compilation|funny|prank|"
                     r"vr|panorama|timelapse|hyperlapse|live ?stream|streaming|gameplay|minecraft|roblox|animation|animated|cartoon|ai)\b")
# 20-25 min videos (1438 s, 1203 s) never finished a 5 s section in 75 s - ffmpeg crawls through their index -
# while 45-111 s ones took 3-8 s (2026-10-25)
MIN_S, MAX_S = 20, 600
_BUDGET = [180.0]   # seconds of yt-dlp per render, so a slow day can't stall it (stock.py's _WAIT_BUDGET)


def _ytdlp() -> list[str] | None:
    exe = shutil.which("yt-dlp")
    return [exe] if exe else None


def _run(args: list[str], timeout: int) -> str:
    """yt-dlp with a hard timeout. A section download runs ffmpeg as a grandchild; subprocess.run's timeout
    killed only yt-dlp and then waited on the pipes that ffmpeg still held (a stalled stream hung 4+ min),
    so the whole tree is killed."""
    import os
    import signal
    import tempfile
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        pr = subprocess.Popen(args, stdout=out, stderr=err, stdin=subprocess.DEVNULL, **kw)
        try:
            code = pr.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pr.pid)], capture_output=True)
            else:
                os.killpg(pr.pid, signal.SIGKILL)
            pr.wait()
            raise RuntimeError(f"timed out after {timeout}s")
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8", "replace")
        if code:
            raise RuntimeError(err.read().decode("utf-8", "replace").strip().splitlines()[-1:] or ["yt-dlp failed"])
        return stdout


def _search(query: str, base: list[str]) -> list[dict]:
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+") + "&sp=" + CC_FILTER
    out = _run(base + ["--flat-playlist", "-I", "1:10", "-j", "--no-warnings", url], 60)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def _words(query: str) -> tuple[str, list[str]]:
    ws = re.findall(r"[a-z0-9]+", query.lower())
    return ws[0], [w for w in ws[1:] if len(w) > 2]


def _relevant(text: str, query: str) -> bool:
    head, rest = _words(query)
    text = text.lower()
    if not re.search(r"\b" + re.escape(head), text):
        return False
    if rest and not any(re.search(r"\b" + re.escape(w), text) for w in rest):
        return False
    if stock.PEOPLE.search(text) and not stock.PEOPLE.search(query.lower()):
        return False
    return not (stock.ANIMAL.search(text) and not stock.ANIMAL.search(query.lower()))


def _passes(entry: dict, query: str) -> bool:
    who = f"{entry.get('channel') or ''} {entry.get('uploader') or ''}"
    title = entry.get("title") or ""
    dur = entry.get("duration") or 0
    if "360" in f"{title} {who}" or "vr180" in f"{title} {who}".lower():   # equirectangular, warped in a panel
        return False
    return (MIN_S <= dur <= MAX_S and not NOT_OWN.search(f"{title} {who}".lower())
            and _relevant(f"{title} {' '.join(entry.get('tags') or [])}", query))


# What a few seconds cut from the middle of a video often shows instead of its title: 'busan beach' gave
# a title card, then trees, then the beach (2026-10-25). CLIP (torch is installed for TTS anyway, the model
# is ~600 MB in the HF cache) must pick the query over these in all 3 frames ('incheon airport terminal'
# passed 2 of 3 on an in-flight map screen).
NOT_IT = ["a close-up of a person's face", "a person talking to the camera", "a title card or text on a screen",
          "a blurry dark image", "trees and leaves", "the inside of a car", "a room indoors",
          "a map on a screen", "a computer or phone screen", "an airplane cabin"]
_CLIP: list = []


def _shows(frames: list[Path], query: str, vid: str) -> bool:
    try:
        import torch
        from PIL import Image
        from transformers import CLIPModel, CLIPProcessor
        if not _CLIP:
            name = "openai/clip-vit-base-patch32"
            _CLIP.extend([CLIPModel.from_pretrained(name).eval(), CLIPProcessor.from_pretrained(name)])
        model, proc = _CLIP
        ims = [Image.open(frames[min(len(frames) - 1, int(len(frames) * k))]).convert("RGB") for k in (0.2, 0.5, 0.8)]
        with torch.no_grad():
            probs = model(**proc(text=[f"a photo of {query}"] + NOT_IT, images=ims, return_tensors="pt",
                                 padding=True)).logits_per_image.softmax(-1)
    except Exception as ex:   # no check, no clip: a wrong clip is worse than the stock fallback
        print(f"    cc: picture check unavailable ({ex}) - skipped")
        return False
    hits = int((probs.argmax(-1) == 0).sum())
    if hits < 3:
        print(f"    cc: {vid} shows {query!r} in {hits}/3 frames - skipped")
    return hits >= 3


def _cut(src: Path, start: float, seconds: float, out_dir: Path, fps: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = PANEL
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{seconds + 0.3:.2f}", "-i", str(src),
             "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}",
             "-q:v", "4", str(out_dir / "f_%04d.jpg")], check=True)
    except subprocess.CalledProcessError as ex:
        print(f"    cc: cut failed: {ex}")
    return sorted(out_dir.glob("f_*.jpg"))


def _credit(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return f"영상: {name[:18] + '…' if len(name) > 19 else name} · CC BY"


def clip_frames(query: str, seconds: float, out_dir: Path, fps: int = 30, used: set | None = None) -> dict | None:
    base = _ytdlp()
    if not base or not query.strip():
        return None
    used = used if used is not None else set()
    query = query.strip()
    try:
        hits = [e for e in _search(query, base) if e.get("id") and f"yt{e['id']}" not in used and _passes(e, query)]
    except Exception as ex:
        print(f"    cc: search failed for {query!r}: {ex}")
        return None
    import time
    for e in hits[:4]:
        if _BUDGET[0] <= 0:
            print("    cc: time budget used up - falling back")
            return None
        t0 = time.time()
        vid = e["id"]
        url = f"https://www.youtube.com/watch?v={vid}"
        try:
            meta = json.loads(_run(base + ["-j", "--no-warnings", "--no-playlist", url], 60))
        except Exception as ex:
            print(f"    cc: metadata failed for {vid}: {ex}")
            continue
        lic = meta.get("license") or ""
        if "creative commons" not in lic.lower():
            print(f"    cc: {vid} is not CC BY on its own page ({lic or 'standard licence'}) - skipped")
            continue
        if not _passes(meta, query):   # full tags/channel now known
            continue
        dur = float(meta.get("duration") or 0)
        CACHE.mkdir(parents=True, exist_ok=True)
        src = CACHE / f"{vid}.mp4"
        try:
            if not src.exists():
                # the whole (short) video with yt-dlp's own chunked downloader, then cut here: ffmpeg seeking
                # into YouTube's stream (what --download-sections does) stalled for 1-2 min on most videos
                # while plain range requests ran at ~10 MB/s (2026-10-25)
                _run(base + ["-q", "--no-warnings", "--no-playlist",
                             "-f", "bv*[vcodec^=avc1][height<=720][height>=480][protocol=https][filesize<150M]/"
                                   "bv*[vcodec^=avc1][height<=720][height>=480][protocol=https]",
                             "-o", str(src), url], 60)
        except Exception as ex:
            src.unlink(missing_ok=True)
            print(f"    cc: clip {vid} failed: {ex}")
            continue
        finally:
            _BUDGET[0] -= time.time() - t0
        # the middle shows the thing (openings are titles and faces); with the file here, other spots are cheap
        for at in (0.35, 0.6, 0.2, 0.8):
            start = min(max(2.0, dur * at), max(0.0, dur - 2 - seconds - 0.6))
            frames = _cut(src, start, seconds, out_dir, fps)
            if frames and not stock._keyed(frames[len(frames) // 2]) and _shows(frames, query, vid):
                used.add(f"yt{vid}")
                who = meta.get("channel") or meta.get("uploader") or ""
                print(f"    cc: clip {vid} @{start:.0f}s by {who!r} for {query!r} ({len(frames)} frames)")
                return {"dir": str(out_dir), "n": len(frames), "id": f"yt{vid}", "url": url, "by": who,
                        "tag": _credit(who), "license": lic, "at": round(start, 1)}
            for f_ in frames:
                f_.unlink()
    print(f"    cc: nothing usable for {query!r}")
    return None


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "seoul subway train"
    print(clip_frames(q, 4.0, Path("output") / "cc_test" / re.sub(r"\W+", "_", q)))
