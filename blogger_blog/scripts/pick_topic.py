#!/usr/bin/env python3
"""
발행할 블로그 주제 선정

- data/topics.csv 에서 후보를 읽고, data/used_topics.json 에 이미
  발행한 주제를 확인해 아직 안 쓴 주제 중 하나를 무작위로 고른다.
- 후보가 전부 소진되면 카테고리 씨앗 문구를 Groq 에 넘겨 새 세부 주제를
  만들고, 이미 발행한 주제와 겹치지 않는 것만 채택한다. 같은 주제를 다시
  쓰면 애드센스 심사에서 중복 콘텐츠로 불리하므로, 재사용은 생성까지
  실패했을 때의 마지막 수단으로만 남겨둔다.
"""

import csv
import json
import os
import random
import re
import sys
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOPICS_CSV = DATA_DIR / "topics.csv"
USED_JSON = DATA_DIR / "used_topics.json"

CATEGORY_LABELS = {
    "finance": "재테크",
    "health": "건강",
    "tech": "IT/생활꿀팁",
    "life": "생활정보",
    "self_dev": "자기계발",
}

# topics.csv 가 소진됐을 때 새 주제를 만들어내기 위한 카테고리별 범위 설명.
# 이 문구 자체가 글의 주제가 되는 게 아니라, "이 범위 안에서 구체적인 주제를
# 지어내라"는 지시의 재료로만 쓰인다.
CATEGORY_SEEDS = {
    "finance": "재테크·절세·세무 등 경제적 자립에 도움 되는 실용 금융 정보",
    "health": "생활 속 건강 관리와 운동에 관한 실용 상식",
    "tech": "국내외 최신 실용 IT 기술 트렌드와 생활 IT 꿀팁",
    "life": "부동산·청약·주거 등 실생활에 도움 되는 생활정보",
    "self_dev": "학습법·커리어·습관 등 자기계발에 관한 실용 정보",
}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "")
GROQ_MODEL_CANDIDATES = [GROQ_MODEL] if GROQ_MODEL else [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]


def _normalize(text: str) -> str:
    """중복 판정용 정규화. 띄어쓰기·문장부호 차이만 다른 주제를 같은 것으로 본다."""
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def load_topics(category: str | None) -> list[dict]:
    with TOPICS_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if category:
        rows = [r for r in rows if r["category"] == category]
    if not rows:
        raise SystemExit(f"❌ '{category}' 카테고리에 해당하는 주제가 없습니다.")
    return rows


def load_used_topics() -> set[str]:
    if not USED_JSON.exists():
        return set()
    try:
        entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {e["topic"] for e in entries if "topic" in e}


def _generate_candidates(category_label: str, seed: str, avoid: list[str]) -> list[str]:
    """Groq 에 새 세부 주제 후보를 요청한다. 실패하면 빈 목록을 돌려준다."""
    # 이미 쓴 주제를 전부 넣으면 프롬프트가 비대해지므로 일부만 추린다.
    recent = avoid[-40:]
    avoid_block = "\n".join("- " + t for t in recent) if recent else "- (없음)"
    prompt = f"""'{category_label}' 분야의 한국어 블로그 글 주제를 8개 지어주세요.

분야 설명: {seed}

조건:
1. 각 주제는 글 한 편으로 쓸 수 있을 만큼 구체적일 것.
   나쁜 예: "건강에 좋은 생활 습관" (너무 포괄적)
   좋은 예: "혈당 스파이크 줄이는 식사 순서"
2. 아래 이미 다룬 주제와 겹치지 않을 것:
{avoid_block}
3. 제목이 아니라 주제만. 물음표·느낌표·따옴표는 넣지 말 것.
4. JSON 배열로만 답할 것. 예: ["주제1", "주제2"]"""

    for model in GROQ_MODEL_CANDIDATES:
        try:
            response = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.9,
                    "max_tokens": 800,
                },
                timeout=60,
            )
            if response.status_code == 404:
                print(
                    f"⚠️ 모델 '{model}' 을(를) 찾을 수 없습니다(404). 다음 후보로 시도합니다.",
                    file=sys.stderr,
                )
                continue
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"⚠️ 주제 생성 실패({model}): {e}", file=sys.stderr)
            continue

        # 설명 문장이 앞뒤에 붙어 나오는 경우가 있어 배열 부분만 떼어낸다.
        match = re.search(r"\[.*\]", content, re.S)
        if not match:
            continue
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        return [str(t).strip() for t in items if str(t).strip()]

    return []


def generate_topic(
    category_label: str, seed: str, used: set[str], known: set[str]
) -> str | None:
    """이미 쓴 주제·기존 목록과 겹치지 않는 새 주제 하나를 만들어 돌려준다."""
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY가 없어 새 주제를 생성할 수 없습니다.", file=sys.stderr)
        return None

    taken = {_normalize(t) for t in used | known}
    for attempt in range(2):
        for candidate in _generate_candidates(category_label, seed, sorted(used)):
            if _normalize(candidate) not in taken:
                print(f"🆕 새 주제를 생성했습니다: {candidate}", file=sys.stderr)
                return candidate
        print(
            f"⚠️ 생성된 후보가 모두 기존 주제와 겹칩니다 ({attempt + 1}/2).",
            file=sys.stderr,
        )
    return None


def _emit(category: str, topic: str) -> None:
    print(json.dumps(
        {
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "topic": topic,
        },
        ensure_ascii=False,
    ))


def main():
    category = sys.argv[1] if len(sys.argv) > 1 else None

    candidates = load_topics(category)
    used = load_used_topics()
    used_norm = {_normalize(t) for t in used}

    unused = [r for r in candidates if _normalize(r["topic"]) not in used_norm]
    if unused:
        chosen = random.choice(unused)
        _emit(chosen["category"], chosen["topic"])
        return

    # 여기부터는 후보 소진. 재사용 대신 새 주제를 만들어 본다.
    print("ℹ️ 목록의 주제를 모두 발행했습니다. 새 주제 생성을 시도합니다.", file=sys.stderr)
    slug = category or random.choice(sorted({r["category"] for r in candidates}))
    label = CATEGORY_LABELS.get(slug, slug)
    known = {r["topic"] for r in load_topics(None)}

    fresh = generate_topic(label, CATEGORY_SEEDS.get(slug, label), used, known)
    if fresh:
        _emit(slug, fresh)
        return

    # 생성까지 실패한 경우에만 재사용. generate_post.py 가 매번 다른 각도로
    # 쓰긴 하지만 중복 위험이 있으므로 경고를 남긴다.
    print(
        "⚠️ 새 주제 생성에 실패해 기존 주제를 재사용합니다. "
        "topics.csv에 주제를 추가하는 것을 권장합니다.",
        file=sys.stderr,
    )
    chosen = random.choice(candidates)
    _emit(chosen["category"], chosen["topic"])


if __name__ == "__main__":
    main()
