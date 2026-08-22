#!/usr/bin/env python3
"""
발행할 블로그 주제 선정

- data/topics.csv 에서 후보를 읽고, data/used_topics.json 에 이미
  발행한 주제를 확인해 아직 안 쓴 주제 중 하나를 무작위로 고른다.
- 특정 카테고리가 전부 소진되면 재사용하되(무한정 쌓아둘 수는 없으므로),
  generate_post.py 가 매번 새로운 각도로 글을 쓰기 때문에 완전히 같은
  글이 중복 발행되지는 않는다.
"""

import csv
import json
import random
import sys
from pathlib import Path

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


def main():
    category = sys.argv[1] if len(sys.argv) > 1 else None

    candidates = load_topics(category)
    used = load_used_topics()

    unused = [r for r in candidates if r["topic"] not in used]
    if unused:
        chosen = random.choice(unused)
    else:
        print(
            "⚠️ 해당 카테고리의 모든 주제를 이미 발행했습니다. 무작위로 재사용합니다 "
            "(새로운 관점으로 재작성됩니다).",
            file=sys.stderr,
        )
        chosen = random.choice(candidates)

    result = {
        "category": chosen["category"],
        "category_label": CATEGORY_LABELS.get(chosen["category"], chosen["category"]),
        "topic": chosen["topic"],
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
