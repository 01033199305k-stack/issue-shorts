"""One script -> one finished 9:16 short, in the reference channel's style.

1. voice every segment (Sohee, delivery instruction) and time its words
2. build the motion page (title, white panel, いらすとや scenes, caption box)
3. capture it frame by frame with headless Chrome
4. mix narration + music bed (ducked) + sound effects at the cuts

Segment fields: text (captions), say (what the voice reads), sfx (one-shot on
the cut into this segment; on segment 0 it fires at t=0), tone (optional acting
note added to the voice instruction), visual (v2) or card (v1).
"""
import zlib
from pathlib import Path

import motion
import stock
from illust import Picker
from pipeline import assemble, tts
from pipeline.tts import Word

SFX_GAIN = {"whoosh": -15.0}   # the cut whoosh fires 10+ times a video - keep it under the voice
# 2026-10-17: the references move from one sentence to the next in ~0.1 s and only hold a beat after
# the title and before a turn. Our clips kept 0.17 s of padding everywhere (5.3-6.7 syl/s over the
# first 6 s vs 6.7-8.4 for @dolongcha/@통찰맨).
HEAD_PAD, TAIL_PAD = 0.04, 0.06
TURN = ("헐", "근데", "결국", "여기서", "자,", "아니", "그런데", "알고 보니")
# phone-speaker clarity for the narration: cut rumble, a little less boom, more presence, even level
VOICE_CHAIN = ("highpass=f=75,equalizer=f=250:t=q:w=1:g=-1.5,equalizer=f=3500:t=q:w=1.2:g=2.5,"
               "acompressor=threshold=-20dB:ratio=3:attack=5:release=90:makeup=2")


def gap_after(i: int, segments: list) -> float:
    """Extra silence after sentence i: a beat after the title card, a short one before a turn."""
    if i >= len(segments) - 1:
        return 0.0
    if i == 0:
        return 0.16
    return 0.1 if segments[i + 1].get("text", "").startswith(TURN) else 0.0


def _pad(path: Path, seconds: float) -> None:
    import numpy as np
    import soundfile as sf
    a, sr = sf.read(str(path), dtype="float32")
    sf.write(str(path), np.concatenate([a, np.zeros((int(seconds * sr),) + a.shape[1:], dtype=np.float32)]), sr)


def voice_instruct(base: str, tone: str | None, persona: str = "") -> str:
    """The voice instruction for one sentence.

    Without a tone the channel-wide delivery (config instruct) reads it as before.
    With a tone (segment "tone", e.g. "기가 막혀 피식 헛웃음 섞인 어이없는 말투로")
    the acting note leads as a command and only an emotion-free persona follows -
    the base's "흥분해서 빠르게" would fight a whisper or a sigh. CustomVoice's
    own examples are short imperatives ("用特别愤怒的语气说")."""
    base = (base or "").strip().rstrip(".")
    tone = (tone or "").strip().rstrip(".")
    if not tone:
        return base
    persona = (persona or "").strip().rstrip(".")
    return f"{tone} 말해. 전체적으로는 {persona}." if persona else f"{tone} 말해."


def render(script: dict, cfg: dict, repo: Path, work_dir: Path, out_path: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    segments = list(script["segments"])
    egg = script.get("like_egg")
    like = cfg.get("like_cta") or {}
    if egg in motion.EGGS and like.get("enabled", True) and egg in (like.get("eggs") or []):
        segments.append(motion.egg_segment(egg))   # spoken "좋아요 누르면 좋아요가 … 변해요~" last line

    wavs, results = [], []
    for i, seg in enumerate(segments):
        print(f"  voice {i + 1}/{len(segments)}: {seg['text'][:40]}")
        res = tts.synthesize(
            seg.get("say") or seg["text"], work_dir / f"seg_{i:02d}.wav",
            engine=cfg["engine"], voice=cfg["voice"], instruct=voice_instruct(cfg.get("instruct", ""), seg.get("tone"), cfg.get("instruct_persona", "")),
            speed=float(cfg.get("speed", 1.0)), display=seg["text"], seed=7 + i,
            head_pad=HEAD_PAD, tail_pad=TAIL_PAD, takes=int(cfg.get("tts_takes", 1)))
        if (g := gap_after(i, segments)):
            _pad(res.audio_path, g)
            res.duration = round(res.duration + g, 3)
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
    cues = motion.caption_cues(words, int(cfg.get("caption_line_chars", 11)), int(cfg.get("caption_words", 6)),
                               int(cfg.get("caption_lines", 2)), [seg.get("cap") for seg in segments])
    picker = Picker()
    used_clips: set = set()
    clips = []
    for i, (vis, (st, en)) in enumerate(zip(visuals, times)):
        qs = (vis or {}).get("video") or []
        clip = None
        for k, q in enumerate([qs] if isinstance(qs, str) else qs):   # candidates in order, like illust q lists
            if (clip := stock.clip_frames(q, en - st + motion.LEAD + 0.2, work_dir / f"clip_{i:02d}_{k}",
                                          motion.FPS, used_clips)):
                break
        clips.append(clip)
    print(f"  stock clips: {sum(1 for c in clips if c)}/{sum(1 for v in visuals if (v or {}).get('video'))}")
    html, cuts = motion.build(segments, visuals, times, cues, script["title_lines"], script.get("credit", ""),
                              picker, repo / "assets" / "fonts" / "BlackHanSans-Regular.ttf", clips,
                              episode=script.get("episode"))
    page = work_dir / "motion.html"
    page.write_text(html, encoding="utf-8")
    print(f"  frames: {int(total * motion.FPS)} ({len(picker.used)} illustrations)")
    video = motion.capture(page, work_dir / "video.mp4", total)
    narration = assemble.concat_audio(wavs, work_dir / "narration_raw.wav")
    tts.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(narration), "-af", VOICE_CHAIN, str(work_dir / "narration.wav")])
    narration = work_dir / "narration.wav"

    sfx_dir = repo / cfg.get("sfx_dir", "assets/sfx")
    default_sfx = cfg.get("transition_sfx", "whoosh")
    sfx = []

    seed = script.get("slug") or script.get("title_lines", [""])[0]

    def pick(name: str, k: int) -> Path | None:
        """<name>.wav plus any variants in <name>/*.wav: each video gets its own pick
        (stable per slug, so a re-render sounds the same), so the opener is not one sound forever."""
        pool = sorted((sfx_dir / name).glob("*.wav")) + [p for p in [sfx_dir / f"{name}.wav"] if p.exists()]
        return pool[zlib.crc32(f"{seed}|{name}|{k}".encode()) % len(pool)] if pool else None

    def add(name: str, at: float, k: int):
        if name and name != "none" and (p := pick(name, k if name == default_sfx else 0)):
            sfx.append((max(0.0, at), p, SFX_GAIN.get(name, -9.0)))

    add(segments[0].get("sfx", ""), 0.0, 0)
    for k, (seg, t) in enumerate(zip(segments[1:], cuts), 1):
        add(seg.get("sfx") or default_sfx, t - motion.LEAD, k)

    bgm = repo / cfg["bgm"] if cfg.get("bgm") else None
    assemble.mux_final(video, narration, None, out_path, bgm_path=bgm, sfx=sfx,
                       bgm_gain_db=float(cfg.get("bgm_gain_db", -10)))
    return {"stock_clips": [c["url"] for c in clips if c], "duration": round(cursor, 2), "matches": [round(r.match, 2) for r in results],
            "sfx": len(sfx), "illustrations": len(picker.used), "cuts": len(cuts) + 1}
