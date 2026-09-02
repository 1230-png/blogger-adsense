#!/usr/bin/env python3
"""Groq API를 사용한 Blogger 블로그 글 자동 생성.

애드센스가 "가치가 별로 없는 콘텐츠"로 반려한 뒤, 원인을 코드 쪽에서 정리한
결과가 이 파일이다. 이전 버전이 만들어내던 HTML은 예외 없이 아래 한 가지
모양이었다.

    <p>서론</p>
    <h2>소제목</h2><p>본문</p><ul>…</ul>   ← 4~6회
    <h2>마무리</h2><p>결론</p>              ← 매번 같은 리터럴

그래서 발행된 글 전부가 (1) 이미지도 표도 없는 벽글, (2) 서로 오가는 링크가
없는 고립된 페이지, (3) 마지막 소제목까지 똑같은 동일 구조였다. 셋 다
"템플릿으로 찍어냈다"는 신호로 읽힌다. 지금 버전이 바꾼 것:

- 결론 소제목을 LLM이 주제에 맞게 짓는다 (고정 리터럴 제거)
- 글머리에 핵심 요약 <table> 을 넣어 벽글에서 벗어난다
- 같은 카테고리의 기존 글로 가는 내부 링크를 붙인다
- LLM이 뱉은 텍스트를 전부 HTML 이스케이프한다
- 분량 기준을 렌더된 HTML 기준으로 다시 세고, 발행 직전에 quality.py 의
  게이트를 통과하지 못하면 발행하지 않는다 (감사와 완전히 같은 기준)
"""

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

import quality

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USED_JSON = DATA_DIR / "used_topics.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Groq 무료 티어는 모델을 주기적으로 퇴역시킨다(llama-3.3-70b-versatile 는
# 2026-08-16 퇴역했고, 그 뒤로 이 엔드포인트는 404를 돌려준다). 모델 하나가
# 사라져도 발행이 멈추지 않도록 후보 목록을 두고 404면 다음으로 넘어간다.
# GROQ_MODEL 을 지정하면 그 모델만 사용한다.
GROQ_MODEL = os.getenv("GROQ_MODEL", "")
GROQ_MODEL_CANDIDATES = [GROQ_MODEL] if GROQ_MODEL else [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# 산문(서론+섹션 본문+리스트+결론)만 센 최소 길이. 요약 표나 링크 블록은
# 빼고 잰다. quality.MIN_TEXT_CHARS 는 렌더 결과 전체에 적용되므로 그보다
# 조금 낮게 잡아, 산문이 기준을 넘으면 전체도 자연히 넘도록 한다.
MIN_PROSE_CHARS = 1600

# 한국어는 토큰당 글자 수가 적어서, 1,600자를 넘기려면 넉넉한 상한이 필요하다.
# 이전 값(3000)은 JSON 오버헤드까지 감안하면 목표 분량에 닿지 못했다.
MAX_TOKENS = 6000

# 붙일 내부 링크 개수. 너무 많으면 링크 목록이 본문보다 눈에 띈다.
RELATED_LINK_COUNT = 3

# 카테고리별로 글 끝에 붙는 한 줄 고지. YMYL(돈·건강) 주제에서는 형식이 아니라
# 실제로 필요하다. 다만 모든 글에 그대로 반복되므로 한 문장만 쓴다 — 길어지면
# quality.py 의 '공용 문장 비율' 검사에 스스로 걸린다.
CATEGORY_NOTICE = {
    "finance": "이 글은 일반적인 정보 제공을 위한 것이며, 금리와 공제 요건은 수시로 "
               "바뀌므로 가입·신청 전에 해당 기관의 공식 안내를 확인하시기 바랍니다.",
    "health": "이 글은 일반적인 건강 정보이며 의학적 진단이나 처방을 대신하지 않으므로, "
              "증상이 있다면 의사 또는 약사와 상담하시기 바랍니다.",
    "life": "제도와 신청 요건은 개정될 수 있으므로, 실제 신청 전에 관할 기관의 공고를 "
            "직접 확인하시기 바랍니다.",
}

SYSTEM_MESSAGE = """당신은 한국어 블로그의 전문 에디터입니다. 검색으로 들어온
독자가 "그래서 뭘 어떻게 하면 되는지"에 대한 답을 한 페이지에서 얻고 나갈 수
있는 글을 씁니다.

요구사항:
1. 요약이나 짜깁기가 아니라, 구체적인 절차·기준·수치·판단 근거를 담을 것.
   "중요합니다", "도움이 됩니다" 같은 빈 문장으로 분량을 채우지 말 것.
2. 서론(이 문제가 왜 생기는지) - 소제목 5~7개(각각 다른 각도에서, 구체적인
   설명과 실천 항목) - 결론 구조를 지킬 것.
3. 결론의 소제목은 주제에 맞게 직접 지을 것. "마무리", "결론" 같은 일반적인
   단어를 그대로 쓰지 말 것.
4. 과장 광고나 근거 없는 의학적·재무적 단정을 피하고, 확실하지 않은 것은
   "경우에 따라 다르다"고 정직하게 쓸 것. 통계 수치나 법령 조항 번호를
   지어내지 말 것.
5. 산문(서론+각 섹션 본문+결론)의 합계가 1,600자를 넘도록 충분히 상세할 것.
6. 아래 JSON 스키마 그대로만 반환할 것 (마크다운 코드블록이나 설명 문장 금지).

{
  "title": "검색 의도에 맞는 구체적인 제목",
  "meta_description": "검색결과에 보일 100자 내외 요약",
  "summary": [
    {"label": "짧은 항목명", "detail": "한 문장 설명"}
  ],
  "intro": "서론 3~5문장",
  "sections": [
    {"heading": "소제목", "body": "본문 4~6문장", "list": ["실천 항목 1", "실천 항목 2"]}
  ],
  "conclusion_heading": "결론 소제목 (주제에 맞게 직접 작성)",
  "conclusion": "결론 3~5문장",
  "tags": ["태그1", "태그2", "태그3"]
}

"summary"는 3~5개, "sections"는 5~7개를 채웁니다.
"list"가 필요 없는 섹션이면 빈 배열로 두어도 됩니다.
HTML 태그는 쓰지 말고 순수 텍스트로만 작성하세요."""


# --- LLM 호출 -----------------------------------------------------------------


def _call_groq(topic: str, category_label: str, extra_instruction: str = "") -> dict:
    prompt = f"""다음 주제로 블로그 글을 작성하세요.

카테고리: {category_label}
주제: {topic}
{extra_instruction}

JSON으로만 반환하세요."""

    for model in GROQ_MODEL_CANDIDATES:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": MAX_TOKENS,
            },
            timeout=120,
        )

        # 404 는 "그런 모델이 없다"는 뜻이다(키가 틀리면 401). 퇴역한 모델일 수
        # 있으므로 다음 후보로 넘어간다.
        if response.status_code == 404:
            print(
                f"⚠️ 모델 '{model}' 을(를) 찾을 수 없습니다(404). 다음 후보로 시도합니다.",
                file=sys.stderr,
            )
            continue

        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        return json.loads(content.strip())

    raise RuntimeError(
        "사용 가능한 Groq 모델이 없습니다. 시도한 모델: "
        + ", ".join(GROQ_MODEL_CANDIDATES)
        + ". console.groq.com/docs/models 에서 현재 모델을 확인한 뒤 "
        "GROQ_MODEL 시크릿으로 지정하세요."
    )


