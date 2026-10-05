"""Illustrations from いらすとや (irasutoya.com) - the flat cartoon people and
props the reference channel builds its scenes from.

    python illust.py タクシー 乗車拒否        # prints the best match and saves it

License (irasutoya.com/p/terms.html): free, no credit needed, commercial use
up to 20 illustrations per production - fetch() refuses a 21st. Images are
transparent PNGs, fetched at 800px and cached under cache/illust/.
"""
import hashlib
import html
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


def search(query: str) -> list[tuple[str, str]]:
    """(title, image url) for the first page of results, in site order."""
    h = _get("https://www.irasutoya.com/search?q=" + urllib.parse.quote(query)).decode("utf-8", "replace")
    out = []
    for src, title in re.findall(r'bp_thumbnail_resize\("([^"]+)","([^"]*)"\)', h):
        out.append((html.unescape(title), re.sub(r"/s\d+(-c)?/", "/s800/", src)))
    return out


KANJI = re.compile(r"^[一-鿿々]+")
# Sheets of several faces/poses read as clutter in a single panel slot.
SHEET = re.compile(r"いろいろな|色々な|表情のイラスト「|ポーズのイラスト「|セット|まとめ|一覧|段階|アイコン")
# Drawings with readable Japanese on them (謝罪文 showed up for 謝罪) - viewers see foreign text.
TEXTY = re.compile(r"文のイラスト|謝罪文|文章|文字|新聞|看板|ポスター|張り紙|貼り紙|手紙|メッセージ|お知らせ|標識|カード|メモ|書き初め|習字")


def _stem(word: str) -> str:
    """泣く/泣いている -> 泣, 壊れた -> 壊, タクシー -> タクシー: titles conjugate verbs."""
    m = KANJI.match(word)
    return m.group(0) if m else word


def _score(title: str, words: list[str]) -> float | None:
    """None = not good enough: better no picture than a wrong one (除雪車 for 車 トランク).
    One or two words must all appear in the title (verb stems), three or more need two.
    Shorter titles are more generic ("タクシーのイラスト" beats "タクシーに乗る人のイラスト（女性）")."""
    stems = [_stem(w) for w in words if w]
    if not stems or stems[0] not in title:
        return None
    hit = sum(1 for s in stems if s in title)
    if hit < (len(stems) if len(stems) <= 2 else 2):
        return None
    if SHEET.search(title):   # several faces/poses in one image - clutter in a panel slot
        return None
    if TEXTY.search(title):   # Japanese lettering in the drawing
        return None
    group = "たち" in title and not any(w in ("たち", "人々", "群衆", "大勢") for w in words)
    return hit - (1.5 if group else 0) - len(title) / 200


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
        if path.exists() and meta.exists() and meta.read_text(encoding="utf-8") in self.urls:
            path.unlink()   # cached pick is a drawing this video already shows - choose again
        if not path.exists():
            words = query.split()
            try:
                results = search(query)
                if len(words) > 1:   # the site's search is strict - widen with the main noun alone
                    results += search(words[0])
            except Exception as ex:
                print(f"    illust: search failed for {query!r}: {ex}")
                return None
            scored = [(s, t, u) for t, u in results if (s := _score(t, words)) is not None]
            if not scored:
                print(f"    illust: nothing titled with {words[0]!r} for {query!r} - fallback")
                return None
            fresh = [r for r in scored if r[2] not in self.urls]   # prefer a drawing not yet used in this video
            _, title, url = max(fresh or scored, key=lambda r: r[0])
            data = None
            # some images 404 at s800 from some hosts - step down through sizes
            for size in ("s800", "s640", "s400", "s320"):
                try:
                    data = _get(re.sub(r"/s\d+(-c)?/", f"/{size}/", url), timeout=30)
                    break
                except Exception as ex:
                    last = ex
            if not data:
                print(f"    illust: download failed {url[-60:]}: {last}")
                return None
            path.write_bytes(data)
            meta.write_text(url, encoding="utf-8")
            _trim(path)
            print(f"    illust: {query!r} -> {title}")
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
