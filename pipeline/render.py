"""One script -> one finished 9:16 short, in the reference channel's style.

1. voice every segment (Sohee, delivery instruction) and time its words
2. build the motion page (title, white panel, いらすとや scenes, caption box)
3. capture it frame by frame with headless Chrome
4. mix narration + music bed (ducked) + sound effects at the cuts

Segment fields: text (captions), say (what the voice reads), sfx (one-shot on
the cut into this segment; on segment 0 it fires at t=0), visual (v2) or card (v1).
"""
from pathlib import Path

import motion
from illust import Picker
from pipeline import assemble, tts
from pipeline.tts import Word

SFX_GAIN = {"whoosh": -15.0}   # the cut whoosh fires 10+ times a video - keep it under the voice


def render(script: dict, cfg: dict, repo: Path, work_dir: Path, out_path: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    segments = script["segments"]

    wavs, results = [], []
    for i, seg in enumerate(segments):
        print(f"  voice {i + 1}/{len(segments)}: {seg['text'][:40]}")
        res = tts.synthesize(
            seg.get("say") or seg["text"], work_dir / f"seg_{i:02d}.wav",
            engine=cfg["engine"], voice=cfg["voice"], instruct=cfg.get("instruct", ""),
            speed=float(cfg.get("speed", 1.0)), display=seg["text"], seed=7 + i)
        print(f"    {res.duration:.1f}s, match {res.match:.2f}")
        wavs.append(res.audio_path)
        results.append(res)
    tts.release_models()

    times, words, cursor = [], [], 0.0
    for res in results:
        times.append((round(cursor, 3), round(cursor + res.duration, 3)))
        words.append([Word(w.text, w.start + cursor, w.end + cursor) for w in res.words])
        cursor += res.duration
    total = cursor + 0.35   # let the last frame breathe

    visuals = [seg.get("visual") or motion.card_to_visual(seg.get("card") or {}) for seg in segments]
    cues = motion.caption_cues(words, int(cfg.get("caption_line_chars", 11)), int(cfg.get("caption_words", 6)))
    picker = Picker()
    html, cuts = motion.build(segments, visuals, times, cues, script["title_lines"], script.get("credit", ""),
                              picker, repo / "assets" / "fonts" / "BlackHanSans-Regular.ttf")
    page = work_dir / "motion.html"
    page.write_text(html, encoding="utf-8")
    print(f"  frames: {int(total * motion.FPS)} ({len(picker.used)} illustrations)")
    video = motion.capture(page, work_dir / "video.mp4", total)
    narration = assemble.concat_audio(wavs, work_dir / "narration.wav")

    sfx_dir = repo / cfg.get("sfx_dir", "assets/sfx")
    default_sfx = cfg.get("transition_sfx", "whoosh")
    sfx = []

    def add(name: str, at: float):
        p = sfx_dir / f"{name}.wav"
        if name and name != "none" and p.exists():
            sfx.append((max(0.0, at), p, SFX_GAIN.get(name, -9.0)))

    add(segments[0].get("sfx", ""), 0.0)
    for seg, t in zip(segments[1:], cuts):
        add(seg.get("sfx") or default_sfx, t - motion.LEAD)

    bgm = repo / cfg["bgm"] if cfg.get("bgm") else None
    assemble.mux_final(video, narration, None, out_path, bgm_path=bgm, sfx=sfx)
    return {"duration": round(cursor, 2), "matches": [round(r.match, 2) for r in results],
            "sfx": len(sfx), "illustrations": len(picker.used), "cuts": len(cuts) + 1}