# --- 내부 링크 ----------------------------------------------------------------


def load_published() -> list:
    """used_topics.json 의 발행 기록. 파일이 없거나 깨졌으면 빈 목록."""
    if not USED_JSON.exists():
        return []
    try:
        entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("url")]


def pick_related(published: list, category: str, topic: str, limit: int = RELATED_LINK_COUNT) -> list:
    """붙일 내부 링크를 고른다.

    같은 카테고리의 최근 글을 먼저 쓰고 모자라면 다른 카테고리에서 채운다.
    지금 쓰고 있는 주제 자신은 제외한다.
    """
    def recency(entry):
        return entry.get("date", "")

    same = [e for e in published if e.get("category") == category and e.get("topic") != topic]
    other = [e for e in published if e.get("category") != category and e.get("topic") != topic]

    picked, seen = [], set()
    for entry in sorted(same, key=recency, reverse=True) + sorted(other, key=recency, reverse=True):
        url = entry["url"]
        if url in seen:
            continue
        seen.add(url)
        picked.append(entry)
        if len(picked) >= limit:
            break
    return picked


# --- 렌더링 -------------------------------------------------------------------


def _esc(text) -> str:
    """LLM이 돌려준 문자열을 HTML 에 넣기 안전하게 만든다.

    이전 버전은 이스케이프 없이 f-string 으로 이어 붙였다. 본문에 '<' 나 '&'
    가 하나만 들어가도 그 뒤 마크업이 깨져서, 반쯤 부서진 페이지가 그대로
    발행됐다. 부서진 페이지는 심사에서 '가치가 낮은 화면'으로 읽힌다.
    """
    return html.escape(str(text or "").strip(), quote=False)


