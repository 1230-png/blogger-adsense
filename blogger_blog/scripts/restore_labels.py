#!/usr/bin/env python3
"""라벨이 비어 있는 발행 글에 카테고리 라벨을 되살린다.

## 왜 필요한가 (사고 경위)

`add_internal_links.py` 의 첫 판이 `posts().update()` 에 title/content 만
보냈다. Blogger 의 update 는 PATCH 가 아니라 **리소스 전체 교체**이므로,
보내지 않은 `labels` 가 전부 지워졌다. 발행 중이던 12편의 라벨이 날아갔다.

Blogger API v3 에는 글의 이전 판을 되돌리는 기능이 없다. 그래서 **원래
라벨을 그대로 복원할 수는 없다.** 복구할 수 있는 것은 `used_topics.json` 에
남아 있는 **카테고리 하나**뿐이고, LLM 이 붙였던 세부 태그(예: "청약",
"연말정산")는 되살릴 수 없다.

세부 태그가 필요하면 Blogger 관리 화면에서 직접 추가해야 한다. 이 스크립트는
최소한 카테고리 분류를 되돌려 라벨 목록 가젯과 감사의 `no_label` 지적을
해소한다.

    python blogger_blog/scripts/restore_labels.py            # 미리보기
    python blogger_blog/scripts/restore_labels.py --apply    # 실제로 복구
"""

import argparse
import json
import sys
from pathlib import Path

import blogger_api

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USED_JSON = DATA_DIR / "used_topics.json"

# pick_topic.py 의 CATEGORY_LABELS 와 같아야 한다. 다르면 같은 분류에 두
# 가지 라벨이 생겨 라벨 목록이 갈라진다.
CATEGORY_LABELS = {
    "finance": "재테크",
    "health": "건강",
    "tech": "IT/생활꿀팁",
    "life": "생활정보",
    "self_dev": "자기계발",
}


def load_url_labels() -> dict:
    """발행 기록에서 {글 주소: 카테고리 라벨} 을 만든다."""
    if not USED_JSON.exists():
        return {}
    try:
        entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    mapping = {}
    for entry in entries:
        url, category = entry.get("url"), entry.get("category")
        label = CATEGORY_LABELS.get(category, category)
        if url and label:
            mapping[url] = label
    return mapping


def update_body(post: dict, labels: list) -> dict:
    """전체 교체 방식이므로 유지할 필드를 모두 되실어 보낸다.

    이 함수가 존재하는 이유가 곧 이 스크립트가 필요해진 이유다.
    """
    body = {
        "kind": "blogger#post",
        "title": post.get("title", ""),
        "content": post.get("content", ""),
        "labels": list(labels),
    }
    if post.get("customMetaData"):
        body["customMetaData"] = post["customMetaData"]
    return body


def main():
    parser = argparse.ArgumentParser(description="라벨이 비어 있는 글에 카테고리 라벨 복구")
    parser.add_argument("--apply", action="store_true", help="실제로 수정한다 (없으면 미리보기)")
    args = parser.parse_args()

    url_labels = load_url_labels()
    if not url_labels:
        print("❌ used_topics.json 에서 카테고리를 읽지 못했습니다.", file=sys.stderr)
        sys.exit(1)

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    posts = blogger_api.list_posts(service, blog_id)

    print(f"📥 발행된 글 {len(posts)}편, 기록에서 찾은 카테고리 {len(url_labels)}건.", file=sys.stderr)

    fixed, skipped, unknown, failed = 0, 0, [], []

    for post in posts:
        # 라벨이 남아 있는 글은 건드리지 않는다. 덮어쓰면 멀쩡한 세부 태그까지
        # 카테고리 하나로 줄어든다.
        if post.get("labels"):
            skipped += 1
            continue

        label = url_labels.get(post.get("url", ""))
        if not label:
            unknown.append(post.get("title", ""))
            continue

        if not args.apply:
            print(f"[미리보기] {post.get('title')} → {label}", file=sys.stderr)
            fixed += 1
            continue

        try:
            service.posts().update(
                blogId=blog_id, postId=post["id"], body=update_body(post, [label])
            ).execute()
            fixed += 1
            print(f"🏷️ 라벨 복구: {post.get('title')} → {label}", file=sys.stderr)
        except Exception as e:
            failed.append((post.get("title", ""), str(e)))
            print(f"❌ 실패: {post.get('title')} — {e}", file=sys.stderr)

    verb = "복구 대상" if not args.apply else "복구 완료"
    print(f"\n{verb} {fixed}편, 라벨이 이미 있어 건너뜀 {skipped}편", file=sys.stderr)
    if unknown:
        print(
            f"⚠️ 기록에 없어 카테고리를 알 수 없는 글 {len(unknown)}편: "
            + ", ".join(unknown[:5]),
            file=sys.stderr,
        )
    print(
        "ℹ️ 되살린 것은 카테고리 라벨 하나뿐입니다. 원래 붙어 있던 세부 태그는\n"
        "   Blogger API 로 복원할 수 없으므로, 필요하면 관리 화면에서 직접 추가하세요.",
        file=sys.stderr,
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
