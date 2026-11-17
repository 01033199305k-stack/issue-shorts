"""Listen to a finished video with earshot (github.com/Leonxlnx/earshot, MIT, CPU only).

2026-11-17 (사용자: "설치해서 붙여"): the picture already gets qa_sheet.jpg; this is the sound side.
earshot measures loudness, true peak, clipping, silences and whether each picture cut has a sound on it,
and draws sound_sheet.png (frames + spectrogram + loudness + cut sync). It only warns - it never holds a
video back, because its event tags are hints and taste is not its job. If earshot is not installed the
render goes on as before.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

TARGET_LUFS = -14.0      # assemble.mux_final aims here (loudnorm I=-14)
LUFS_TOLERANCE = 2.0
MAX_TRUE_PEAK = -1.0
MIN_SILENCE_S = 0.5      # a gap this long inside a 30-60 s short is dead air


def check(video: Path, out_dir: Path, timeout: int = 600) -> dict:
    exe = shutil.which("earshot")
    if not exe:
        return {"skipped": "earshot 미설치"}
    js, wav = out_dir / "sound_qa.json", out_dir / "sound_qa_stereo.wav"
    try:
        # Our mix is mono. earshot reads a mono file as dual-mono and reports it 3 dB louder than
        # ffmpeg ebur128 does (11/17: -11.4 vs -14.5 LUFS on the same video), so hand it a stereo copy;
        # picture cuts still come from the video.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "2",
                        "-c:a", "pcm_s16le", str(wav)], check=True, capture_output=True, timeout=timeout)
        subprocess.run([exe, "timeline", str(wav), "--video", str(video), "--detail", "low", "--out", str(js)],
                       check=True, capture_output=True, timeout=timeout)
        subprocess.run([exe, "sheet", str(wav), "--video", str(video), "-o", str(out_dir / "sound_sheet.png")],
                       check=True, capture_output=True, timeout=timeout)
        data = json.loads(js.read_text(encoding="utf-8"))
        # Loudness and true peak by the same meter loudnorm uses (ffmpeg ebur128), on the real mono file.
        data.setdefault("loudness", {}).update(ffmpeg_loudness(video))
    except Exception as ex:     # never let the ear break a render
        return {"error": str(ex)[:300]}
    finally:
        wav.unlink(missing_ok=True)
    return summarize(data)


def ffmpeg_loudness(video: Path) -> dict:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af", "ebur128=peak=true",
                       "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    tail = (p.stderr or "").split("Summary:")[-1]
    i, tp = re.search(r"I:\s*(-?[\d.]+) LUFS", tail), re.search(r"Peak:\s*(-?[\d.]+) dBFS", tail)
    return {k: float(m.group(1)) for k, m in (("integrated_lufs", i), ("true_peak_dbtp", tp)) if m}


def summarize(data: dict) -> dict:
    loud = data.get("loudness") or {}
    stats = ((data.get("sync") or {}).get("cuts") or {}).get("stats") or {}
    dur = float(data.get("duration") or 0)
    lufs, tp = loud.get("integrated_lufs"), loud.get("true_peak_dbtp")
    issues = []
    if lufs is not None and abs(lufs - TARGET_LUFS) > LUFS_TOLERANCE:
        issues.append(f"음량 {lufs} LUFS (목표 {TARGET_LUFS:g}±{LUFS_TOLERANCE:g})")
    if tp is not None and tp > MAX_TRUE_PEAK:
        issues.append(f"순간 최대 {tp} dBTP (기준 {MAX_TRUE_PEAK:g} 이하)")
    if (loud.get("clipping") or {}).get("runs"):
        issues.append(f"찢어지는 소리(클리핑) {loud['clipping']['runs']}곳: {loud['clipping'].get('times', [])[:5]}")
    for s in loud.get("silences") or []:
        st, en = (s.get("start"), s.get("end")) if isinstance(s, dict) else (s[0], s[1])
        if st is not None and en is not None and en - st >= MIN_SILENCE_S and 0.3 < st and en < dur - 0.3:
            issues.append(f"소리 빈 구간 {st:.1f}~{en:.1f}s")
    if loud.get("digital_silence"):
        issues.append("소리가 아예 없음")
    return {
        "lufs": lufs, "true_peak": tp, "lra": loud.get("lra_lu"),
        "cuts": stats.get("n"), "cut_hit_100ms": stats.get("hit_within_100ms"),
        "cuts_without_sound": stats.get("no_sound", []),
        "issues": issues,
    }