def render_html(post: dict, related: list, notice: str = "") -> str:
    parts = []

    # 1) 핵심 요약 표. 표가 하나 있는 것만으로 '이미지도 표도 없는 벽글'에서
    #    벗어난다. 스크롤 없이 결론을 먼저 보여 주므로 독자에게도 이득이다.
    summary = [
        s for s in (post.get("summary") or [])
        if isinstance(s, dict) and s.get("label") and s.get("detail")
    ]
    if summary:
        rows = "".join(
            f'<tr><th scope="row">{_esc(s["label"])}</th><td>{_esc(s["detail"])}</td></tr>'
            for s in summary
        )
        parts.append("<h2>핵심 요약</h2>")
        parts.append(
            '<table border="1" cellpadding="8" cellspacing="0">'
            f"<tbody>{rows}</tbody></table>"
        )

    # 2) 서론
    parts.append(f"<p>{_esc(post.get('intro'))}</p>")

    # 3) 본문 섹션
    for section in post.get("sections", []):
        heading = _esc(section.get("heading"))
        body = _esc(section.get("body"))
        if not heading or not body:
            continue
        parts.append(f"<h2>{heading}</h2>")
        parts.append(f"<p>{body}</p>")
        items = [i for i in (section.get("list") or []) if str(i).strip()]
        if items:
            li = "".join(f"<li>{_esc(item)}</li>" for item in items)
            parts.append(f"<ul>{li}</ul>")

    # 4) 결론. 소제목을 고정 리터럴로 박지 않는다 — 24편의 마지막 h2 가 전부
    #    '마무리'로 같았던 것이 템플릿 판정의 직접적인 근거였다.
    conclusion_heading = _esc(post.get("conclusion_heading")) or "정리하며"
    parts.append(f"<h2>{conclusion_heading}</h2>")
    parts.append(f"<p>{_esc(post.get('conclusion'))}</p>")

    # 5) 내부 링크. 없으면 블록 자체를 생략한다 (빈 목록은 오히려 나쁘다).
    if related:
        li = "".join(
            f'<li><a href="{html.escape(str(e["url"]), quote=True)}">'
            f'{_esc(e.get("title") or e.get("topic"))}</a></li>'
            for e in related
        )
        parts.append("<h2>함께 읽으면 좋은 글</h2>")
        parts.append(f"<ul>{li}</ul>")

    # 6) 카테고리 고지 한 줄
    if notice:
        parts.append(f"<p><em>{_esc(notice)}</em></p>")

    return "\n".join(parts)


def prose_length(post: dict) -> int:
    """서론+섹션 본문+리스트+결론의 공백 제외 글자 수.

    소제목과 요약 표, 링크 블록은 빼고 센다. 이전 버전은 소제목과 리스트까지
    합쳐 1,200자를 셌기 때문에, 실제 산문이 1,000자 아래인 글도 통과했다.
    """
    chunks = [str(post.get("intro") or ""), str(post.get("conclusion") or "")]
    for section in post.get("sections", []):
        chunks.append(str(section.get("body") or ""))
        chunks.extend(str(i) for i in (section.get("list") or []))
    return len(re.sub(r"\s+", "", "".join(chunks)))


# --- 조립 ---------------------------------------------------------------------


def generate_post(topic: str, category_slug: str, category_label: str) -> dict:
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY가 없습니다. 얇은 콘텐츠를 발행하는 대신 중단합니다.", file=sys.stderr)
        sys.exit(1)

    try:
        post = _call_groq(topic, category_label)
    except Exception as e:
        print(f"❌ Groq API 에러: {e}", file=sys.stderr)
        sys.exit(1)

    chars = prose_length(post)
    if chars < MIN_PROSE_CHARS:
        print(
            f"⚠️ 생성된 산문이 {chars}자로 짧습니다 (최소 {MIN_PROSE_CHARS}자). 재생성합니다.",
            file=sys.stderr,
        )
        try:
            post = _call_groq(
                topic,
                category_label,
                extra_instruction=(
                    f"이전 답변이 너무 짧았습니다({chars}자). 섹션 수를 7개까지 늘리고 "
                    f"각 섹션의 설명을 더 구체적으로 써서 산문 합계가 반드시 "
                    f"{MIN_PROSE_CHARS}자를 넘도록 다시 작성하세요."
                ),
            )
        except Exception as e:
            print(f"❌ Groq API 재시도 에러: {e}", file=sys.stderr)
            sys.exit(1)
        chars = prose_length(post)

    if chars < MIN_PROSE_CHARS:
        print(
            f"❌ 재시도 후에도 산문이 {chars}자로 기준({MIN_PROSE_CHARS}자) 미달입니다. "
            "정책 위반 재발을 막기 위해 발행하지 않고 중단합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    published = load_published()
    related = pick_related(published, category_slug, topic)
    if published and not related:
        print("⚠️ 붙일 내부 링크를 찾지 못했습니다.", file=sys.stderr)

    content = render_html(post, related, CATEGORY_NOTICE.get(category_slug, ""))

    tags = [str(t).strip() for t in (post.get("tags") or []) if str(t).strip()]
    if category_label not in tags:
        tags.insert(0, category_label)

    return {
        "title": str(post.get("title") or "").strip(),
        "meta_description": str(post.get("meta_description") or "").strip(),
        "content": content,
        "tags": tags,
        "category": category_label,
        "category_slug": category_slug,
        "topic": topic,
        "prose_chars": chars,
        "char_count": quality.text_length(content),
        "related_urls": [e["url"] for e in related],
        "generated_at": datetime.now().isoformat(),
    }


def main():
    topic_data = json.loads(sys.stdin.read())
    topic = topic_data["topic"]
    slug = topic_data["category"]
    label = topic_data["category_label"]

    print(f"✍️ 글 생성 중: [{label}] {topic}", file=sys.stderr)
    post = generate_post(topic, slug, label)
    print(
        f"   산문 {post['prose_chars']}자 · 렌더 {post['char_count']}자 · "
        f"내부링크 {len(post['related_urls'])}개",
        file=sys.stderr,
    )

    print(json.dumps(post, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
