# issue-shorts

@군림보 스타일 이슈 쇼츠를 매일 2편(07:30·17:00 KST) 자동으로 만들어 유튜브에 **예약 공개**로 올린다.
PC가 꺼져 있어도 GitHub Actions 에서 돈다.

```
04:30 / 14:00 KST  GitHub Actions 시작 (실패 대비 05:30 / 15:00 재시도)
  1. 커뮤니티 인기글 수집   디시 실베·에펨 포텐·더쿠 HOT·개드립, 댓글 수 + 여러 곳 동시 화제 가산점
  2. 취재 (Claude Opus 5.5) 소재 1개 선택 → 웹 검색으로 언론 보도 확인 → 취재 메모
  3. 대본 (Claude Opus 5.5) 확인된 사실만으로 음슴체 대본 + 카드 + 유튜브 제목·설명 (JSON)
  4. 카드 → 소희 썰톤 음성(Qwen3-TTS, CPU) → 자막 2줄 → 효과음·배경음악 → mp4
  5. 유튜브 업로드: 비공개 + 예약 공개(07:30 / 17:00)
07:30 / 17:00      유튜브가 공개로 전환
```

## 검수 (예약 공개 + 폰 확인)

- 공개 2~3시간 전에 유튜브 스튜디오 앱 → 콘텐츠 → **예약됨**에 올라와 있다.
- 미리 보고 문제가 있으면 **삭제**하면 끝. 아무것도 안 하면 정시에 공개된다.
- 영상·대본·취재 메모·카드 원본은 Actions 실행 페이지의 **Artifacts**에 7일간 남는다.
- 실패하면 GitHub 이 메일을 보낸다. 재시도 실행이 한 시간 뒤에 한 번 더 돈다.

## 비용

| 항목 | 비용 |
|---|---|
| GitHub Actions (공개 저장소) | 무료 |
| Claude Opus 5.5 (취재·대본) | 편당 약 $0.35 → 월 60편 약 $21 (입력 $4 / 출력 $20 per 1M 토큰, 웹 검색 1,000회 $10) |
| 유튜브 API | 무료 (전용 프로젝트, 하루 약 6건 한도 중 2건 사용) |

실제 비용은 `state/history.json` 의 `cost_usd` 에 회차마다 남는다.

## 처음 설정 (한 번)

1. **GitHub 로그인**: `gh auth login`
2. **Anthropic API 키**: https://console.anthropic.com → 결제 수단 등록 → API Keys → Create Key
3. **유튜브 전용 Google Cloud 프로젝트** (지금세계 프로젝트는 하루 업로드 한도를 이미 다 써서 같이 쓰면 실패한다)
   1. https://console.cloud.google.com/projectcreate → 이름 `issue-shorts` → 만들기
   2. API 및 서비스 → 라이브러리 → **YouTube Data API v3** → 사용
   3. OAuth 동의 화면(Google 인증 플랫폼) → 외부 → 앱 이름·이메일 입력 → 저장 → **앱 게시(프로덕션)**
      - '테스트' 상태로 두면 토큰이 7일마다 끊긴다
   4. 사용자 인증 정보 → OAuth 클라이언트 ID 만들기 → 유형 **데스크톱 앱** → 클라이언트 ID·보안 비밀번호 복사
4. **비밀값 등록**: 이 폴더에서 `python setup.py`
   - API 키, 클라이언트 ID·비밀번호를 붙여 넣는다 (화면에 안 보임)
   - 브라우저에서 새 채널을 골라 허용 → 터미널에 뜬 채널 이름이 맞으면 `y`
5. **시험 실행**: `gh workflow run produce -f dry_run=true` (업로드 없이 영상만 → Artifacts 에서 확인)

## 손으로 돌리기

```bash
gh workflow run produce -f slot=evening            # 17:00 회차를 지금 만들어 예약 업로드
gh workflow run produce -f dry_run=true            # 업로드 없이 영상만
gh run list -w produce                              # 실행 기록
```

PC에서 직접: `python run.py --dry-run` (config.yaml 의 engine 을 `voicebox` 로 바꾸면 Voicebox 앱 '소희' 프로필로 빠르게 렌더링).

## 파일

| 파일 | 하는 일 |
|---|---|
| `scrape.py` | 커뮤니티 4곳 인기글 목록·본문 |
| `editor.py` | Claude 취재·대본 프롬프트, JSON 스키마, 검증 |
| `make_cards.py` | 군림보식 카드 (제목 2줄 + 그림 패널), 넘침 검사 |
| `pipeline/tts.py` | 소희 음성 + whisper 타이밍 + 발음 검사(어긋나면 다시 생성) |
| `pipeline/render.py` | 켄번즈·자막·효과음·배경음악 합성 |
| `upload.py` | 예약 공개 업로드 |
| `run.py` | 한 회차 전체 실행, 중복 방지, 기록 |
| `config.yaml` | 목소리·말투 지시·속도·자막 규칙 |
| `state/history.json` | 회차별 기록 (소재 중복 방지에도 쓴다) |

효과음은 비공개 저장소 `issue-shorts-assets`(배포 키로 읽음)에 있다. 바탕화면 '효과음 모음'에서 가져온 파일이라 출처가 불분명해 공개 저장소에 두지 않는다.
글꼴 Black Han Sans 는 OFL, 배경음악은 CC0 (`assets/bgm/CREDITS.md`).

## 소재 기준 (editor.py)

- 우선: 반전·황당 포인트가 한 문장으로 설명되는 것, 댓글 많고 여러 커뮤니티에 동시에 뜬 것, 언론 보도로 확인되는 것
- 제외: 정치·종교·젠더 갈등·혐오 조장, 일반인 신상·피해자 특정·사망 사건, 연예인 사생활·루머, 성적 내용, 미성년자, 의료·투자, 최근 다룬 소재
- 커뮤니티 글에만 있는 주장은 사실로 쓰지 않는다. 따옴표 카드는 기사에 나온 발언만.
