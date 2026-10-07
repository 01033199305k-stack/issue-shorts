"""Narration: Qwen3-TTS CustomVoice preset 'Sohee' with a delivery instruction.

Two backends render the same voice:
- "qwen": qwen-tts in-process. This is what GitHub Actions runs (CPU, ~5x
  realtime on 4 cores). Weights come from the Hugging Face cache.
- "voicebox": the Voicebox desktop app's local API, for previews on the PC.

Neither returns word timings, so faster-whisper measures them on the
rendered audio and the script's own words are laid onto that timeline.
The same transcript doubles as a pronunciation check: a take whose words
drift too far from the script (a swallowed ending, a slurred word) is
re-rolled with another seed.
"""
import difflib
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.util import ffprobe_duration, run, speech_bounds, to_wav

QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
VOICEBOX_URL = "http://127.0.0.1:17493"
MIN_MATCH = 0.78     # transcript-vs-script similarity below this = re-roll
MAX_TAKES = 3
# Qwen3-TTS often stops before the last syllable has died away (음/함/임 cut off).
# Give it a throwaway tail after a pause so the real sentence ends naturally,
# then cut inside that pause.
TAIL = " ... 네."
TTS_VERSION = "sent-v3"   # part of the take cache key: bump when generation changes


@dataclass
class Word:
    text: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class TTSResult:
    audio_path: Path
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0
    match: float = 1.0


_qwen = None
_whisper = None


def _qwen_model():
    global _qwen
    if _qwen is None:
        import torch
        from qwen_tts import Qwen3TTSModel
        cuda = torch.cuda.is_available()
        if not cuda:
            torch.set_num_threads(os.cpu_count() or 4)
        _qwen = Qwen3TTSModel.from_pretrained(
            QWEN_MODEL, device_map="cuda" if cuda else "cpu",
            dtype=torch.bfloat16 if cuda else torch.float32)
    return _qwen


def release_models() -> None:
    """Free the 7 GB of TTS weights before the memory-hungry render steps."""
    global _qwen
    _qwen = None
    import gc
    gc.collect()


def _whisper_model():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper


def _load16k(path: Path):
    """16 kHz mono float32 via ffmpeg. faster-whisper's own decoder goes
    through PyAV, whose releases break its open() signature from time to time."""
    import subprocess

    import numpy as np
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def _gen_qwen(text: str, speaker: str, instruct: str, seed: int, out: Path) -> None:
    import soundfile as sf
    import torch
    torch.manual_seed(seed)
    wavs, sr = _qwen_model().generate_custom_voice(
        text=text, speaker=speaker, language="Korean", instruct=instruct or None)
    sf.write(str(out), wavs[0], sr)


def _gen_voicebox(text: str, profile_id: str, instruct: str, seed: int, out: Path) -> None:
    body = {"profile_id": profile_id, "text": text, "language": "ko", "seed": seed,
            "engine": "qwen_custom_voice"}
    if instruct:
        body["instruct"] = instruct
    req = urllib.request.Request(f"{VOICEBOX_URL}/generate", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    gid = json.load(urllib.request.urlopen(req, timeout=60))["id"]
    deadline = time.time() + 600
    while True:
        h = json.load(urllib.request.urlopen(f"{VOICEBOX_URL}/history/{gid}", timeout=60))
        if h.get("status") == "completed":
            break
        if h.get("status") in ("failed", "error") or time.time() > deadline:
            raise RuntimeError(f"voicebox {gid}: {h.get('status')} {h.get('error')}")
        time.sleep(1)
    out.write_bytes(urllib.request.urlopen(f"{VOICEBOX_URL}/audio/{gid}", timeout=60).read())


def _map_words(display: str, heard: list[Word]) -> list[Word]:
    """Lay the script's words onto the timeline whisper heard, by position:
    whisper's spelling drifts (삼백만 -> 300만) and its word split can differ,
    so each script word takes the span of whisper's characters at the same
    fraction of the sentence. Pauses whisper heard stay where they are."""
    chars: list[tuple[float, float]] = []
    for w in heard:
        n = max(1, len(w.text.strip()))
        step = (w.end - w.start) / n
        chars += [(w.start + k * step, w.start + (k + 1) * step) for k in range(n)]
    tokens = display.split()
    total = sum(len(t) for t in tokens)
    if not chars or not total:
        return []
    out, pos = [], 0
    for t in tokens:
        a = int(pos / total * len(chars))
        b = max(a, int((pos + len(t)) / total * len(chars)) - 1)
        out.append(Word(t, chars[a][0], chars[min(b, len(chars) - 1)][1]))
        pos += len(t)
    return out


def _cut_tail(path: Path) -> float | None:
    """Start of the pause before the throwaway tail: the last silence (>=80 ms at
    -42 dB) that ends inside the final second, i.e. right before "네"."""
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        "silencedetect=n=-42dB:d=0.08", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    dur = ffprobe_duration(path)
    gaps, start = [], None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].split()[0])
        elif "silence_end:" in line and start is not None:
            gaps.append((start, float(line.split("silence_end:")[1].split("|")[0])))
            start = None
    gaps = [g for g in gaps if g[0] > 0.4 and dur - 1.0 <= g[1] <= dur - 0.12]
    return gaps[-1][0] + 0.06 if gaps else None


