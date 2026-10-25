"""Official photos: the real picture of the event, when a public agency released it.

2026-10-24 (사용자: "썰가챠에 가장 큰 문제가 실사 사진이 없다는 거임"): a photo a police station, fire
service, coast guard or city hall took in the course of its work and released ("사진=○○경찰서 제공") is
a public work - 저작권법 제24조의2 lets anyone reuse it without permission. Community and readers'
photos are not, so they are never taken (사용자가 커뮤니티 사진도 원했지만 저작권·초상권 때문에 제외).

The script names the agency on the scene that should show it: "visual": {"photo": {"who": "부산해양경찰서"}}
(optional "src": the article to look in; otherwise every URL in facts_used / source_post is tried).
The article's images are read with the text right after them (the caption), and an image is used only when
that caption says it was provided by an agency ("제공") and nothing in it points to a reader, a community
post or social media. The photo then becomes the scene's background like stock footage, slowly zooming,
tagged "사진=<agency> 제공" instead of '자료화면' - the tag is the credit, and there is no link anywhere.
"""
import html as _html
import re
import subprocess
import urllib.request
from pathlib import Path

PANEL = (1080, 960)
CACHE = Path.home() / ".cache" / "issue-shorts" / "photos"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
# Only the state and local government (24조의2 ①): the provider's name has to end like one of these.
# Companies, public corporations (공사·공단 need a 공공누리 mark, 24조의2 ②), people and the press do not.
AGENCY = re.compile(r"[가-힣]{0,10}(?:경찰서|경찰청|지구대|파출소|경찰|소방서|소방재난본부|소방본부|소방청|소방|해경|"
                    r"해양경찰서|해양경찰청|시청|구청|군청|도청|교육청|청|부|육군|해군|공군|해병대|사단)|"
                    r"[가-힣]{1,5}(?:시|군|구|도)")
NOT_OFFICIAL = re.compile(r"(독자|제보|시청자|본인|가족|유족|지인|업체|회사|커뮤니티|온라인|SNS|에스엔에스|유튜브|틱톡|"
                          r"인스타|페이스북|트위터|블라인드|보배드림|디시|더쿠|에펨|게시판|캡처|갈무리|게티|AFP|로이터|"
                          r"편집부|공동취재|지도|맵)")
CREDIT = (re.compile(r"(?:사진|영상|자료)?\s*[=:]?\s*([가-힣A-Za-z0-9·]{2,12}(?:\s[가-힣A-Za-z0-9·]{1,12}){0,2})\s*제공(?![가-힣])"),
          re.compile(r"제공\s*[=:]\s*([가-힣A-Za-z0-9·]{2,12}(?:\s[가-힣A-Za-z0-9·]{1,12}){0,2})"))
MIN_W = 480


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": url})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _decode(raw: bytes) -> str:
    head = raw[:3000].decode("ascii", "ignore").lower()
    enc = "euc-kr" if re.search(r"charset=[\"']?(euc-kr|ks_c_5601)", head) else "utf-8"
    return raw.decode(enc, "replace")


def _text(fragment: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragment, flags=re.S | re.I)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def candidates(page: str, base: str) -> list[tuple[str, str]]:
    """(image url, caption text) for every picture in an article: the alt text plus the words that follow it."""
    out = []
    for m in re.finditer(r"<img\b[^>]*>", page, re.I):
        tag = m.group(0)
        src = re.search(r"\b(?:data-src|data-original|src)\s*=\s*[\"']([^\"']+)", tag, re.I)
        if not src or src.group(1).startswith("data:"):
            continue
        url = urllib.request.urljoin(base, _html.unescape(src.group(1)))
        alt = re.search(r"\balt\s*=\s*[\"']([^\"']*)", tag, re.I)
        caption = ((alt.group(1) if alt else "") + " " + _text(page[m.end():m.end() + 700])[:220]).strip()
        out.append((url, caption))
    return out


def provider(caption: str, who: str = "") -> str | None:
    """The agency an image credits, or None when it is not an agency's own photo."""
    if NOT_OFFICIAL.search(caption):
        return None
    for rx in CREDIT:
        for m in rx.finditer(caption):
            name = re.sub(r"^(사진|영상|자료)\s*", "", m.group(1).strip(" =:/"))
            last = name.split()[-1] if name.split() else ""   # "부산 해운대구" -> judged on "해운대구"
            if last and AGENCY.fullmatch(last) and (not who or _same(who, name)):
                return name
    return None


def _same(who: str, name: str) -> bool:
    a, b = re.sub(r"\s", "", who), re.sub(r"\s", "", name)
    return a in b or b in a or bool(set(re.findall(r"[가-힣]{2,}", a)) & set(re.findall(r"[가-힣]{2,}", b)))


def find(urls: list[str], who: str = "") -> dict | None:
    """First agency-credited photo in the articles: {url, who, path}."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for page_url in urls:
        try:
            page = _decode(_get(page_url))
        except Exception as ex:
            print(f"    photo: {page_url[:60]} unreadable ({ex})")
            continue
        for img, caption in candidates(page, page_url):
            name = provider(caption, who)
            if not name:
                continue
            dst = CACHE / (re.sub(r"[^A-Za-z0-9]", "_", img)[-90:] + ".img")
            try:
                if not dst.exists():
                    dst.write_bytes(_get(img))
                from PIL import Image
                with Image.open(dst) as im:
                    w, h = im.size
            except Exception:
                dst.unlink(missing_ok=True)
                continue
            if w < MIN_W or not 0.45 < w / h < 2.4:   # thumbnails, logos, banners
                continue
            print(f"    photo: {name} 제공 ({w}x{h}) from {page_url[:60]}")
            return {"url": img, "who": name, "path": str(dst)}
    return None


def frames(photo: dict, seconds: float, out_dir: Path, fps: int = 30, tag: str = "",
           strip_bottom: bool = True) -> dict | None:
    """The photo as a scene background: panel-filling frames with a slow push-in (same shape as stock.clip_frames).
    tag: the corner label (default "사진=<agency> 제공"); strip_bottom: cut the news site's logo strip."""
    w, h = PANEL
    n = max(1, int(round((seconds + 0.3) * fps)))
    out_dir.mkdir(parents=True, exist_ok=True)
    # the bottom strip goes first: news sites stamp their logo there (뉴스1 bottom-right) - the photo is the
    # agency's, the logo is not
    vf = (("crop=iw:ih*0.86:0:0," if strip_bottom else "") + f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='min(1+0.0009*on,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps={fps}")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", photo["path"], "-vf", vf, "-frames:v", str(n),
                        "-q:v", "3", str(out_dir / "f_%04d.jpg")], check=True)
    except Exception as ex:
        print(f"    photo: frames failed: {ex}")
        return None
    got = len(list(out_dir.glob("f_*.jpg")))
    return {"dir": str(out_dir), "n": got, "url": photo["url"], "tag": tag or f"사진={photo['who']} 제공"} if got else None
