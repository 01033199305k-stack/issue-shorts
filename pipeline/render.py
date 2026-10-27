"""One script -> one finished 9:16 short, in the reference channel's style.

1. voice every segment (Sohee, delivery instruction) and time its words
2. build the motion page (title, white panel, いらすとや scenes, caption box)
3. capture it frame by frame with headless Chrome
4. mix narration + music bed (ducked) + sound effects at the cuts

Segment fields: text (captions), say (what the voice reads), sfx (one-shot on
the cut into this segment; on segment 0 it fires at t=0), tone (optional acting
note added to the voice instruction), join (true: the sentence runs on into the
next screen, so the two are voiced as one take), visual (v2) or card (v1).
"""
import re
import zlib
from pathlib import Path

import motion
import photo
import stillphoto
import ccvideo
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
    """Extra silence after sentence i: a beat after the title card, a short one before a turn,
    and the last sentence's own hold (the like line)."""
    if i >= len(segments) - 1:
        return float(segments[i].get("hold", 0.0))   # the like line keeps its drawing up while viewers press
    if i == 0:
        return 0.16
    return 0.1 if segments[i + 1].get("text", "").startswith(TURN) else 0.0


def voice_runs(segments: list) -> list[list[int]]:
    """Screens voiced as one take. 2026-10-23: the references run a sentence on across a cut ("~는데,"),
    but Sohee voiced alone drops the end of "들어왔는데," like a full stop (4-13 semitones under the line,
    the same as the "~음." controls) and a "carry on" tone lifted only 2 of 4. A segment with "join": true
    is voiced together with the next one, so the pitch carries over, and the take is cut back into screens."""
    runs, cur = [], []
    for i, seg in enumerate(segments):
        cur.append(i)
        if not (seg.get("join") and 0 < i < len(segments) - 1):
            runs.append(cur)
            cur = []
    return runs


def run_tone(segs: list) -> str | None:
    """One acting note for a joined take: each screen's tone in order ("처음엔 A, 이어서 B")."""
    tones = []
    for s in segs:
        t = (s.get("tone") or "").strip().rstrip(".")
        if t and t not in tones:
            tones.append(t)
    if len(tones) <= 1:
        return tones[0] if tones else None
    return "처음엔 " + ", 이어서 ".join(tones)


def _quiet_point(a, sr: int, lo: float, hi: float) -> float:
    """The quietest 20 ms inside [lo, hi] - where one syllable hands over to the next."""
    import numpy as np
    win, hop = int(0.02 * sr), int(0.005 * sr)
    i0, i1 = max(0, int(lo * sr)), min(len(a) - win, int(hi * sr))
    if i1 <= i0:
        return (lo + hi) / 2
    starts = range(i0, i1, hop)
    rms = [float(np.sqrt(np.mean(a[s:s + win] ** 2))) for s in starts]
    return (starts[int(np.argmin(rms))] + win / 2) / sr


def _heard_index(sm, i: int, n: int) -> int:
    """Where position i of the script lands in what whisper heard (difflib opcodes)."""
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if i1 <= i < i2:
            return j1 + (i - i1) if tag == "equal" else j1 + round((i - i1) / (i2 - i1) * (j2 - j1))
    return n


