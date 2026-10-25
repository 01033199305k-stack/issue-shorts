"""Real photos for a scene: free stock stills (Pixabay, then Pexels; Openverse CC0 only with STILL_OPENVERSE=1).

2026-10-25 (사용자: "패턴이 너무 동일해서 재미가 없어, 실사 사진이 짧주처럼 들어가면 좋을 것 같은데"):
@짧은주녑 fills the panel with a real photo of the thing in every scene, but its photos are other people's
(reverse search found two private Threads posts and an album cover - no permission, no credit). We get the
same look from licences that allow it: Pixabay and Pexels (free for commercial use, no attribution) and
Openverse results limited to CC0 / public domain. Never news, community or SNS pictures.

The script asks with "visual": {"pic": ["convenience store counter", "cash register"]} - English words for
a place or an object, candidates in order. The photo becomes the scene's background like stock footage
(slow push-in, tagged '자료사진'), and the scene's illustrations stand on top of it as usual; a scene with
no items is a plain photo with the caption, the @짧은주녑 look.

People are filtered out on purpose (no identifiable person may stand in for someone in a story), and so are
AI-generated, cartoon and 3D images.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import photo
import stock

CACHE = Path.home() / ".cache" / "issue-shorts" / "stills"
MIN_W = 960
PEOPLE = re.compile(r"\b(people|persons?|man|men|woman|women|girls?|boys?|child(ren)?|kids?|baby|portrait|face|selfie|"
                    r"couple|family|model|businessman|businesswoman|student|worker|crowd|lady|guy)\b")


def _get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "issue-shorts", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _pixabay(query: str, key: str) -> list[dict]:
    d = _get_json("https://pixabay.com/api/?" + urllib.parse.urlencode(
        {"key": key, "q": query, "image_type": "photo", "orientation": "horizontal", "safesearch": "true",
         "per_page": 20, "min_width": MIN_W}))
    return [{"id": f"pbi{h['id']}", "desc": h.get("tags", ""), "link": h.get("largeImageURL") or h.get("webformatURL"),
             "w": h.get("imageWidth", 0), "url": h.get("pageURL", "")} for h in d.get("hits", [])]


def _pexels(query: str, key: str) -> list[dict]:
    d = _get_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "per_page": 20}), {"Authorization": key})
    return [{"id": f"pxi{p['id']}", "desc": (p.get("alt") or "") + " " + p.get("url", "").replace("-", " "),
             "link": (p.get("src") or {}).get("large2x"), "w": p.get("width", 0), "url": p.get("url", "")}
            for p in d.get("photos", [])]


def _openverse(query: str, _key: str = "") -> list[dict]:
    d = _get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "license": "cc0,pdm", "page_size": 20, "mature": "false"}))
    return [{"id": f"ov{r['id']}", "desc": (r.get("title") or "") + " " + " ".join(t.get("name", "") for t in r.get("tags") or []),
             "link": r.get("url"), "w": r.get("width") or 0, "url": r.get("foreign_landing_url", "")}
            for r in d.get("results", [])]


def relevant(hit: dict, query: str) -> bool:
    desc = hit["desc"].lower()
    words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2]
    if not words or words[0] not in desc:   # the head word must be in the photo's own description
        return False
    if stock.FAKE.search(desc) or (stock.ANIMAL.search(desc) and not stock.ANIMAL.search(query.lower())):
        return False
    if PEOPLE.search(desc) and not PEOPLE.search(query.lower()):
        return False
    return (hit.get("w") or MIN_W) >= MIN_W and bool(hit.get("link"))


def find(query: str, used: set | None = None) -> dict | None:
    """First usable photo for the words: {url, who, path} (the shape photo.frames takes)."""
    used = used if used is not None else set()
    keys = (("pixabay", _pixabay, os.environ.get("PIXABAY_API_KEY", "").strip()),
            ("pexels", _pexels, os.environ.get("PEXELS_API_KEY", "").strip()),
            # Openverse (CC0/PD, no key) only on request: tried 2026-10-25, 'cash register' gave a 1940s factory
            # floor and 'police car' a Toronto 1957 cruiser - a wrong photo is worse than the illustrated panel
            ("openverse", _openverse, "-" if os.environ.get("STILL_OPENVERSE") else ""))
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, search, key in keys:
        if not key:
            continue
        try:
            hits = [h for h in search(query, key) if h["id"] not in used and relevant(h, query)]
        except Exception as ex:
            print(f"    still: {name} search failed for {query!r}: {ex}")
            continue
        for h in hits[:4]:
            dst = CACHE / (re.sub(r"[^A-Za-z0-9]", "_", h["id"]) + ".img")
            try:
                if not dst.exists():
                    stock._download(h["link"], dst)
                from PIL import Image
                with Image.open(dst) as im:
                    w, hh = im.size
            except Exception as ex:
                dst.unlink(missing_ok=True)
                print(f"    still: {h['id']} failed: {ex}")
                continue
            if w < MIN_W or not 1.0 <= w / hh <= 2.4:   # portrait shots crop to a sliver of the subject
                continue
            used.add(h["id"])
            print(f"    still: {name} {h['id']} for {query!r} ({w}x{hh}) {h['url'][:70]}")
            return {"url": h["url"], "who": name, "path": str(dst)}
    print(f"    still: nothing usable for {query!r}")
    return None


def frames(query_list, seconds: float, out_dir: Path, fps: int = 30, used: set | None = None) -> dict | None:
    """The first candidate that finds a photo, as panel frames tagged '자료사진' (like stock.clip_frames)."""
    for k, q in enumerate([query_list] if isinstance(query_list, str) else query_list or []):
        if (hit := find(q.strip(), used)):
            return photo.frames(hit, seconds, Path(f"{out_dir}_{k}"), fps, tag="자료사진", strip_bottom=False)
    return None