def _trim_tail(src: Path, dst: Path, cut: float | None) -> None:
    """Keep audio up to `cut` with a 40 ms fade-out (no click), plus 0.1 s of room."""
    from pipeline.util import run as _run
    end = f"atrim=0:{cut:.3f}," if cut else ""
    fade_at = max(0.0, (cut or ffprobe_duration(src)) - 0.04)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af",
          f"{end}afade=t=out:st={fade_at:.3f}:d=0.04,apad=pad_dur=0.1", str(dst)])


def _squeeze_pauses(path: Path, keep: float = 0.1, longer_than: float = 0.15) -> None:
    """Shorten every pause inside the sentence to `keep` seconds, in place.

    Qwen3-TTS stops for 0.4-0.7 s mid-sentence ("근데 ... 데려간 이유가"), most of
    all on tones like 비밀 털어놓듯 / 뜸 들이며. @dolongcha and @군림보 never pause
    longer than ~0.2 s, so ours sounded chopped into odd phrases (2026-10-07).
    """
    import numpy as np
    import soundfile as sf
    a, sr = sf.read(str(path), dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    hop = int(sr * 0.01)
    n = len(a) // hop
    if n < 10:
        return
    db = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    quiet = db < max(np.percentile(db, 90) - 30, -55)
    voiced = np.flatnonzero(~quiet)
    if len(voiced) < 2:
        return
    first, last = voiced[0], voiced[-1]   # lead-in / tail are trimmed elsewhere
    pieces, pos, i = [], 0, first
    while i <= last:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j <= last and quiet[j]:
            j += 1
        if (j - i) * 0.01 > longer_than:
            half = int(keep / 2 * sr)
            s, e = i * hop, j * hop
            pieces.append(a[pos:s + half])
            pos = e - half
        i = j
    if not pieces:
        return
    pieces.append(a[pos:])
    sf.write(str(path), np.concatenate(pieces), sr)


CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def _norm(s: str) -> str:
    """Compare by sound, not spelling: whisper writes what it hears, and Korean
    liaison makes "한 말이 더 가관임" sound like "한 마리 더 가과님". Split syllables
    into jamo and drop the silent initial ㅇ, and the two become identical."""
    out = []
    for ch in re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower():
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            c, j, t = code // 588, (code % 588) // 28, code % 28
            out.append(("" if CHO[c] == "ㅇ" else CHO[c]) + JUNG[j] + JONG[t].strip())
        else:
            out.append(ch)
    return "".join(out)


def _similarity(heard: str, *scripts: str) -> float:
    h = _norm(heard)
    return max(difflib.SequenceMatcher(None, h, _norm(s)).ratio() for s in scripts if s)


def synthesize(
    text: str,
    out_wav: Path,
    *,
    engine: str,
    voice: str,
    instruct: str = "",
    speed: float = 1.0,
    display: str | None = None,
    seed: int = 7,
    head_pad: float = 0.05,
    tail_pad: float = 0.12,
) -> TTSResult:
    """Render one segment, trimmed of dead air, with word timings.

    text is what the voice reads (numbers spelled out); display is what the
    captions show. Takes that mishear the script get re-rolled up to
    MAX_TAKES times and the closest one is kept.
    """
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    display = display or text
    gen = _gen_qwen if engine == "qwen" else _gen_voicebox

    # Same sentence, same voice settings -> reuse the take (re-renders and retries skip TTS)
    import hashlib
    import shutil
    key = hashlib.sha1(json.dumps([TTS_VERSION, engine, voice, instruct, speed, seed, text, display],
                                  ensure_ascii=False).encode()).hexdigest()[:20]
    cdir = Path(__file__).resolve().parent.parent / "cache" / "tts"
    if (cdir / f"{key}.json").exists() and (cdir / f"{key}.wav").exists():
        meta = json.loads((cdir / f"{key}.json").read_text(encoding="utf-8"))
        shutil.copyfile(cdir / f"{key}.wav", out_wav)
        return TTSResult(out_wav, [Word(*w) for w in meta["words"]], meta["duration"], meta["match"])
    res = _synthesize_fresh(text, out_wav, gen=gen, voice=voice, instruct=instruct, speed=speed,
                            display=display, seed=seed, head_pad=head_pad, tail_pad=tail_pad)
    cdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_wav, cdir / f"{key}.wav")
    (cdir / f"{key}.json").write_text(json.dumps(
        {"words": [[w.text, w.start, w.end] for w in res.words], "duration": res.duration, "match": res.match},
        ensure_ascii=False), encoding="utf-8")
    return res


