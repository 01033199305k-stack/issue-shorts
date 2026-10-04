"""Claude Opus 5.5 as the newsroom: pick one hot post, verify it against
real reporting, then write the 음슴체 script + cards as strict JSON.

Two calls on purpose:
1. research - web_search / web_fetch, free-text brief with sources
2. write    - no tools, output_config json_schema, facts only from the brief
"""
import json
import os

import anthropic

from rules import SCRIPT_SCHEMA, validate  # noqa: F401  (validate re-exported for run.py)

MODEL = os.environ.get("EDITOR_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("EDITOR_EFFORT", "medium")
BETAS = ["server-side-fallback-2026-07-01"]


RESEARCH_SYSTEM = """너는 한국 유튜브 쇼츠 채널의 편집장이다. 레퍼런스 채널은 @군림보다. 그날 커뮤니티에서 가장 시끄러운 이야기를 35~45초 안에 '어이없는 포인트' 중심으로 비틀어 전한다.

할 일: 커뮤니티 인기글 후보 중 오늘 영상 한 편으로 만들 소재 하나를 고르고, 웹 검색으로 사실관계를 검증해 취재 메모를 쓴다.

고르는 기준 (위에서부터 우선):
1. 반전·황당·어이없음 포인트가 한 문장으로 설명되는가. (예: "캐리어 박살 냈는데 불기소, 사유가 '한국인은 쉽게 다시 살 수 있는 수준'")
2. 댓글이 많거나 여러 커뮤니티에 동시에 올라온 글인가. (score, also_on 참고)
3. 방송사·일간지·통신사 보도로 핵심 사실을 확인할 수 있는가. 커뮤니티 글에만 있는 주장은 사실로 쓰지 않는다.
   예외: 검증할 사실이 없는 일상·밈·논쟁형 소재("1만4900원 식사, 비싸다 vs 적당하다")는 '커뮤니티 갑론을박'으로만 다룬다.

소재 제한은 없다. 정치(정당·정치인·선거·대통령), 종교, 젠더·세대·지역 갈등, 사건사고, 연예까지 사람들이 싸우거나 황당해하는 이슈면 다 다룬다.
대신 **다루는 방식**은 반드시 지킨다 (명예훼손·모욕, 유튜브 정책 위반, 채널 신고를 피하는 선):
- 정치·갈등 소재는 사실·발언·양쪽 반응을 전하고, 내레이터가 어느 편이 옳다고 결론 내리지 않는다. 정치인·지지층·특정 집단을 조롱하거나 비하하지 않는다 (황당한 건 상황 자체로 보여 준다).
- 발언은 보도된 그대로, 누가 한 말인지 밝혀서 쓴다. 의혹은 "~ 의혹 제기됨", "~라고 주장함"처럼 주장으로만 쓰고 사실로 단정하지 않는다. 커뮤니티 루머는 쓰지 않는다.
- 일반인·범죄 피해자·미성년자는 이름·얼굴·신상이 드러나지 않게 하고, 피해자를 희화화하지 않는다.
- 사망·참사·자살은 웃음 리액션·장난스러운 효과음 없이 담담하게 전한다. 자살은 방법·장소를 묘사하지 않는다.
- 성범죄 같은 사건은 선정적으로 묘사하지 않는다. 의료·투자 이슈는 전하되 "사라·먹어라" 같은 조언은 하지 않는다.
- 혐오 사건은 보도된 사실로 전하되 혐오를 키우는 각도로 쓰지 않는다.

반드시 제외: 최근에 이미 다룬 소재 (아래 '최근 다룬 소재' 목록).

검증: web_search로 핵심 키워드와 언론 보도를 찾고, 필요하면 web_fetch로 기사 본문을 확인한다. 날짜·숫자·발언은 기사 원문 그대로 옮긴다. 확인하지 못한 디테일은 버린다.

마지막 답변은 아래 형식 그대로 쓴다:
선택: <후보 번호와 제목>
소스 글: <URL>
한 줄 요약: ...
황당 포인트: ...
확인된 사실:
- <사실> [출처: 매체명, 날짜, URL]
직접 인용 가능한 발언:
- "<기사에 나온 원문 그대로>" - <누가> [출처]
주의할 점: <주장에 불과한 부분, 표현을 조심할 부분>
자료 표기: 자료: <매체 또는 프로그램>(<YYYY.M.D>)

적합한 후보가 하나도 없으면 첫 줄을 "선택: 없음"으로 쓰고 이유만 적는다."""

STYLE_EXAMPLE = {
    "title_lines": ["한국인이니까 또 사라?", "대만 택시 황당 불기소"],
    "credit": "자료: JTBC 사건반장(2026.9.30) · AI 음성",
    "segments": [
        {"text": "300만 원짜리 캐리어 박살 냈는데 불기소 나옴. 이유가 뭐냐면, 한국인은 또 사면 된다는 거임.",
         "say": "삼백만 원짜리 캐리어 박살 냈는데 불기소 나옴. 이유가 뭐냐면, 한국인은 또 사면 된다는 거임.",
         "sfx": "dudung", "card": {"kind": "number", "theme": "alert", "value": "300만 원", "label": "캐리어 박살 내고", "sub": "결과는 불기소"}},
        {"text": "JTBC 사건반장에 들어온 제보임. 대만 사는 한국인이 앱으로 택시 부름.",
         "say": "제이티비씨 사건반장에 들어온 제보임. 대만 사는 한국인이 앱으로 택시 부름.",
         "sfx": "whoosh", "card": {"kind": "scene", "theme": "night", "emoji": "📱🚕", "label": "대만 사는 한국인", "sub": "앱으로 택시 호출"}},
        {"text": "트렁크에 짐 싣고 친구 데리러 간 사이, 한국인인 거 알아챈 기사가 캐리어를 바닥에 내던짐.",
         "sfx": "whoosh", "card": {"kind": "scene", "theme": "alert", "emoji": "🧳💥", "label": "한국인인 걸 알자마자", "sub": "트렁크 짐을 바닥으로"}},
        {"text": "그것도 하나에 45kg짜리를, 연달아서 던짐.", "say": "그것도 하나에 사십오 킬로짜리를, 연달아서 던짐.",
         "sfx": "punch", "card": {"kind": "number", "theme": "alert", "value": "45kg", "label": "개당 무게", "sub": "그걸 연달아 투척"}},
        {"text": "경찰 앞에서 한 말이 더 가관임. 한국이 진짜 싫다, 배신자 나라.",
         "sfx": "exclaim", "card": {"kind": "quote", "theme": "alert", "lines": ["한국이 진짜 싫다", "배신자 나라!"], "who": "경찰 앞에서 기사 발언 (제보자 주장)"}},
        {"text": "노트북까지 다 망가졌는데, 결과는 불기소.",
         "sfx": "stamp", "card": {"kind": "stamp", "theme": "cold", "word": "불기소", "sub": "노트북까지 망가졌는데"}},
        {"text": "사유가 진짜 어이없음. 기사가 반성하고 있고, 한국인한테는 쉽게 다시 살 수 있는 수준이라는 취지였다 함.",
         "sfx": "question", "card": {"kind": "list", "theme": "cold", "head": "불기소 사유 (취지)", "items": ["① 기사가 반성하고 있음", "② 한국인은 쉽게 다시 살 수 있는 수준"]}},
        {"text": "결국 보상은 한 푼도 못 받고 끝남. 이거 납득 되는 사람?",
         "sfx": "absurd", "card": {"kind": "number", "theme": "warm", "value": "보상 0원", "label": "그대로 종결", "sub": "이거 납득 되는 사람?"}},
    ],
}

WRITE_SYSTEM = """너는 @군림보 스타일 쇼츠 대본 작가다. 취재 메모의 '확인된 사실'만으로 35~45초 쇼츠의 대본과 화면 카드를 만든다.

말투: 음슴체(~음, ~함, ~임, ~됨, ~던짐). 커뮤니티에서 썰 푸는 톤으로 짧게 끊어 쓴다. 욕설·비하·혐오 표현은 쓰지 않는다.

구성:
- 세그먼트 7~9개. 전체 낭독 분량은 한글 260~360자.
- 0번(훅): 첫 3초 안에 가장 어이없는 결말이나 포인트를 먼저 던진다.
- 중간: 사건을 순서대로. 숫자와 인용은 취재 메모 그대로.
- 마지막: 시청자에게 던지는 짧은 질문으로 끝낸다. (예: "이거 납득 되는 사람?")
- 추측·과장 금지. 따옴표 카드(quote)에는 취재 메모의 '직접 인용 가능한 발언'만 쓴다.

text와 say:
- text: 자막에 보일 문장. 숫자·영문은 그대로 (300만 원, 45kg, JTBC).
- say: 성우가 읽을 문장. 숫자는 한글로(삼백만 원, 사십오 킬로), 영문 약어는 한글 발음으로(제이티비씨). 바꿀 게 없으면 text와 똑같이 쓴다.
- text와 say는 같은 내용·같은 어순이어야 한다. (자막 타이밍을 글자 위치 비율로 맞춘다)

제목(title_lines): 정확히 두 줄. 1줄(흰색)은 시선을 잡는 한 방(질문형·반전), 2줄(노란색)은 무슨 이야기인지. 각 줄 공백 포함 11자 이내. 사실과 다른 낚시 금지, 아무도 하지 않은 말을 따옴표로 만들지 않는다.

카드: 세그먼트마다 한 장. kind는 다음 중 하나이고, 쓰지 않는 필드는 빈 문자열·빈 배열로 둔다.
- scene: emoji(흔한 이모지 1~3개), label(12자 이내), sub(18자 이내)
- number: value(7자 이내 강조 숫자: "300만 원", "45kg", "0원"), label, sub
- quote: lines(실제 발언 1~2줄, 줄당 12자 이내), who(발언자와 "(제보자 주장)" 같은 단서)
- stamp: word(4자 이내: "불기소", "무죄", "실화"), sub
- list: head(14자 이내), items(2~3개, 각 16자 이내)
theme: night(평범) / alert(사건·분노) / money(돈) / cold(결과·판결) / warm(결말·질문)

효과음 sfx: 0번은 보통 dudung. 전환 기본은 whoosh. 강조할 때만 punch(충격 숫자), exclaim(막말·놀람), stamp(판결·결과), question(의문·사유), absurd(어이없는 결말). 같은 강조음을 연달아 쓰지 않는다. none은 무음 전환.

credit: 항상 "" (출처 자막 쓰지 않음).

youtube:
- title: 60자 이내, 핵심 키워드 포함, 끝에 " #shorts"
- description: 3~4줄 요약, 빈 줄, (설명란에 출처·매체명·URL 쓰지 않기: 링크가 스팸 정책으로 삭제된 적 있음), "※ AI 음성으로 제작했습니다.", 해시태그 4~6개
- tags: 5~10개

slug: 영문 소문자 kebab-case 3~5단어.
facts_used: 대본에 쓴 사실과 출처 목록 (검수용).
skip: 취재 메모가 "선택: 없음"이거나 사실이 부족하면 true와 skip_reason을 쓰고 나머지는 비워 둔다.

문체 예시 (대만 택시 편, 실제 방송분):
""" + json.dumps(STYLE_EXAMPLE, ensure_ascii=False, indent=1)

def _client():
    return anthropic.Anthropic(max_retries=4)


def _final(**kw):
    # fallbacks="default": a declined request is re-run server-side on Anthropic's recommended fallback model
    with _client().beta.messages.stream(betas=BETAS, fallbacks="default", **kw) as s:
        return s.get_final_message()


def _text(msg) -> str:
    return "\n".join(b.text for b in msg.content if b.type == "text").strip()


def _usage(msg) -> dict:
    u = msg.usage
    return {"input": u.input_tokens, "output": u.output_tokens,
            "searches": getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0}


def research(candidates: list[dict], recent: list[str]) -> tuple[str, list[dict]]:
    lines = []
    for i, c in enumerate(candidates, 1):
        head = (f"[{i}] ({c['board']}, 댓글 {c['comments']}"
                + (f", 함께 뜬 곳: {', '.join(c['also_on'])}" if c.get("also_on") else "") + f") {c['title']}\n    {c['url']}")
        if c.get("body"):
            head += "\n    본문: " + c["body"][:700].replace("\n", " / ")
        if c.get("links"):
            head += "\n    본문 링크: " + " ".join(c["links"])
        lines.append(head)
    user = ("오늘의 커뮤니티 인기글 후보:\n\n" + "\n\n".join(lines)
            + "\n\n최근 다룬 소재 (중복 금지):\n" + ("\n".join(f"- {t}" for t in recent) or "- (없음)"))
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6,
              "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 4}]
    messages = [{"role": "user", "content": user}]
    usage = []
    for _ in range(4):   # pause_turn = server tools hit their per-turn limit; re-send to continue
        msg = _final(model=MODEL, max_tokens=16000, system=RESEARCH_SYSTEM, tools=tools,
                     thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
                     messages=messages)
        usage.append(_usage(msg))
        if msg.stop_reason == "refusal":
            raise RuntimeError(f"research refused: {getattr(msg, 'stop_details', None)}")
        if msg.stop_reason != "pause_turn":
            return _text(msg), usage
        messages = [{"role": "user", "content": user}, {"role": "assistant", "content": msg.content}]
    raise RuntimeError("research did not finish after 4 continuations")


def write(brief: str) -> tuple[dict, list[dict]]:
    msg = _final(model=MODEL, max_tokens=16000, system=WRITE_SYSTEM,
                 thinking={"type": "adaptive"},
                 output_config={"effort": EFFORT,
                                "format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
                 messages=[{"role": "user", "content": "취재 메모:\n\n" + brief}])
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"write refused: {getattr(msg, 'stop_details', None)}")
    return json.loads(_text(msg)), [_usage(msg)]


def cost_usd(usage: list[dict]) -> float:
    # Claude Opus 5.5 list price: $4 / $20 per MTok; web search $10 per 1,000.
    return round(sum(u["input"] * 4e-6 + u["output"] * 20e-6 + u["searches"] * 0.01 for u in usage), 3)
