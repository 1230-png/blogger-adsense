#!/usr/bin/env python3
"""발행된 글의 본문 텍스트를 그대로 찍어낸다.

`audit_blog.py` 는 글자 수·소제목 수 같은 **지표**만 본다. 그런데 애드센스
심사에서 실제로 문제가 되는 것은 "이 글이 읽을 가치가 있는가"이고, 그건
지표로 환산되지 않는다. 지표가 전부 초록불인데도 반려가 유지된다면 본문을
사람이 직접 읽어야 한다. 이 스크립트는 그 읽을거리를 꺼내 온다.

    python blogger_blog/scripts/dump_post.py --count 3
    python blogger_blog/scripts/dump_post.py --url https://soo-c9.blogspot.com/...

네트워크에서 블로그에 직접 접근할 수 없는 환경(사내 프록시 등)에서도
Blogger API 로 본문을 가져올 수 있다는 점이 이 스크립트의 존재 이유다.
"""

import argparse
import sys

import blogger_api
import quality


def main():
    parser = argparse.ArgumentParser(description="발행된 글 본문을 출력")
    parser.add_argument("--count", type=int, default=3, help="최신순으로 몇 편을 찍을지")
    parser.add_argument("--url", help="특정 글 하나만 (주소로 지정)")
    parser.add_argument(
        "--chars", type=int, default=4000, help="글마다 출력할 최대 글자 수"
    )
    args = parser.parse_args()

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    posts = blogger_api.list_posts(service, blog_id)

    if args.url:
        posts = [p for p in posts if p.get("url") == args.url]
        if not posts:
            print(f"❌ 그 주소의 글을 찾지 못했습니다: {args.url}", file=sys.stderr)
            sys.exit(1)
    else:
        posts = posts[: args.count]

    for i, post in enumerate(posts, 1):
        text = quality.block_text(post.get("content") or "")
        print("=" * 70)
        print(f"[{i}] {post.get('title')}")
        print(post.get("url", ""))
        print(f"라벨: {', '.join(post.get('labels') or []) or '(없음)'}")
        print("=" * 70)
        print(text[: args.chars])
        if len(text) > args.chars:
            print(f"... (이하 {len(text) - args.chars}자 생략)")
        print()


if __name__ == "__main__":
    main()
