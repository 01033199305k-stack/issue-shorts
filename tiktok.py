"""TikTok cross-post through Buffer (the same free Buffer account 지금세계 uses).

TikTok's own Content Posting API keeps unaudited apps on 'only me' and its guidelines
forbid fully automated posting, so the audit never passes a bot like this. Buffer is an
audited app: a createPost with a video URL goes up public. (news-factory/post.py, first
post 2026-10-01.)

Buffer pulls the video from a URL, so the mp4 is attached to a GitHub release of this
public repo (tag tt-<slug>) and the release is deleted after a few days.

Env: BUFFER_API_KEY (secret, shared with news-factory), BUFFER_TIKTOK_CHANNEL_ID (the
썰가챠 TikTok channel in Buffer - required: the account also holds 지금세계's TikTok),
GITHUB_TOKEN + GITHUB_REPOSITORY (Actions). Missing any -> skipped, YouTube is unaffected.
"""
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "issue-shorts/1.0 (+https://github.com/01033199305k-stack/issue-shorts)"   # Cloudflare blocks python's default
KEEP_DAYS = 3
CREATE = """mutation($input: CreatePostInput!) { createPost(input: $input) {
    __typename ... on PostActionSuccess { post { id status } } ... on MutationError { message } } }"""


def ready() -> str:
    """'' when everything is set, else why TikTok is skipped."""
    miss = [k for k in ("BUFFER_API_KEY", "BUFFER_TIKTOK_CHANNEL_ID", "GITHUB_TOKEN", "GITHUB_REPOSITORY")
            if not os.environ.get(k)]
    return ("설정 없음: " + ", ".join(miss)) if miss else ""


def _gh(method: str, url: str, data: bytes | None = None, ctype: str = "application/json"):
    if not url.startswith("http"):
        url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{url}"
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json",
        "Content-Type": ctype, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"github {method} {url[-60:]} -> {ex.code} {ex.read()[:200]!r}")


def host_video(video: Path, slug: str) -> str:
    """Attach the mp4 to a fresh release and return its public download URL."""
    tag = "tt-" + re.sub(r"[^A-Za-z0-9_.-]", "-", slug)[:90]
    try:   # a retry of the same slot: replace the old release
        old = _gh("GET", f"/releases/tags/{tag}")
        _gh("DELETE", f"/releases/{old['id']}")
        _gh("DELETE", f"/git/refs/tags/{tag}")
    except RuntimeError:
        pass
    rel = _gh("POST", "/releases", json.dumps({
        "tag_name": tag, "name": tag, "body": "TikTok 게시용 임시 파일 (며칠 뒤 자동 삭제)",
        "prerelease": True}).encode())
    up = rel["upload_url"].split("{")[0] + "?name=" + urllib.parse.quote(video.name)
    asset = _gh("POST", up, video.read_bytes(), "video/mp4")
    return asset["browser_download_url"]


def cleanup() -> None:
    """Delete tt-* releases older than KEEP_DAYS (Buffer has long since pulled them)."""
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    for rel in _gh("GET", "/releases?per_page=100") or []:
        made = dt.datetime.fromisoformat(rel["created_at"].replace("Z", "+00:00"))
        if rel["tag_name"].startswith("tt-") and made < cut:
            _gh("DELETE", f"/releases/{rel['id']}")
            try:
                _gh("DELETE", f"/git/refs/tags/{rel['tag_name']}")
            except RuntimeError:
                pass


def caption(title: str, tags: list[str]) -> str:
    title = re.sub(r"\s*#shorts\b", "", title, flags=re.I).strip()
    tags = list(dict.fromkeys(re.sub(r"[\s#·]", "", t) for t in ["썰", *tags] if t.strip()))[:5]  # TikTok takes 5
    return (f"{title}\n\n※ AI 음성으로 제작했습니다.\n" + " ".join("#" + t for t in tags if t))[:2200]


def post(video: Path, slug: str, title: str, tags: list[str], publish_at: dt.datetime | None) -> dict:
    """Schedule the TikTok post for publish_at (the YouTube slot time); now if that has passed."""
    url = host_video(video, slug)
    inp = {"channelId": os.environ["BUFFER_TIKTOK_CHANNEL_ID"], "text": caption(title, tags),
           "schedulingType": "automatic", "source": "issue-shorts",
           "assets": [{"video": {"url": url, "metadata": {"thumbnailOffset": 1500}}}],
           "metadata": {"tiktok": {"isAiGenerated": os.environ.get("TIKTOK_AI_LABEL", "") == "1"}}}
    now = dt.datetime.now(dt.timezone.utc)
    if publish_at and publish_at.astimezone(dt.timezone.utc) > now + dt.timedelta(minutes=5):
        inp.update(mode="customScheduled",
                   dueAt=publish_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    else:
        inp["mode"] = "shareNow"
    req = urllib.request.Request("https://api.buffer.com", method="POST",
                                 data=json.dumps({"query": CREATE, "variables": {"input": inp}}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA,
                                          "Authorization": "Bearer " + os.environ["BUFFER_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as ex:   # body only - never the key
        raise RuntimeError(f"buffer -> {ex.code}: {ex.read().decode(errors='replace')[:300]}")
    if body.get("errors"):
        raise RuntimeError("buffer: " + "; ".join(e.get("message", "") for e in body["errors"])[:300])
    res = body["data"]["createPost"]
    if res.get("__typename") != "PostActionSuccess":
        raise RuntimeError("createPost: " + (res.get("message") or str(res))[:300])
    return {"buffer_id": res["post"]["id"], "status": res["post"]["status"], "mode": inp["mode"],
            "due": inp.get("dueAt", "now"), "video_url": url}
