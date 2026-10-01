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
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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
    group = "たち" in title and not any(w in ("たち", "人々", "群衆", "大勢") for w in words)
    return hit - (1.5 if group else 0) - len(title) / 200


class Picker:
    """One per video: tracks the 20-illustration licence limit."""

    def __init__(self):
        self.used: dict[str, Path] = {}

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
            _, title, url = max(scored, key=lambda r: r[0])
            try:
                path.write_bytes(_get(url, timeout=30))
            except Exception as ex:
                print(f"    illust: download failed {url}: {ex}")
                return None
            print(f"    illust: {query!r} -> {title}")
        self.used[query] = path
        return path


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "タクシー"
    for t, u in search(q)[:8]:
        print(t, u[-50:])
    print(Picker().fetch(q))
