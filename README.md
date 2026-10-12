# issue-shorts

@군림보 스타일 이슈 쇼츠를 하루 4편(07·12·18·21시, `config.yaml` 의 `slots`) 자동으로 만들어 유튜브에 **예약 공개**로 올린다.
PC가 꺼져 있어도 돈다. 유료 API 없이 Claude 구독 + GitHub Actions(무료)로만 돈다.

```
05·08·11·14·17·20시 KST  Claude 클라우드 예약 작업 (Claude 구독, ROUTINE.md 를 따름)
  1. gather 워크플로를 직접 돌려 커뮤니티 인기글 수집 → inbox/latest.json
     디시(실베·HIT)·더쿠·루리웹·네이트판·보배드림·엠팍 + 네이버 댓글 많은 기사 (에펨·개드립은 러너 IP 차단)
  2. 다음 회차 최대 3개: 소재 선택·취재 (웹 검색으로 언론 보도 확인)
  3. 음슴체 대본 JSON → rules.py 검사 → scripts/YYYY-MM-DD-HHMM.json 을 한 커밋으로 푸시
그 푸시로 GitHub Actions(produce) 시작 (아직 영상 기록이 없는 대본을 전부 차례로)
  4. いらすとや 그림 + 스톡 영상(Pixabay) → 소희 썰톤 음성(Qwen3-TTS, CPU) → 자막 2줄 → 효과음·배경음악 → mp4
  5. 유튜브 업로드: 비공개 + 예약 공개(그 회차 정각)
2시간마다            watchdog: 곧 공개될 회차나 지난 3시간 회차에 영상이 없으면 실패 메일
07·12·18·21시          유튜브가 공개로 전환
```

회차 시각보다 90분 넘게 늦게 만들어진 영상은 공개하지 않고 **비공개**로만 올린다 (스튜디오에서 직접 판단).

## 검수 (예약 공개 + 폰 확인)

- 공개 2~3시간 전에 유튜브 스튜디오 앱 → 콘텐츠 → **예약됨**에 올라와 있다.
- 미리 보고 문제가 있으면 **삭제**하면 끝. 아무것도 안 하면 정시에 공개된다.
- 영상·대본·취재 메모·카드 원본은 Actions 실행 페이지의 **Artifacts**에 7일간 남는다.
- 실패하면 GitHub 이 메일을 보낸다. 재시도 실행이 한 시간 뒤에 한 번 더 돈다.

## 비용

| 항목 | 비용 |
|---|---|
| GitHub Actions (공개 저장소) | 무료 |
| Claude 구독 예약 작업 (취재·대본) | 추가 비용 없음 (구독 사용량에서 차감) |
| 유튜브 API | 무료 (전용 프로젝트, 하루 약 6건 한도 중 2건 사용) |

## 처음 설정 (한 번)

1. **GitHub 로그인**: `gh auth login`
2. **유튜브 전용 Google Cloud 프로젝트** (지금세계 프로젝트는 하루 업로드 한도를 이미 다 써서 같이 쓰면 실패한다)
   1. https://console.cloud.google.com/projectcreate → 이름 `issue-shorts` → 만들기
   2. API 및 서비스 → 라이브러리 → **YouTube Data API v3** → 사용
   3. OAuth 동의 화면(Google 인증 플랫폼) → 외부 → 앱 이름·이메일 입력 → 저장 → 대상 → **앱 게시(프로덕션)**
      - '테스트' 상태로 두면 토큰이 7일마다 끊긴다
   4. 클라이언트 → 클라이언트 만들기 → 유형 **데스크톱 앱** → 클라이언트 ID·보안 비밀번호 복사
3. **비밀값 등록**: 이 폴더에서 `python setup.py`
   - Anthropic 키 질문은 엔터로 건너뛴다 (대본은 구독 예약 작업이 쓴다)
   - 클라이언트 ID·비밀번호를 붙여 넣는다 (화면에 안 보임)
   - 브라우저에서 새 채널을 골라 허용 → 터미널에 뜬 채널 이름이 맞으면 `y`
4. **클라우드 예약 작업**: https://claude.ai/code/routines 에 `issue-shorts 대본` (3시간마다, 05~20시 KST) 이 있어야 한다.

## 손으로 돌리기

```bash
gh workflow run produce -f script=examples/taiwan-taxi.json            # 시험: 업로드 없이 영상만 (기본값)
gh workflow run produce -f script=scripts/2026-10-04-1900.json -f dry_run=false   # 그 대본으로 예약 업로드
gh run list -w produce                                                 # 실행 기록
```

대본을 손으로 쓰려면 `examples/taiwan-taxi.json` 형식으로 `scripts/YYYY-MM-DD-HHMM.json` (HHMM 은 `slots` 중 하나) 을 만들어 `python rules.py <파일>` 로 검사한 뒤 main 에 푸시하면 된다.
PC에서 직접: `python run.py --script <파일> --dry-run` (config.yaml 의 engine 을 `voicebox` 로 바꾸면 Voicebox 앱 '소희' 프로필로 렌더링).
API 키로 돌리는 예전 방식(`python run.py`, editor.py)도 남아 있다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `scrape.py` | 커뮤니티 4곳 인기글 목록·본문 |
| `gather.py` | 인기글 순위 + 본문 속 뉴스 제목 → `inbox/latest.json` (공개 저장소라 본문·기사 원문은 안 올림) |
| `.github/workflows/gather.yml` | 02:30·12:30 KST 수집 |
| `ROUTINE.md` | 클라우드 예약 작업이 매번 따르는 지침 (소재 기준·취재·음슴체·카드·검사·푸시) |
| `rules.py` | 대본 JSON 형식과 검사 (`python rules.py <파일>`) |
| `editor.py` | (선택) Claude API 로 취재·대본 - API 키가 있을 때만 |
| `make_cards.py` | 군림보식 카드 (제목 2줄 + 그림 패널), 넘침 검사 |
| `pipeline/tts.py` | 소희 음성 + whisper 타이밍 + 발음 검사(어긋나면 다시 생성) |
| `pipeline/render.py` | 켄번즈·자막·효과음·배경음악 합성 |
| `upload.py` | 예약 공개 업로드 |
| `run.py` | 한 회차 렌더링·업로드, 중복 방지, 기록 |
| `.github/workflows/produce.yml` | scripts/ 푸시 → 영상 → 예약 업로드 |
| `.github/workflows/watchdog.yml` | 05:30·15:30 점검, 빠지면 실패 메일 |
| `config.yaml` | 목소리·말투 지시·속도·자막 규칙 |
| `state/history.json` | 회차별 기록 (소재 중복 방지에도 쓴다) |

효과음은 비공개 저장소 `issue-shorts-assets`(배포 키로 읽음)에 있다. 바탕화면 '효과음 모음'에서 가져온 파일이라 출처가 불분명해 공개 저장소에 두지 않는다.
글꼴 Black Han Sans 는 OFL, 배경음악은 CC0 (`assets/bgm/CREDITS.md`).

## 소재 기준 (ROUTINE.md)

- 우선: 반전·황당 포인트가 한 문장으로 설명되는 것, 댓글 많고 여러 커뮤니티에 동시에 뜬 것, 언론 보도로 확인되는 것
- 소재 제한 없음 (정치·갈등 포함). 다루는 방식: 편들지 않기, 의혹은 주장으로만, 일반인·피해자·미성년자 신원 비공개, 사망·참사엔 웃음 톤 금지, 의료·투자 조언 금지
- 제외: 최근 다룬 소재
- 커뮤니티 글에만 있는 주장은 사실로 쓰지 않는다. 따옴표 카드는 기사에 나온 발언만.
