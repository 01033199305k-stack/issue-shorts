"""Free stock footage (Pixabay or Pexels) for scene backgrounds.

    clip = clip_frames("taxi street night", 4.2, work_dir / "clip_03", fps=30)

A scene's visual may carry "video": "<English search words>". The clip is
cropped to the white panel (1080x960) and written out as JPEG frames that the
motion page swaps in frame by frame (headless capture cannot play <video>
deterministically). Needs PIXABAY_API_KEY or PEXELS_API_KEY (Pixabay first);
without one - or when nothing relevant is found - the scene keeps its plain background.

Both licences: free for commercial use, no attribution required, but no
identifiable people in a bad light - so the script writer is told to search
for places and objects, not people.
"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

PANEL = (1080, 960)
CACHE = Path.home() / ".cache" / "issue-shorts" / "pexels"


def _search_pixabay(query: str, key: str) -> list[dict]:
    """Pixabay hits in the Pexels shape the rest of this module uses."""
    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": query, "per_page": 8, "safesearch": "true"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "issue-shorts"}), timeout=20) as r:
        hits = json.loads(r.read()).get("hits", [])
    out = []
    for h in hits:
        files = [{"file_type": "video/mp4", "width": f.get("width", 0), "link": f["url"]}
                 for f in (h.get("videos") or {}).values() if f.get("url")]
        out.append({"id": f"pb{h['id']}", "duration": h.get("duration", 0), "url": h.get("pageURL", ""),
                    "tags": h.get("tags", ""),
                    "user": {"name": h.get("user", "")}, "video_files": files})
    return out


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


CHROMA = ("green screen", "greenscreen", "chroma", "blue screen", "alpha channel", "transparent")
# Pixabay's AI clips pass any word test: "camera photographer studio" got an owl in a sweater
# holding a camera (tags: ai generated, animal, anthropomorphic, ..., photographer, camera, studio).
FAKE = re.compile(r"\b(ai[ -]?generated|generative|anthropomorphic|animation|animated|cartoon|3d|render(ing)?|cgi)\b")
ANIMAL = re.compile(r"\b(animals?|owls?|birds?|cats?|kittens?|dogs?|puppy|monkeys?|bears?|fox(es)?|rabbits?|wildlife|pets?)\b")


def _describe(video: dict) -> str:
    """What the clip is about: Pixabay tags, or the words in a Pexels page slug
    (pexels.com/video/a-judo-match-on-a-mat-12345/)."""
    slug = (video.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{video.get('tags', '')} {slug.replace('-', ' ')}".lower()


def _relevant(video: dict, query: str) -> bool:
    """The full query's main noun (its first word) must be in the clip's own description, AI/CG and
    animal clips are out unless asked for,
    and keyed footage is out: a short phrase like "judo mat" used to return a yoga pavilion,
    "stopwatch timer" a stopwatch on a green screen."""
    desc = _describe(video)
    head = query.split()[0].lower()
    if FAKE.search(desc) or (ANIMAL.search(desc) and not ANIMAL.search(query.lower())):
        return False
    return head in desc and not any(c in desc for c in CHROMA)


def _keyed(frame: Path) -> bool:
    """Backstop for untagged chroma footage: a frame that is mostly pure green or blue."""
    from PIL import Image
    with Image.open(frame) as im:
        px = list(im.convert("RGB").resize((48, 32)).getdata())
    keyed = sum(1 for r, g, b in px if (g > 140 and g > r + 60 and g > b + 60) or (b > 140 and b > r + 60 and b > g + 40))
    return keyed > 0.3 * len(px)


def _find(query: str, pixabay: str, pexels: str) -> list[dict]:
    """Pixabay first, Pexels when Pixabay has nothing relevant for this phrase."""
    for key, search in ((pixabay, _search_pixabay), (pexels, _search)):
        if not key:
            continue
        try:
            if (videos := [v for v in search(query, key) if _relevant(v, query)]):
                return videos
        except Exception as ex:
            print(f"    stock: search failed for {query!r}: {ex}")
    return []


def clip_frames(query: str, seconds: float, out_dir: Path, fps: int = 30, used: set | None = None) -> dict | None:
    pixabay = os.environ.get("PIXABAY_API_KEY", "").strip()
    pexels = os.environ.get("PEXELS_API_KEY", "").strip()
    if not (pixabay or pexels) or not query.strip():
        return None
    used = used if used is not None else set()
    query = query.strip()
    # no shortening of the query: a wrong clip is worse than the plain illustrated panel
    videos = [v for v in _find(query, pixabay, pexels)
              if v["id"] not in used and v.get("duration", 0) >= 3 and _relevant(v, query)]
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
        frames = sorted(out_dir.glob("f_*.jpg"))
        if frames and _keyed(frames[len(frames) // 2]):
            print(f"    stock: clip {v['id']} looks like chroma-key footage - skipped")
            for f_ in frames:
                f_.unlink()
            continue
        n = len(frames)
        if n:
            used.add(v["id"])
            return {"dir": str(out_dir), "n": n, "id": v["id"], "url": v.get("url", ""),
                    "by": (v.get("user") or {}).get("name", "")}
    print(f"    stock: nothing usable for {query!r}")
    return None