def _synthesize_fresh(text, out_wav, *, gen, voice, instruct, speed, display, seed, head_pad, tail_pad) -> TTSResult:

    best = None
    for take in range(MAX_TAKES):
        raw = out_wav.with_suffix(f".take{take}.wav")
        full = out_wav.with_suffix(f".take{take}.full.wav")
        sped = out_wav.with_suffix(f".take{take}.sped.wav")
        gen(text + TAIL, voice, instruct, seed + take * 101, raw)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-af", f"atempo={speed:.3f}", "-ar", "24000", "-ac", "1", str(full)])
        raw.unlink(missing_ok=True)
        _trim_tail(full, sped, _cut_tail(full))
        full.unlink(missing_ok=True)
        _squeeze_pauses(sped)
        segs, _ = _whisper_model().transcribe(_load16k(sped), language="ko", word_timestamps=True)
        heard = [Word(w.word.strip(), w.start, w.end)
                 for s in segs for w in (s.words or []) if w.word.strip()]
        match = _similarity(" ".join(w.text for w in heard), text, display)
        if best is None or match > best[0]:
            if best:
                best[1].unlink(missing_ok=True)
            best = (match, sped, heard)
        else:
            sped.unlink(missing_ok=True)
        if match >= MIN_MATCH:
            break
        print(f"    take {take + 1}: match {match:.2f} < {MIN_MATCH} - re-rolling")

    match, sped, heard = best
    words = _map_words(display, heard)
    if not words:
        to_wav(sped, out_wav)
        sped.unlink(missing_ok=True)
        return TTSResult(out_wav, [], ffprobe_duration(out_wav), match)

    raw_duration = ffprobe_duration(sped)
    audio_start, audio_end = speech_bounds(sped)
    start = max(0.0, min(audio_start, words[0].start) - head_pad)
    end = min(raw_duration, audio_end + tail_pad)
    to_wav(sped, out_wav, start=start, end=end)
    sped.unlink(missing_ok=True)
    duration = ffprobe_duration(out_wav)
    # Keep every word inside the trimmed clip: a cue that outlives its clip
    # overlaps the next segment's first cue and the two render garbled.
    shifted = [Word(w.text, min(max(0.0, w.start - start), duration),
                    min(max(0.0, w.end - start), duration)) for w in words]
    return TTSResult(out_wav, shifted, duration, match)
