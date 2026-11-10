"""PC side of the Grok scenes (grokclips.py): uploads what the Chrome extension saved.

다운로드/썰가챠/grok-<회차>/ 의 start.json, scene_XX.mp4, done.json 을 공개 릴리스 grok-<회차>(prerelease)에
올린다. 작업 스케줄러가 3분마다 실행한다 (등록: tools/grok_upload_task.ps1). gh CLI 로그인을 그대로 쓴다.
done.json 은 그 폴더의 mp4 가 전부 올라간 뒤 마지막에 올린다 - 렌더러는 done.json 을 보고 기다림을 끝낸다.
"""
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = "01033199305k-stack/issue-shorts"
ROOT = Path.home() / "Downloads" / "썰가챠"


def gh_exe() -> str:
    hits = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\GitHub.cli_*\bin\gh.exe"))
    return hits[0] if hits else "gh"


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([gh_exe(), *args, "-R", REPO], capture_output=True, text=True, encoding="utf-8")


def sync(folder: Path) -> str:
    key = folder.name[len("grok-"):]
    tag = f"grok-{key}"
    state_f = folder / ".uploaded.json"
    sent = set(json.loads(state_f.read_text(encoding="utf-8"))) if state_f.exists() else set()
    if "done.json" in sent:
        return ""
    if gh("release", "view", tag, "--json", "tagName").returncode != 0:
        r = gh("release", "create", tag, "--prerelease", "--title", f"Grok 장면 {key}",
               "--notes", "썰가챠 Grok 장면 (PC 확장이 만듦, 렌더링이 받아 쓰고 며칠 뒤 지워짐)")
        if r.returncode != 0:
            return f"{tag}: 릴리스 만들기 실패 {r.stderr.strip()[:200]}"
    names = sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    # 받는 중인 파일(.crdownload)은 건너뛰고, done.json 은 mp4 가 다 올라간 다음에
    todo = [n for n in names if n not in sent and n != "done.json" and (n.endswith(".mp4") or n.endswith(".json"))]
    if "done.json" in names and not [n for n in names if n.endswith(".crdownload")]:
        todo.append("done.json")
    msgs = []
    for n in todo:
        r = gh("release", "upload", tag, str(folder / n), "--clobber")
        if r.returncode != 0:
            msgs.append(f"{tag}/{n}: 올리기 실패 {r.stderr.strip()[:200]}")
            break
        sent.add(n)
        msgs.append(f"{tag}/{n} 올림")
        state_f.write_text(json.dumps(sorted(sent)), encoding="utf-8")
    return "\n".join(msgs)


def main() -> int:
    if not ROOT.exists():
        return 0
    out = []
    for folder in sorted(ROOT.glob("grok-*")):
        if folder.is_dir() and (msg := sync(folder)):
            out.append(msg)
    if out:   # pythonw (작업 스케줄러, 창 없음)에는 stdout 이 없어서 파일에 남긴다
        import datetime
        with open(ROOT / "grok_upload.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%m-%d %H:%M}] " + "\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
