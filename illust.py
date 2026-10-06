"""Illustrations from いらすとや (irasutoya.com) - the flat cartoon people and
props the reference channel builds its scenes from.

    python illust.py タクシー 乗車拒否        # prints the best match and saves it

License (irasutoya.com/p/terms.html): free, no credit needed, commercial use
up to 20 illustrations per production - fetch() refuses a 21st. Images are
transparent PNGs, fetched at 800px and cached under cache/illust/.
"""
import gzip
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
CACHE = REPO / "cache" / "illust"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
LIMIT = 20


def _get(url: str, timeout: int = 20) -> bytes:
    """The site answers bursts with 503/429 - back off and retry, and pace every request."""
    import time
    import urllib.error
    for attempt in range(4):
        time.sleep(0.6 if attempt == 0 else 3 * attempt)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
    raise RuntimeError("unreachable")


INDEX = REPO / "assets" / "irasutoya.json.gz"   # built by illust_index.py
_INDEX: list | None = None


def _index() -> list:
    global _INDEX
    if _INDEX is None:
        _INDEX = json.loads(gzip.decompress(INDEX.read_bytes())) if INDEX.exists() else []
    return _INDEX


def search(query: str) -> list[tuple[str, str]]:
    """(title, image url): every drawing whose title has the query's main word, from the
    local index - the site's search page answers 429 to GitHub's runners. Without the
    index, the first page of the site's own search, in site order."""
    if (idx := _index()):
        head = _stem(query.split()[0]) if query.split() else ""
        return [(t, re.sub(r"/s\d+(-c)?/", "/s800/", u)) for t, u in idx if head and head in t]
    h = _get("https://www.irasutoya.com/search?q=" + urllib.parse.quote(query)).decode("utf-8", "replace")
    out = []
    for src, title in re.findall(r'bp_thumbnail_resize\("([^"]+)","([^"]*)"\)', h):
        out.append((html.unescape(title), re.sub(r"/s\d+(-c)?/", "/s800/", src)))
    return out


KANJI = re.compile(r"^[一-鿿々]+")
# Sheets of several faces/poses read as clutter in a single panel slot.
SHEET = re.compile(r"いろいろな|色々な|表情のイラスト「|ポーズのイラスト「|セット|まとめ|一覧|段階|アイコン")
# Drawings with readable Japanese on them (謝罪文 showed up for 謝罪) - viewers see foreign text.
TEXTY = re.compile(r"文のイラスト|謝罪文|文章|文字|新聞|看板|ポスター|張り紙|貼り紙|手紙|メッセージ|お知らせ|標識|カード|メモ|書き初め|習字|円|将来")


ICHIDAN = set("えけせてねへめれげぜでべぺいきしちにひみりぎじびぴ")


def _stem(word: str) -> str:
    """泣く/泣いている -> 泣, 壊れた -> 壊, 考える/考えている -> 考え, タクシー -> タクシー: titles conjugate verbs."""
    if len(word) >= 3 and word.endswith("る") and word[-2] in ICHIDAN:
        return word[:-1]   # ichidan verb: 考 alone also matches 考古学者
    m = KANJI.match(word)
    return m.group(0) if m else word


def _has(title: str, word: str) -> bool:
    """A verb cut to its kanji (泣く -> 泣) must go on in kana in the title:
    泣いている yes, 書く -> 書類 / 走る -> 走者 no."""
    stem = _stem(word)
    if stem == word or not KANJI.fullmatch(stem):
        return stem in title
    return re.search(re.escape(stem) + r"(?![一-鿿々のとやでをがはも・])", title) is not None   # 司書の for 書く: no


def _score(title: str, words: list[str]) -> float | None:
    """None = not good enough: better no picture than a wrong one (除雪車 for 車 トランク).
    One or two words must all appear in the title (verb stems), three or more need two.
    Generic titles win: short ones ("タクシーのイラスト" beats "タクシーに乗る人のイラスト（女性）"),
    the word up front ("カメラマンのイラスト（男性）" beats "水中カメラマンのイラスト")."""
    words = [w for w in words if w]
    if not words or not _has(title, words[0]):
        return None
    hit = sum(1 for w in words if _has(title, w))
    stems = words
    if hit < (len(stems) if len(stems) <= 2 else 2):
        return None
    if SHEET.search(title):   # several faces/poses in one image - clutter in a panel slot
        return None
    if TEXTY.search(title):   # Japanese lettering in the drawing
        return None
    group = "たち" in title and not any(w in ("たち", "人々", "群衆", "大勢") for w in words)
    main = re.sub(r"（[^）]*）|「[^」]*」", "", title)   # 泣いている女性のイラスト beats 泣き寝入りのイラスト（女性）
    head = _stem(words[0])
    lead = max(0, main.find(head))   # 水中カメラマン: a modifier before the word = a special case
    owned = re.search(re.escape(head) + "の(?!イラスト)", main) is not None   # 裁判官のバッジ, お金のキャラクター
    return (hit + 0.5 * sum(1 for w in words if _has(main, w)) - (1.5 if group else 0) - (0.3 if owned else 0)
            - len(main) / 200 - lead / 40)


