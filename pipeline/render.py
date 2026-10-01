"""One script (segments + card PNGs) -> one finished 9:16 short.

Segment fields: text (captions), say (what the voice reads, optional),
photo (card PNG), sfx (one-shot on the cut into this segment; on segment 0
it fires at t=0 as the hook sting; "" = silent cut).
"""
from pathlib import Path

from pipeline import assemble, captions, kenburns, tts
from pipeline.tts import Word

TRANSITION = 0.25


def render(segments: list[dict], cfg: dict, repo: Path, work_dir: Path, out_path: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    last = len(segments) - 1

    # Voice first, for every segment, so the TTS weights can be released
    # before ffmpeg and Chrome need the memory.
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

    clips, segment_words, cut_times, cursor = [], [], [], 0.0
    for i, (seg, res) in enumerate(zip(segments, results)):
        if i > 0:
            cut_times.append(cursor)
        segment_words.append([Word(w.text, w.start + cursor, w.end + cursor) for w in res.words])
        cursor += res.duration
        # Every clip but the last carries the crossfade overlap; xfade eats it
        # back, so the faded timeline still matches the narration length.
        clip_len = res.duration + (TRANSITION if i < last else 0.0)
        clip = work_dir / f"clip_{i:02d}.mp4"
        kenburns.make_clip(Path(seg["photo"]), clip, clip_len,
                           zoom="in" if i % 2 == 0 else "out",
                           zoom_target=float(cfg.get("zoom_target", 1.06)),
                           fit=1.0, lift=0, bg_color="#000000",
                           pin_top=int(cfg.get("pin_top", 535)))
        clips.append(clip)

    video = assemble.concat_videos(clips, work_dir / "video.mp4", transition=TRANSITION)
    narration = assemble.concat_audio(wavs, work_dir / "narration.wav")

    brand = cfg.get("brand") or {}
    ass = captions.build_ass(
        segment_words, work_dir / "captions.ass",
        total_duration=cursor,
        brand_accent=brand.get("accent", "#FFE14D"),
        brand_ink=brand.get("ink", "#000000"),
        font="Black Han Sans",
        fontsize=int(cfg.get("fontsize", 74)),
        max_words=int(cfg.get("caption_words", 6)),
        line_chars=int(cfg.get("caption_line_chars", 11)),
    )

    sfx_dir = repo / cfg.get("sfx_dir", "assets/sfx")
    default_sfx = cfg.get("transition_sfx", "whoosh")

    def sfx_file(name: str) -> Path | None:
        p = sfx_dir / f"{name}.wav"
        return p if name and p.exists() else None

    sfx: list[tuple[float, Path]] = []
    if (p := sfx_file(segments[0].get("sfx", ""))):
        sfx.append((0.0, p))
    for seg, t in zip(segments[1:], cut_times):
        name = seg.get("sfx") or default_sfx
        if (p := sfx_file(name)):
            sfx.append((t, p))

    bgm = repo / cfg["bgm"] if cfg.get("bgm") else None
    assemble.mux_final(video, narration, ass, out_path, bgm_path=bgm,
                       fonts_dir=repo / "assets" / "fonts", sfx=sfx)
    return {"duration": round(cursor, 2), "matches": [round(r.match, 2) for r in results],
            "sfx": len(sfx)}
