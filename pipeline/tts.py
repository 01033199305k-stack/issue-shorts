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


def _norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower()


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

    best = None
    for take in range(MAX_TAKES):
        raw = out_wav.with_suffix(f".take{take}.wav")
        sped = out_wav.with_suffix(f".take{take}.sped.wav")
        gen(text, voice, instruct, seed + take * 101, raw)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-af", f"atempo={speed:.3f}", "-ar", "24000", "-ac", "1", str(sped)])
        raw.unlink(missing_ok=True)
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