_OCR = None
FOREIGN = re.compile(r"[぀-ヿ㐀-鿿¥￥]")   # kana + CJK ideographs + yen sign (reads as Japanese money)


def has_foreign_text(path: Path) -> bool:
    """True when the drawing has readable Japanese/Chinese lettering on it (謝罪文 paper,
    ポテト snack bag, 学級新聞): viewers read it as foreign clutter. RapidOCR on a white
    backdrop; a hit needs confidence >= 0.8 - hatching and faces score 0.5-0.76.
    Without rapidocr installed the check is skipped (title filter TEXTY still applies)."""
    global _OCR
    if _OCR is False:
        return False
    try:
        if _OCR is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        from PIL import Image
        import numpy as np
        with Image.open(path) as im:
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.getchannel("A"))
        res, _ = _OCR(np.array(bg)[:, :, ::-1])
    except Exception as ex:
        print(f"    illust: text check unavailable ({ex.__class__.__name__}) - skipped")
        _OCR = False if isinstance(ex, ImportError) else _OCR
        return False
    return any(FOREIGN.search(t) and score >= 0.8 for _, t, score in (res or []))


def _trim(path: Path, pad: int = 6) -> None:
    """Cut the transparent margin off the 800x800 canvas so the layout sees
    the drawing's real shape (a wide court bench, a tall standing person)."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGBA")
        box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if not box:
            return
        l, t, r, b = box
        im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad))).save(path)


class Picker:
    """One per video: tracks the 20-illustration licence limit."""

    def __init__(self):
        self.used: dict[str, Path] = {}
        self.urls: set[str] = set()   # pictures already on screen: another query must not land on the same drawing

    def fetch(self, query) -> Path | None:
        """query: "泣く 男性" or alternatives ["泣く 男性", "号泣 男性", "泣く 人"], tried in order."""
        if isinstance(query, (list, tuple)):
            for q in query:
                if (path := self.fetch(q)):
                    return path
            return None
        query = (query or "").strip()
        if not query:
            return None
        if query in self.used:
            return self.used[query]
        if len(self.used) >= LIMIT:
            print(f"    illust: {LIMIT}-image licence limit reached, skipping {query!r}")
            return None
        CACHE.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(query.encode()).hexdigest()[:16]
        path = CACHE / f"{key}.png"
        meta = CACHE / f"{key}.url"
        if path.exists() and not meta.exists():
            path.unlink()   # no .url = the pick never passed the lettering check (crashed mid-way) - choose again
        if path.exists() and meta.exists() and meta.read_text(encoding="utf-8") in self.urls:
            path.unlink()   # cached pick is a drawing this video already shows - choose again
        if not path.exists():
            words = query.split()
            try:
                results = search(query)
                if len(words) > 1 and not _index():   # the site's search is strict - widen with the main noun alone
                    results += search(words[0])
            except Exception as ex:
                print(f"    illust: search failed for {query!r}: {ex}")
                return None
            scored = [(s, t, u) for t, u in results if (s := _score(t, words)) is not None]
            if not scored:
                print(f"    illust: nothing titled with {words[0]!r} for {query!r} - fallback")
                return None
            fresh = [r for r in scored if r[2] not in self.urls]   # prefer a drawing not yet used in this video
            ranked = sorted(fresh, key=lambda r: -r[0]) + sorted([r for r in scored if r not in fresh], key=lambda r: -r[0])
            for _, title, url in ranked[:4]:
                data, last = None, None
                # some images 404 at s800 from some hosts - step down through sizes
                for size in ("s800", "s640", "s400", "s320"):
                    try:
                        data = _get(re.sub(r"/s\d+(-c)?/", f"/{size}/", url), timeout=30)
                        break
                    except Exception as ex:
                        last = ex
                if not data:
                    print(f"    illust: download failed {url[-60:]}: {last}")
                    continue
                path.write_bytes(data)
                if has_foreign_text(path):
                    path.unlink()   # before the print: a console that can't show the title must not leave it cached
                    print(f"    illust: {title} has Japanese/Chinese lettering - next candidate")
                    continue
                meta.write_text(url, encoding="utf-8")
                _trim(path)
                print(f"    illust: {query!r} -> {title}")
                break
            if not path.exists():
                return None
        self.used[query] = path
        if meta.exists():
            self.urls.add(meta.read_text(encoding="utf-8"))
        return path


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "タクシー"
    for t, u in search(q)[:8]:
        print(t, u[-50:])
    print(Picker().fetch(q))
