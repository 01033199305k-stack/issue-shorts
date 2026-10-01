# -*- coding: utf-8 -*-
"""비밀값 등록 (처음 한 번, 또는 키·토큰을 바꿀 때). 본인 터미널에서 실행한다.

    python setup.py

- 입력값은 화면에 보이지 않고, gh 로 GitHub Secrets 에 바로 들어간다 (파일·로그에 남지 않음).
- 엔터만 누르면 그 항목은 건너뛴다 (이미 넣어 둔 값 유지).
- 유튜브는 브라우저에서 구글 로그인 → 새 채널(브랜드 계정) 선택 → 허용.
  로그인된 채널 이름을 보여 주고, 맞다고 해야 저장한다.
- "Google에서 확인하지 않은 앱" 경고는 본인 앱이라 '고급 → 이동'으로 넘어가면 된다.
- OAuth 동의 화면이 '프로덕션' 상태여야 토큰이 7일 뒤에 끊기지 않는다.
"""
import getpass
import http.server
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def repo() -> str:
    url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    return url.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")


def set_secret(name: str, value: str, target: str) -> None:
    r = subprocess.run(["gh", "secret", "set", name, "-R", target], input=value, text=True,
                       capture_output=True)
    if r.returncode != 0:
        sys.exit(f"{name} 저장 실패: {r.stderr.strip()}")
    print(f"  ✓ {name} 저장")


def oauth(client_id: str, client_secret: str) -> str:
    code_box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_box["code"] = (q.get("code") or [""])[0]
            code_box["error"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("인증 완료. 이 창을 닫고 터미널로 돌아가세요.".encode())

        def log_message(self, *args):
            pass

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent select_account"})
    print("\n브라우저에서 구글 로그인 → 새 채널 선택 → 허용 하세요. 안 열리면 이 주소를 여세요:\n" + url)
    webbrowser.open(url)
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    while "code" not in code_box:
        server.handle_request()
    if not code_box["code"]:
        sys.exit("인증 거부됨: " + code_box.get("error", ""))
    data = urllib.parse.urlencode({"code": code_box["code"], "client_id": client_id,
                                   "client_secret": client_secret, "redirect_uri": REDIRECT,
                                   "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as r:
        tok = json.loads(r.read())
    if "refresh_token" not in tok:
        sys.exit("refresh_token 이 오지 않았습니다. 구글 계정 → 보안 → 서드파티 액세스에서 앱을 지우고 다시 실행하세요.")
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                                 headers={"Authorization": "Bearer " + tok["access_token"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.loads(r.read()).get("items", [])
    name = items[0]["snippet"]["title"] if items else "(채널 없음)"
    if input(f"\n로그인된 채널: 「{name}」 - 이 채널에 올리면 됩니까? (y/n) ").strip().lower() != "y":
        sys.exit("취소했습니다. 다시 실행해서 올바른 채널을 고르세요.")
    return tok["refresh_token"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        sys.exit("먼저 `gh auth login` 으로 GitHub 에 로그인하세요.")
    target = repo()
    print(f"저장소: {target}  (엔터 = 건너뛰기)\n")

    key = getpass.getpass("Anthropic API 키 - 구독 예약 작업으로 대본을 쓰면 필요 없음, 엔터로 건너뛰기: ").strip()
    if key:
        set_secret("ANTHROPIC_API_KEY", key, target)

    cid = getpass.getpass("유튜브 OAuth 클라이언트 ID (새 프로젝트, ...apps.googleusercontent.com): ").strip()
    if cid:
        secret = getpass.getpass("유튜브 OAuth 클라이언트 보안 비밀번호: ").strip()
        refresh = oauth(cid, secret)
        set_secret("YOUTUBE_CLIENT_ID", cid, target)
        set_secret("YOUTUBE_CLIENT_SECRET", secret, target)
        set_secret("YOUTUBE_REFRESH_TOKEN", refresh, target)
    print("\n완료. 시험 실행: gh workflow run produce -R " + target + " -f dry_run=true")


if __name__ == "__main__":
    main()
