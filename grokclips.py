"""Grok Imagine scenes made on the operator's PC (2026-11-10 사용자: "grok 동영상 만드는거 썰가챠에 추가").

The Chrome extension 「썰가챠 Grok 비디오 메이커」 (auto mode) reads new scripts from this public repo,
makes a 6 s clip for every segment with `visual.grok`, and tools/grok_upload.py attaches them to a
prerelease tagged grok-<key> (start.json first, then scene_XX.mp4 + done.json).
The renderer waits for that release only while it looks alive; PC off / Chrome closed / out of credits
= the scenes fall back to their usual picture/stock, so a slot never misses because of Grok.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_SLUG = os.environ.get("GITHUB_REPOSITORY") or "01033199305k-stack/issue-shorts"
START_WAIT = 8 * 60     # no start.json by then = nobody is making clips for this script
DONE_WAIT = 25 * 60     # started but not finished by then = use what is there
PANEL = (1080, 960)


def wanted(script: dict) -> list[int]:
    return [i for i, s in enumerate(script.get("segments", [])) if ((s.get("visual") or {}).get("grok") or {}).get("prompt")]


def _get(url: str, binary: bool = False):
    headers = {"User-Agent": "issue-shorts", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    if binary:
        headers["Accept"] = "application/octet-stream"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read() if binary else json.loads(r.read())


def _release(key: str) -> dict | None:
    try:
        return _get(f"https://api.github.com/repos/{REPO_SLUG}/releases/tags/grok-{key}")
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            return None
        raise


def fetch(key: str, script: dict, out_dir: Path) -> dict[int, Path]:
    """{segment index: mp4} of the Grok clips made for this script (empty when there are none)."""
    want = wanted(script)
    if not want or not key:
        return {}
    t0, rel = time.time(), None
    while True:
        try:
            rel = _release(key)
        except Exception as ex:
            print(f"  grok: release lookup failed: {ex}")
            rel = None
        names = {a["name"] for a in (rel or {}).get("assets", [])}
        waited = time.time() - t0
        if "done.json" in names:
            break
        if rel is None and waited > START_WAIT:
            print(f"  grok: no clips started for {key} in {START_WAIT // 60} min - scenes keep their usual pictures")
            return {}
        if waited > DONE_WAIT:
            print(f"  grok: not finished after {DONE_WAIT // 60} min - using the {len(names & {f'scene_{i:02d}.mp4' for i in want})} clips there")
            break
        time.sleep(30)
    out_dir.mkdir(parents=True, exist_ok=True)
    got = {}
    for a in (rel or {}).get("assets", []):
        name = a["name"]
        if not (name.startswith("scene_") and name.endswith(".mp4")):
            continue
        try:
            i = int(name[6:-4])
        except ValueError:
            continue
        if i not in want:
            continue
        dst = out_dir / name
        try:
            dst.write_bytes(_get(a["url"], binary=True))
            got[i] = dst
        except Exception as ex:
            print(f"  grok: download {name} failed: {ex}")
    print(f"  grok: {len(got)}/{len(want)} clips for {key}")
    return got


def clip_frames(src: Path, seconds: float, out_dir: Path, fps: int = 30) -> dict | None:
    """The clip as panel-sized frames, held on its last frame when the line is longer than 6 s."""
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = PANEL
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-t", f"{seconds + 0.3:.2f}",
                        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},"
                               f"tpad=stop_mode=clone:stop_duration={max(0.0, seconds - 5.5):.2f}",
                        "-q:v", "4", str(out_dir / "f_%04d.jpg")], check=True)
    except Exception as ex:
        print(f"  grok: frames failed for {src.name}: {ex}")
        return None
    n = len(list(out_dir.glob("f_*.jpg")))
    # '재연': it is a re-enactment, not footage of the real event (the stock tag '자료화면' would say otherwise)
    return {"dir": str(out_dir), "n": n, "id": f"grok-{src.stem}", "url": "", "by": "", "tag": "재연"} if n else None
