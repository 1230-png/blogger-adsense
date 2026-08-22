#!/usr/bin/env python3
"""
Groq API를 사용한 Blogger 블로그 글 자동 생성

애드센스 재심사 사유가 "가치가 별로 없는 콘텐츠"였기 때문에, 이 스크립트는
얇은 글을 대량으로 찍어내는 대신 최소 분량/구조 요건을 강제한다:

- 서론 + 4~6개 소제목 섹션(각 섹션은 실질적인 정보 포함) + 결론
- 순수 본문 텍스트 최소 1,200자 (모자라면 한 번 더 길게 요청, 그래도
  모자라면 실패 처리하고 발행하지 않는다 — 미달 콘텐츠를 발행하는 것 자체가
  원래 문제를 되풀이하는 것이기 때문)
- LLM에는 마크업이 아니라 구조화된 JSON(제목/섹션/리스트)을 받아서
  파이썬에서 HTML로 조립한다 (LLM이 HTML을 JSON 문자열 안에 통째로 넣으면
  따옴표 이스케이프가 깨져 파싱 실패하는 경우가 잦기 때문)
"""

import json
import os
import sys
from datetime import datetime

import requests

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Groq 무료 티어는 모델을 주기적으로 퇴역시킨다(llama-3.3-70b-versatile 는
# 2026-08-16 퇴역했고, 그 뒤로는 이 엔드포인트가 404를 돌려준다). 모델 하나가
# 사라져도 발행이 멈추지 않도록 후보 목록을 두고 404면 다음으로 넘어간다.
# GROQ_MODEL 을 지정하면 그 모델만 사용한다.
GROQ_MODEL = os.getenv("GROQ_MODEL", "")
GROQ_MODEL_CANDIDATES = [GROQ_MODEL] if GROQ_MODEL else [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

MIN_BODY_CHARS = 1200

SYSTEM_MESSAGE = """당신은 한국어 블로그의 전문 에디터입니다. 검색 유입과
실제 독자에게 도움이 되는, 광고 승인 심사를 통과할 수준의 고유하고
실용적인 글을 씁니다.

요구사항:
1. 요약이나 짜깁기가 아니라 실제로 도움이 되는 구체적인 정보/방법/수치를 담을 것
2. 서론(왜 이 주제가 중요한지) - 소제목 4~6개(각 소제목마다 구체적인 설명,
   필요하면 실천 팁 리스트) - 결론(요약 및 다음 행동 제안) 구조를 지킬 것
3. 과장 광고, 근거 없는 의학/재무적 단정 표현은 피하고 일반적인 정보 제공
   수준으로 작성할 것
4. 순수 본문 텍스트 합계가 1,200자 이상이 되도록 충분히 상세하게 쓸 것
5. 아래 JSON 스키마 그대로만 반환할 것 (마크다운 코드블록이나 다른 텍스트 금지)

{
  "title": "SEO에 유리한 매력적인 제목",
  "meta_description": "검색결과에 보일 100자 내외 요약",
  "intro": "서론 2~4문장",
  "sections": [
    {"heading": "소제목", "body": "본문 설명 (3~5문장)", "list": ["실천 팁 1", "실천 팁 2"]}
  ],
  "conclusion": "결론 2~4문장",
  "tags": ["태그1", "태그2", "태그3"]
}

"list" 필드는 필요 없는 섹션이면 빈 배열로 두어도 됩니다."""


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
                "max_tokens": 3000,
            },
            timeout=60,
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


def _body_char_count(post: dict) -> int:
    total = len(post.get("intro", "")) + len(post.get("conclusion", ""))
    for section in post.get("sections", []):
        total += len(section.get("heading", "")) + len(section.get("body", ""))
        total += sum(len(item) for item in section.get("list", []))
    return total


def _render_html(post: dict) -> str:
    parts = [f"<p>{post['intro']}</p>"]
    for section in post.get("sections", []):
        parts.append(f"<h2>{section['heading']}</h2>")
        parts.append(f"<p>{section['body']}</p>")
        items = section.get("list") or []
        if items:
            li = "".join(f"<li>{item}</li>" for item in items)
            parts.append(f"<ul>{li}</ul>")
    parts.append("<h2>마무리</h2>")
    parts.append(f"<p>{post['conclusion']}</p>")
    return "\n".join(parts)


def generate_post(topic: str, category_label: str) -> dict:
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY가 없습니다. 얇은 콘텐츠를 발행하는 대신 중단합니다.", file=sys.stderr)
        sys.exit(1)

    try:
        post = _call_groq(topic, category_label)
    except Exception as e:
        print(f"❌ Groq API 에러: {e}", file=sys.stderr)
        sys.exit(1)

    char_count = _body_char_count(post)
    if char_count < MIN_BODY_CHARS:
        print(
            f"⚠️ 생성된 본문이 {char_count}자로 너무 짧습니다 (최소 {MIN_BODY_CHARS}자). "
            "더 길게 재생성을 시도합니다.",
            file=sys.stderr,
        )
        try:
            post = _call_groq(
                topic,
                category_label,
                extra_instruction=(
                    f"이전 답변이 너무 짧았습니다({char_count}자). 각 섹션의 설명을 더 "
                    f"구체적으로 늘려서 본문 텍스트 합계가 반드시 {MIN_BODY_CHARS}자를 "
                    "넘도록 다시 작성하세요."
                ),
            )
        except Exception as e:
            print(f"❌ Groq API 재시도 에러: {e}", file=sys.stderr)
            sys.exit(1)
        char_count = _body_char_count(post)

    if char_count < MIN_BODY_CHARS:
        print(
            f"❌ 재시도 후에도 본문이 {char_count}자로 최소 기준({MIN_BODY_CHARS}자) "
            "미달입니다. 애드센스 정책 위반 재발을 막기 위해 발행하지 않고 중단합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    return {
        "title": post["title"],
        "meta_description": post.get("meta_description", ""),
        "content": _render_html(post),
        "tags": post.get("tags", []),
        "category": category_label,
        "topic": topic,
        "char_count": char_count,
        "generated_at": datetime.now().isoformat(),
    }


def main():
    topic_json = sys.stdin.read()
    topic_data = json.loads(topic_json)

    print(f"✍️ 글 생성 중: [{topic_data['category_label']}] {topic_data['topic']}", file=sys.stderr)

    post = generate_post(topic_data["topic"], topic_data["category_label"])
    post["category_slug"] = topic_data["category"]

    print(json.dumps(post, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
