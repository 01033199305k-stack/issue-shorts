"""Free stock footage from Pexels for scene backgrounds.

    clip = clip_frames("taxi street night", 4.2, work_dir / "clip_03", fps=30)

A scene's visual may carry "video": "<English search words>". The clip is
cropped to the white panel (1080x845) and written out as JPEG frames that the
motion page swaps in frame by frame (headless capture cannot play <video>
deterministically). Needs PEXELS_API_KEY; without it - or when nothing is
found - the scene simply keeps its plain background.

Pexels licence: free for commercial use, no attribution required. It forbids
showing identifiable people in a bad light, so the script writer is told to
search for places and objects, not people.
"""
import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

PANEL = (1080, 845)
CACHE = Path.home() / ".cache" / "issue-shorts" / "pexels"


def _search(query: str, key: str) -> list[dict]:
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "medium", "per_page": 8})
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "issue-shorts"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("videos", [])


def _best_file(video: dict) -> dict | None:
    """mp4 closest to 1280 px wide (enough for a 1080 panel, small to download)."""
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
    files = [f for f in files if f["width"] >= 960] or files
    return min(files, key=lambda f: abs(f["width"] - 1280)) if files else None


def clip_frames(query: str, seconds: float, out_dir: Path, fps: int = 30, used: set | None = None) -> dict | None:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key or not query.strip():
        return None
    used = used if used is not None else set()
    try:
        videos = _search(query, key)
    except Exception as ex:
        print(f"    stock: search failed for {query!r}: {ex}")
        return None
    for v in videos:
        if v["id"] in used or v.get("duration", 0) < 3:
            continue
        f = _best_file(v)
        if not f:
            continue
        CACHE.mkdir(parents=True, exist_ok=True)
        src = CACHE / f"{v['id']}_{f['width']}.mp4"
        try:
            if not src.exists():
                req = urllib.request.Request(f["link"], headers={"User-Agent": "issue-shorts"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    src.write_bytes(r.read())
            out_dir.mkdir(parents=True, exist_ok=True)
            w, h = PANEL
            dur = min(seconds + 0.3, max(1.0, v["duration"] - 0.6))
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.3", "-t", f"{dur:.2f}", "-i", str(src),
                 "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}",
                 "-q:v", "4", str(out_dir / "f_%04d.jpg")], check=True)
        except Exception as ex:
            print(f"    stock: clip {v['id']} failed: {ex}")
            continue
        n = len(list(out_dir.glob("f_*.jpg")))
        if n:
            used.add(v["id"])
            return {"dir": str(out_dir), "n": n, "id": v["id"], "url": v.get("url", ""),
                    "by": (v.get("user") or {}).get("name", "")}
    print(f"    stock: nothing usable for {query!r}")
    return None
