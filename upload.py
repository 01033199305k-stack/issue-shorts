"""YouTube Data API v3 upload with scheduled publishing.

The video goes up as private with status.publishAt, and YouTube flips it to
public at that minute - so the slot time holds even when the GitHub runner
starts late, and the hours in between are the review window (YouTube Studio
app -> delete anything wrong). If the slot time has already passed, it goes
up public straight away.

Auth: YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN.
This channel uses its own Google Cloud project: the news-factory project's
~6 uploads/day quota is already spent by 지금세계.
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class QuotaExceeded(RuntimeError):
    pass


def access_token() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as ex:
        raise RuntimeError("token refresh -> %d %s" % (ex.code, ex.read()[:200]))


def upload(video_path: str, title: str, description: str, tags: list[str],
           publish_at: dt.datetime | None, private_only: bool = False) -> dict:
    """publish_at: aware datetime; None or past -> public now.
    private_only: park it as private with no schedule (the slot was missed by
    hours - the operator decides in YouTube Studio)."""
    now = dt.datetime.now(dt.timezone.utc)
    status = {"selfDeclaredMadeForKids": False}
    if private_only:
        status["privacyStatus"] = "private"
    elif publish_at and publish_at > now + dt.timedelta(minutes=2):   # 긴급 대본은 3분 뒤 예약
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        status["privacyStatus"] = "public"
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": tags[:15], "categoryId": "24",          # 엔터테인먼트
                    "defaultLanguage": "ko", "defaultAudioLanguage": "ko"},
        "status": status,
    }
    with open(video_path, "rb") as fp:
        video = fp.read()
    auth = {"Authorization": "Bearer " + access_token()}
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            data=json.dumps(meta).encode(), method="POST", headers=dict(auth, **{
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(len(video))}))
        with urllib.request.urlopen(req, timeout=60) as r:
            loc = r.headers["Location"]
        req = urllib.request.Request(loc, data=video, method="PUT",
                                     headers=dict(auth, **{"Content-Type": "video/mp4"}))
        with urllib.request.urlopen(req, timeout=900) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as ex:
        body = ex.read().decode(errors="replace")
        if "quotaExceeded" in body or "uploadLimitExceeded" in body:
            raise QuotaExceeded(body[:300])
        try:
            body = json.loads(body)["error"]["message"]
        except (ValueError, KeyError):
            body = body[:300]
        raise RuntimeError("upload -> %d: %s" % (ex.code, body))
    vid = res["id"]
    return {"id": vid, "url": "https://youtube.com/shorts/" + vid,
            "privacy": res.get("status", {}).get("privacyStatus"),
            "publish_at": res.get("status", {}).get("publishAt")}
