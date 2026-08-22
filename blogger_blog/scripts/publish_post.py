#!/usr/bin/env python3
"""
Google Blogger API v3로 글 발행

기존 YouTube 업로드 스크립트(growth_tips/scripts/upload_shorts.py)와 동일한
구글 OAuth refresh_token 방식을 사용한다.

필요 환경변수:
- BLOGGER_REFRESH_TOKEN, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET
  : get_blogger_token.py 로 발급
- BLOGGER_BLOG_ID
  : Blogger 관리 화면 URL(blogger.com/blog/posts/<이 숫자>)에서 확인
- BLOGGER_LABELS_EXTRA (선택) : 모든 글에 공통으로 붙일 라벨(콤마 구분)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USED_JSON = DATA_DIR / "used_topics.json"


def get_blogger_client():
    refresh_token = os.environ.get("BLOGGER_REFRESH_TOKEN")
    client_id = os.environ.get("BLOGGER_CLIENT_ID")
    client_secret = os.environ.get("BLOGGER_CLIENT_SECRET")

    if not refresh_token or not client_id or not client_secret:
        print(
            "❌ BLOGGER_REFRESH_TOKEN / BLOGGER_CLIENT_ID / BLOGGER_CLIENT_SECRET "
            "환경변수가 필요합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    credentials.refresh(google.auth.transport.requests.Request())

    return build("blogger", "v3", credentials=credentials)


def publish(post: dict) -> dict:
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        print("❌ BLOGGER_BLOG_ID 환경변수가 필요합니다.", file=sys.stderr)
        sys.exit(1)

    service = get_blogger_client()

    labels = list(post.get("tags", []))
    extra_labels = os.environ.get("BLOGGER_LABELS_EXTRA", "")
    if extra_labels:
        labels += [t.strip() for t in extra_labels.split(",") if t.strip()]

    body = {
        "kind": "blogger#post",
        "title": post["title"],
        "content": post["content"],
        "labels": labels,
    }

    try:
        result = service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()
    except Exception as e:
        print(f"❌ Blogger 발행 실패: {e}", file=sys.stderr)
        sys.exit(1)

    return {
        "post_id": result.get("id"),
        "url": result.get("url"),
        "title": post["title"],
        "topic": post["topic"],
        "category": post.get("category_slug", post.get("category")),
        "char_count": post.get("char_count"),
        "published_at": datetime.now().isoformat(),
    }


def record_used_topic(entry: dict) -> None:
    entries = []
    if USED_JSON.exists():
        try:
            entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            entries = []
    entries.append(
        {
            "topic": entry["topic"],
            "category": entry["category"],
            "date": entry["published_at"][:10],
            "url": entry["url"],
        }
    )
    USED_JSON.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    post_json = sys.stdin.read()
    post = json.loads(post_json)

    result = publish(post)
    record_used_topic(result)

    print(f"✅ 발행 완료: {result['url']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
