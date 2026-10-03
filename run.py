"""One slot, end to end: scrape -> research -> write -> cards -> voice/render
-> upload (scheduled) -> record.

    python run.py --script scripts/2026-10-04-0700.json   # what the workflow runs: the cloud
                                       # routine wrote this script; date+slot come from the name
    python run.py --script x.json --slot 1900 --dry-run    # render any script, no upload
    python run.py                      # API path: scrape + editor.py (needs ANTHROPIC_API_KEY)

Slots are idempotent: a slot that already has a video in state/history.json
exits 0, so the retry cron an hour later is harmless.
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))
SLOTS = {"morning": (7, 30), "evening": (17, 0)}   # 예전 이름 (2026-10-03 까지의 대본)
HISTORY = REPO / "state" / "history.json"


def load_history() -> list[dict]:
    return json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []


def save_history(rows: list[dict]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def pick_slot(name: str | None, now: dt.datetime, day: str | None = None) -> tuple[str, dt.datetime]:
    if not name or name == "auto":   # 다음 정각
        nxt = now + dt.timedelta(hours=1)
        name = f"{nxt.hour:02d}00"
    hhmm = name.lstrip("u")          # u2215 = 긴급 대본 (22:15 에 쓴 것, 영상이 나오면 바로 공개)
    h, m = SLOTS[name] if name in SLOTS else (int(hhmm[:2]), int(hhmm[2:]))
    base = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=KST) if day else now
    return name, base.replace(hour=h, minute=m, second=0, microsecond=0)


def gather(history: list[dict]) -> tuple[list[dict], list[str]]:
    import scrape
    posts, warns = scrape.collect()
    for w in warns:
        print("  WARN", w)
    if not posts:
        raise RuntimeError("커뮤니티 모두 수집 실패: " + " | ".join(warns))
    used = {h.get("source_post") for h in history}
    ranked = [p for p in scrape.rank(posts) if p["url"] not in used][:15]
    for p in ranked[:8]:
        b = scrape.post_body(p["url"])
        p["body"], p["links"] = b["text"], b["links"]
    return ranked, warns


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", default="auto")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--script")
    ap.add_argument("--date", help="KST publish date YYYY-MM-DD (default: from the script name, else today)")
    args = ap.parse_args()

    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    local = REPO / "config.local.yaml"     # PC 시험용 덮어쓰기 (gitignore) - 예: engine: voicebox
    if local.exists():
        cfg.update(yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    now = dt.datetime.now(KST)
    day, slot_name = args.date, args.slot
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(morning|evening|u?\d{4})\.json$", args.script or "")
    if m:
        day = day or m.group(1)
        slot_name = m.group(2) if slot_name in (None, "auto") else slot_name
    slot, publish_at = pick_slot(slot_name, now, day)
    key = f"{publish_at:%Y-%m-%d}-{slot}"
    history = load_history()
    if not args.dry_run and any(h.get("key") == key and h.get("video_id") for h in history):
        print(f"{key}: 이미 업로드됨 - 종료")
        return 0
    print(f"slot {key} -> publish {publish_at:%Y-%m-%d %H:%M} KST")
    t0 = time.time()
    record = {"key": key, "slot": slot, "publish_at": publish_at.isoformat(), "started": now.isoformat()}

    if args.script:
        script = json.loads(Path(args.script).read_text(encoding="utf-8"))
        brief, usage = script.get("brief", "(written by the cloud routine)"), []
        if script.get("skip"):
            print(f"{key}: 예약 작업이 소재를 건너뜀 - {script.get('skip_reason')}")
            if not args.dry_run:
                record.update({"skipped": script.get("skip_reason", "")})
                history.append(record)
                save_history(history)
            return 0
        from rules import validate
        problems = validate(script)
        if problems:
            raise RuntimeError("대본 검사 실패: " + " | ".join(problems))
    else:
        import editor
        print("[1/5] 커뮤니티 수집")
        candidates, warns = gather(history)
        record["scrape_warnings"] = warns
        recent = [h.get("title", "") for h in history[-30:]]
        print(f"[2/5] 취재 (후보 {len(candidates)}개)")
        brief, usage = editor.research(candidates, recent)
        print(brief[:1500])
        print("[3/5] 대본")
        script, u2 = editor.write(brief)
        usage += u2
        record["cost_usd"] = editor.cost_usd(usage)
        if script.get("skip"):
            raise RuntimeError("편집 AI가 소재를 고르지 못함: " + script.get("skip_reason", ""))
        problems = editor.validate(script)
        if problems:
            print("  대본 경고:", problems)
            record["script_warnings"] = problems

    slug = f"{publish_at:%Y-%m-%d}_{slot}_{script.get('slug') or 'short'}"
    out_dir = REPO / "output" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "brief.txt").write_text(brief, encoding="utf-8")

    print("[4/5] 음성 + 모션 렌더 (군림보식 패널 + いらすとや)")
    from pipeline.render import render
    video = out_dir / "video.mp4"
    stats = render(script, cfg, REPO, out_dir / "work", video)
    record.update(stats)
    print(f"  {stats}")
    if not 15 <= stats["duration"] <= 70:
        raise RuntimeError(f"영상 길이 {stats['duration']}s - 쇼츠 범위 밖")

    yt = script["youtube"]
    record.update({"title": yt["title"], "source_post": script.get("source_post"),
                   "facts_used": script.get("facts_used"), "slug": slug})
    if args.dry_run:
        print("[5/5] dry-run: 업로드 생략 ->", video)
    else:
        import upload
        if slot.startswith("u"):
            # 긴급: 업로드 3분 뒤 공개 (그 3분이 폰 검수 시간). 화제가 식기 전에 내보내는 게 목적이라 늦음 규칙 없음
            late = False
            publish_at = dt.datetime.now(KST) + dt.timedelta(minutes=3)
            record["publish_at"] = publish_at.isoformat()
            print("[5/5] 유튜브 업로드 (긴급 - 3분 뒤 공개)")
        else:
            # 회차 시각보다 90분 넘게 늦었으면 공개하지 않고 비공개로만 둔다 (운영자가 스튜디오에서 판단)
            late = dt.datetime.now(KST) - publish_at > dt.timedelta(minutes=90)
            print("[5/5] 유튜브 업로드 " + ("(회차 시각을 넘겨 비공개로만)" if late else "(예약 공개)"))
        res = upload.upload(str(video), yt["title"], yt["description"], yt["tags"], publish_at,
                            private_only=late)
        record["late"] = late
        record.update({"video_id": res["id"], "url": res["url"], "privacy": res["privacy"],
                       "scheduled_for": res["publish_at"]})
        print(f"  {res}")
    record["seconds"] = round(time.time() - t0)
    if not args.dry_run:
        history.append(record)
        save_history(history)
    (out_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done:", json.dumps({k: record.get(k) for k in ("key", "title", "url", "duration", "cost_usd", "seconds")},
                              ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
