#!/usr/bin/env python3
"""Google Blogger API v3 로 글 발행.

발행 직전에 `quality.py` 의 게이트를 한 번 더 통과시킨다. generate_post.py 도
분량을 확인하지만, 그건 LLM 응답에 대한 검사고 여기서 보는 것은 **실제로
Blogger 에 올라갈 HTML** 이다. 감사(audit_blog.py)가 나중에 볼 대상과 정확히
같은 것을 같은 함수로 보기 때문에, "발행은 됐는데 감사에서 떨어지는" 글이
생기지 않는다.

필요 환경변수:
- BLOGGER_REFRESH_TOKEN / BLOGGER_CLIENT_ID / BLOGGER_CLIENT_SECRET / BLOGGER_BLOG_ID
  : blogger_api.py 참고
- BLOGGER_LABELS_EXTRA (선택) : 모든 글에 공통으로 붙일 라벨(콤마 구분)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import blogger_api
import quality

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USED_JSON = DATA_DIR / "used_topics.json"


def gate(post: dict, *, require_internal_link: bool) -> quality.PostReport:
    """발행 후보를 감사와 동일한 기준으로 검사한다.

    blog_host 를 넘기지 않는 이유: 내부 링크는 generate_post.py 가
    used_topics.json 에 기록된 이 블로그의 절대 URL 로 넣으므로, 호스트를
    모르면 판정할 수 없다. 그래서 아래 main() 에서 실제 호스트를 넘긴다.
    """
    return quality.check_post(
        {
            "id": "",
            "title": post.get("title", ""),
            "url": "",
            "content": post.get("content", ""),
            "labels": post.get("tags", []),
        },
        blog_host=post.get("_blog_host", ""),
        require_internal_link=require_internal_link,
    )


def publish(service, blog_id: str, post: dict, labels: list, is_draft: bool) -> dict:
    body = {
        "kind": "blogger#post",
        "title": post["title"],
        "content": post["content"],
        "labels": labels,
    }

    # meta_description 은 이전 버전에서 생성만 되고 아무 데도 쓰이지 않았다.
    # Blogger API v3 의 customMetaData 는 임의의 문자열을 보관하는 필드라,
    # 이걸 넣는다고 검색결과의 'Search Description' 이 설정된다는 보장은 없다
    # (그 값은 Blogger 관리 화면 쪽 설정이다). 그래서 여기 넣어 두기는 하되,
    # 요약이 독자에게 실제로 보이는 경로는 generate_post.py 가 본문 맨 위에
    # 넣는 '핵심 요약' 표다.
    description = post.get("meta_description")
    if description:
        body["customMetaData"] = json.dumps({"description": description}, ensure_ascii=False)

    result = service.posts().insert(blogId=blog_id, body=body, isDraft=is_draft).execute()

    return {
        "post_id": result.get("id"),
        "url": result.get("url"),
        "title": post["title"],
        "topic": post["topic"],
        "category": post.get("category_slug", post.get("category")),
        "char_count": post.get("char_count"),
        "prose_chars": post.get("prose_chars"),
        "is_draft": is_draft,
        "published_at": datetime.now().isoformat(),
    }


def record_used_topic(entry: dict) -> None:
    """발행 기록 추가.

    title 을 함께 남긴다. generate_post.py 가 다음 글에 붙일 내부 링크의 앵커
    텍스트로 쓰는데, 예전 기록에는 topic 밖에 없어 링크 문구가 어색했다.
    """
    entries = []
    if USED_JSON.exists():
        try:
            entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            entries = []
    entries.append(
        {
            "topic": entry["topic"],
            "title": entry.get("title", ""),
            "category": entry["category"],
            "date": entry["published_at"][:10],
            "url": entry["url"],
        }
    )
    USED_JSON.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Blogger 글 발행")
    parser.add_argument(
        "--draft-on-fail",
        action="store_true",
        help="품질 게이트에 걸리면 발행을 중단하는 대신 초안으로 올린다 "
             "(초안은 공개되지 않으므로 심사에 영향을 주지 않는다)",
    )
    args = parser.parse_args()

    post = json.loads(sys.stdin.read())

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    blog = blogger_api.get_blog(service, blog_id)
    post["_blog_host"] = blogger_api.blog_host(blog)

    # 이미 발행된 글이 있으면 내부 링크는 필수다. 한 편도 없는 새 블로그라면
    # 링크할 대상이 없으므로 요구하지 않는다.
    existing_count = len(blogger_api.list_posts(service, blog_id))
    report = gate(post, require_internal_link=existing_count > 0)

    for f in report.findings:
        mark = "🔴" if f.severity == quality.BLOCK else "🟡"
        print(f"{mark} {f.message}", file=sys.stderr)

    is_draft = False
    if report.blocked:
        if not args.draft_on_fail:
            print(
                "\n❌ 품질 게이트에 걸려 발행하지 않습니다. "
                "미달 콘텐츠를 올리는 것이 애드센스 반려의 원인이었습니다.",
                file=sys.stderr,
            )
            sys.exit(1)
        is_draft = True
        print("\n⚠️ 게이트 미달이라 공개 발행 대신 초안으로 올립니다.", file=sys.stderr)

    labels = list(post.get("tags", []))
    import os  # 라벨 추가 시크릿은 이 지점에서만 쓰인다

    extra_labels = os.environ.get("BLOGGER_LABELS_EXTRA", "")
    if extra_labels:
        labels += [t.strip() for t in extra_labels.split(",") if t.strip()]

    try:
        result = publish(service, blog_id, post, labels, is_draft)
    except Exception as e:
        print(f"❌ Blogger 발행 실패: {e}", file=sys.stderr)
        sys.exit(1)

    # 초안은 공개 URL 이 없으므로 발행 기록에 넣지 않는다. 넣으면 다음 글이
    # 그 URL 을 '함께 읽으면 좋은 글'로 링크했다가 죽은 링크가 된다.
    if is_draft:
        print(f"📝 초안으로 저장했습니다 (id={result['post_id']}). 손본 뒤 직접 발행하세요.", file=sys.stderr)
    else:
        record_used_topic(result)
        print(f"✅ 발행 완료: {result['url']}", file=sys.stderr)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if is_draft:
        sys.exit(1)


if __name__ == "__main__":
    main()