def split_take(res, segs: list, paths: list[Path]) -> list:
    """Cut one joined take back into per-screen clips in the gap between the words where a screen ends.
    Whisper hears the take again and the script is lined up with it by sound (tts._norm), because the
    take's own word times are shares of the caption text, which drift where captions and speech differ
    (5잔 / 다섯 잔): the first try put "데" of "들어왔는데" on the next screen and cut "카페" in half.
    The clips are sample-exact neighbours, so played in a row they are the original take."""
    import difflib
    import soundfile as sf
    a, sr = sf.read(str(res.audio_path), dtype="float32")
    heard = tts.hear(res.audio_path)
    says = [tts._norm(s.get("say") or s["text"]) for s in segs]
    sounds, owner = "", []   # every heard sound unit, and the heard word it belongs to
    for n, w in enumerate(heard):
        u = tts._norm(w.text)
        sounds += u
        owner += [n] * len(u)
    cut = [0]
    if sounds:
        sm = difflib.SequenceMatcher(None, "".join(says), sounds, autojunk=False)
        starts = [k for k in range(len(owner)) if k == 0 or owner[k] != owner[k - 1]]
        pos = 0
        for s in says[:-1]:
            pos += len(s)
            h = _heard_index(sm, pos, len(sounds))
            w = owner[min(starts, key=lambda k: abs(k - h))]   # the heard word the next screen opens with
            lo, hi = heard[max(0, w - 1)].end - 0.06, heard[w].start + 0.06
            cut.append(max(cut[-1] + 1, int(round(_quiet_point(a, sr, min(lo, hi), max(lo, hi)) * sr))))
    else:   # whisper heard nothing: split by each screen's share of the script
        total = sum(len(s) for s in says) or 1
        for k in range(1, len(says)):
            cut.append(int(len(a) * sum(len(s) for s in says[:k]) / total))
    cut.append(len(a))
    out = []
    for j, (seg, path) in enumerate(zip(segs, paths)):
        piece = a[cut[j]:cut[j + 1]]
        sf.write(str(path), piece, sr)
        t0, dur = cut[j] / sr, len(piece) / sr
        mine = [Word(w.text, w.start - t0, w.end - t0) for w in heard if 0 <= (w.start + w.end) / 2 - t0 < dur]
        ws = tts._map_words(seg["text"], mine) if mine else []
        if not ws:   # nothing heard on this screen: spread its caption words over the clip
            toks = seg["text"].split()
            ws = [Word(t, dur * k / len(toks), dur * (k + 1) / len(toks)) for k, t in enumerate(toks)]
        ws = [Word(w.text, min(max(0.0, w.start), dur), min(max(0.0, w.end), dur)) for w in ws]
        out.append(tts.TTSResult(path, ws, dur, res.match))
    return out


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
    egg, egg_q = motion.egg_parts(script.get("like_egg"))
    like = cfg.get("like_cta") or {}
    if egg in motion.EGGS and like.get("enabled", True) and egg in (like.get("eggs") or []):
        segments.append(motion.egg_segment(egg, egg_q))   # spoken "좋아요 누르면 좋아요가 … 변해요~" over its drawing

    wavs, results = [], []
    for run in voice_runs(segments):
        segs, i0 = [segments[i] for i in run], run[0]
        print(f"  voice {i0 + 1}/{len(segments)}: " + " / ".join(s["text"][:40] for s in segs))
        res = tts.synthesize(
            " ".join(s.get("say") or s["text"] for s in segs),
            work_dir / (f"seg_{i0:02d}.wav" if len(run) == 1 else f"run_{i0:02d}.wav"),
            engine=cfg["engine"], voice=cfg["voice"], instruct=voice_instruct(cfg.get("instruct", ""), run_tone(segs), cfg.get("instruct_persona", "")),
            speed=float(cfg.get("speed", 1.0)), display=" ".join(s["text"] for s in segs), seed=7 + i0,
            head_pad=HEAD_PAD, tail_pad=TAIL_PAD, takes=int(cfg.get("tts_takes", 1)))
        parts = [res] if len(run) == 1 else split_take(res, segs, [work_dir / f"seg_{i:02d}.wav" for i in run])
        for i, part in zip(run, parts):
            if i == run[-1] and (g := gap_after(i, segments)):   # no beat inside a joined take
                _pad(part.audio_path, g)
                part.duration = round(part.duration + g, 3)
            print(f"    {part.duration:.1f}s, match {part.match:.2f}")
            wavs.append(part.audio_path)
            results.append(part)
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
    found: dict = {}   # agency -> its photo, looked up once per video
    article_urls = list(dict.fromkeys(re.findall(r"https?://[^\s,)\]\"']+", " ".join(script.get("facts_used") or [])
                                                 + " " + (script.get("source_post") or ""))))
    for i, (vis, (st, en)) in enumerate(zip(visuals, times)):
        qs = (vis or {}).get("video") or []
        clip = None
        if (ph := (vis or {}).get("photo")):   # the real photo an agency released beats any stock footage
            key = ph.get("who", "")
            if key not in found:
                found[key] = photo.find([ph["src"]] if ph.get("src") else article_urls, key)
            if found[key]:
                clip = photo.frames(found[key], en - st + motion.LEAD + 0.2, work_dir / f"photo_{i:02d}", motion.FPS)
            else:
                print(f"    photo: no photo credited to {key!r} - scene keeps its own picture")
            if clip:
                clips.append(clip)
                continue
        # a free stock still of the real place/object (stillphoto.py) - the @짧은주녑 look without their copying
        if (pq := (vis or {}).get("pic")) and (clip := stillphoto.frames(pq, en - st + motion.LEAD + 0.2,
                                                                         work_dir / f"still_{i:02d}", motion.FPS, used_clips)):
            clips.append(clip)
            continue
        # CC BY YouTube footage of the real place/thing (ccvideo.py), credited on screen; `video` is the fallback
        cq = (vis or {}).get("cc") or []
        for k, q in enumerate([cq] if isinstance(cq, str) else cq):
            if (clip := ccvideo.clip_frames(q, en - st + motion.LEAD + 0.2, work_dir / f"cc_{i:02d}_{k}",
                                            motion.FPS, used_clips)):
                break
        if clip:
            clips.append(clip)
            continue
        for k, q in enumerate([qs] if isinstance(qs, str) else qs):   # candidates in order, like illust q lists
            if (clip := stock.clip_frames(q, en - st + motion.LEAD + 0.2, work_dir / f"clip_{i:02d}_{k}",
                                          motion.FPS, used_clips)):
                break
        clips.append(clip)
    print(f"  stock clips: {sum(1 for c in clips if c)}/{sum(1 for v in visuals if (v or {}).get('video') or (v or {}).get('pic'))}")
    html, cuts = motion.build(segments, visuals, times, cues, script["title_lines"], script.get("credit", ""),
                              picker, repo / "assets" / "fonts" / "BlackHanSans-Regular.ttf", clips,
                              episode=script.get("episode"))
    page = work_dir / "motion.html"
    page.write_text(html, encoding="utf-8")
    print(f"  frames: {int(total * motion.FPS)} ({len(picker.used)} illustrations)")
    qa: dict = {}
    video = motion.capture(page, work_dir / "video.mp4", total, qa)
    # 2026-10-22 (사용자: "줄바꿈하거나 짤리는 부분 검수 제대로"): the page measures every caption and word box
    # at each caption and before each cut - cut/covered/overflowing words are layout_issues (run.py keeps such a
    # video off the public schedule); captions still broken at a bad point are listed as caption_breaks.
    issues = motion.qa_summary(qa.get("issues", []))
    breaks = motion.bad_breaks(cues, words)
    motion.qa_sheet(qa.get("frames", []), out_path.parent / "qa_sheet.jpg")
    for x in issues:
        print(f"  ::warning::화면 검수 {x['t']}s {x['kind']}: '{x['text']}' - {x['msg']}")
    for b in breaks:
        print(f"  자막 끊김 주의: {b}")
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
    return {"stock_clips": [c["url"] for c in clips if c],
            "cc_clips": [{"url": c["url"], "by": c["by"], "license": c["license"]} for c in clips if c and c.get("license")], "duration": round(cursor, 2), "matches": [round(r.match, 2) for r in results],
            "sfx": len(sfx), "illustrations": len(picker.used), "cuts": len(cuts) + 1,
            "layout_issues": issues, "caption_breaks": breaks}
