#!/usr/bin/env python3
"""이미 발행된 글에 '함께 읽으면 좋은 글' 내부 링크 블록을 넣는다.

감사 결과 발행된 24편이 **전부** 내부 링크 0개였다. 각 글이 서로 오가지
않는 고립된 페이지라는 뜻이고, 애드센스가 "고유 콘텐츠와 우수한 사용자
환경"을 볼 때 불리하게 작용한다.

`generate_post.py` 는 앞으로 쓰는 글에만 링크를 넣는다. 이미 올라간 글은
손대지 않으므로, 글을 몇 편으로 추리든 남는 글은 계속 링크가 0개다.
이 스크립트가 그 구멍을 메운다.

    python blogger_blog/scripts/add_internal_links.py            # 미리보기
    python blogger_blog/scripts/add_internal_links.py --apply    # 실제로 수정

여러 번 돌려도 안전하다. 이미 블록이 있는 글은 건너뛴다.

## --refresh: 죽은 링크 정리

글을 초안으로 내리면(unpublish_posts.py / prune_posts.py) 그 글을 링크하던
다른 글의 링크가 404가 된다. 404 페이지는 "게시자 콘텐츠가 없는 화면"이라,
애드센스가 두 번째로 지적했던 바로 그 문제로 되돌아간다.

`--refresh` 는 기존 블록을 지우고 **지금 공개된 글로만** 다시 만든다.

    python blogger_blog/scripts/add_internal_links.py --refresh --apply

결과가 기존과 같은 글은 API 호출도 하지 않으므로, 글을 내린 직후에 그냥
돌리면 된다.

## 링크를 고르는 방식

같은 라벨(카테고리)을 공유하는 글을 먼저, 모자라면 최근 글로 채운다.
서로가 서로를 링크하도록 대칭으로 넣지는 않는다 — 두 글이 서로만 가리키는
고립된 쌍이 생기면 링크가 있으나 마나이기 때문이다.
"""

import argparse
import html
import re
import sys

import blogger_api
import quality

# generate_post.py 가 새 글에 쓰는 것과 같은 제목이어야 한다. 다르면 같은
# 블로그 안에서 블록 이름이 두 가지가 되고, 재실행 시 중복 삽입도 생긴다.
BLOCK_HEADING = "함께 읽으면 좋은 글"
LINK_COUNT = 3

# 블록 전체(소제목 + 목록)를 통째로 잡는다. 글 끝이 아니라 카테고리 고지
# 앞에 있는 경우가 있어서, 잘라낸 자리에 그대로 되넣을 수 있어야 한다.
BLOCK_RE = re.compile(
    r"\s*<h2>\s*" + re.escape(BLOCK_HEADING) + r"\s*</h2>\s*<ul>.*?</ul>",
    re.DOTALL,
)


def has_block(content: str) -> bool:
    return BLOCK_HEADING in (content or "")


def replace_block(content: str, block: str) -> str:
    """기존 블록이 있으면 그 자리에서 바꾸고, 없으면 끝에 붙인다.

    re.sub 의 치환 문자열은 백슬래시를 이스케이프로 해석하므로, 링크 제목에
    '\\' 가 하나라도 있으면 깨진다. 그래서 람다로 넘긴다.
    """
    content = content or ""
    if BLOCK_RE.search(content):
        return BLOCK_RE.sub(lambda _: block, content, count=1)
    return content + block


def dead_links(content: str, live_urls: set, host: str) -> list:
    """본문의 내부 링크 중 지금 공개된 글이 아닌 주소."""
    info = quality.extract(content or "")
    out = []
    for href in info.links:
        if not (href.startswith("/") or (host and host.lower() in href.lower())):
            continue
        if href.rstrip("/") not in live_urls:
            out.append(href)
    return out


def render_block(related: list) -> str:
    items = "".join(
        f'<li><a href="{html.escape(p["url"], quote=True)}">'
        f'{html.escape(p.get("title", "").strip(), quote=False)}</a></li>'
        for p in related
    )
    return f"\n<h2>{BLOCK_HEADING}</h2>\n<ul>{items}</ul>"


def update_body(post: dict, new_content: str) -> dict:
    """posts().update() 에 보낼 본문.

    ⚠️ Blogger 의 update 는 PATCH 가 아니라 **리소스 전체 교체**다. 보내지 않은
    필드는 지워진다. 실제로 이 스크립트의 첫 판이 title/content 만 보내는 바람에
    발행된 12편의 라벨이 전부 날아갔다. 유지해야 하는 필드는 반드시 여기서
    되실어 보낸다.
    """
    body = {
        "kind": "blogger#post",
        "title": post.get("title", ""),
        "content": new_content,
        "labels": list(post.get("labels") or []),
    }
    if post.get("customMetaData"):
        body["customMetaData"] = post["customMetaData"]
    return body


def pick_related(post: dict, others: list, limit: int = LINK_COUNT) -> list:
    """같은 라벨을 공유하는 글 우선, 모자라면 최신순으로 채운다."""
    labels = set(post.get("labels") or [])
    candidates = [p for p in others if p.get("id") != post.get("id") and p.get("url")]

    def sort_key(p):
        shared = len(labels & set(p.get("labels") or []))
        # 라벨이 많이 겹칠수록, 그다음으로 최근일수록 앞에 온다.
        return (-shared, p.get("published", ""))

    return sorted(candidates, key=sort_key, reverse=False)[:limit]


def main():
    parser = argparse.ArgumentParser(description="발행된 글에 내부 링크 블록 추가")
    parser.add_argument("--apply", action="store_true", help="실제로 수정한다 (없으면 미리보기)")
    parser.add_argument("--limit", type=int, default=LINK_COUNT, help="글마다 붙일 링크 수")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="기존 블록을 지금 공개된 글로 다시 만든다 (내려간 글로 가는 죽은 링크 정리)",
    )
    args = parser.parse_args()

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    blog = blogger_api.get_blog(service, blog_id)
    host = blogger_api.blog_host(blog)

    posts = blogger_api.list_posts(service, blog_id)
    print(f"📥 발행된 글 {len(posts)}편.", file=sys.stderr)

    if len(posts) < 2:
        print("ℹ️ 링크할 대상이 없습니다 (글이 2편 미만).", file=sys.stderr)
        return

    # 고정 페이지(소개·문의 등)로 가는 링크도 살아 있는 링크다. 글만 넣고
    # 판정하면 멀쩡한 페이지 링크를 죽은 링크로 잘못 세게 된다.
    live_urls = {p["url"].rstrip("/") for p in posts if p.get("url")}
    live_urls |= {
        p["url"].rstrip("/")
        for p in blogger_api.live_pages(service, blog_id)
        if p.get("url")
    }

    changed, skipped, failed = 0, 0, []

    for post in posts:
        content = post.get("content") or ""
        title = post.get("title", "")

        if has_block(content) and not args.refresh:
            skipped += 1
            continue

        # 이미 다른 방식으로 내부 링크가 있는 글은 건드리지 않는다. --refresh
        # 일 때는 그 링크가 아직 살아 있는지가 관건이므로 죽은 것만 본다.
        info = quality.extract(content)
        internal = [h for h in info.links if h.startswith("/") or host.lower() in h.lower()]
        if args.refresh:
            if not has_block(content) and internal and not dead_links(content, live_urls, host):
                skipped += 1
                continue
        elif internal:
            skipped += 1
            continue

        related = pick_related(post, posts, args.limit)
        if not related:
            skipped += 1
            continue

        block = render_block(related)
        new_content = replace_block(content, block) if args.refresh else content + block

        if new_content == content:
            skipped += 1
            continue

        if not args.apply:
            dead = dead_links(content, live_urls, host) if args.refresh else []
            note = f" (죽은 링크 {len(dead)}건 정리)" if dead else ""
            print(f"[미리보기] {title} → {[p['title'] for p in related]}{note}", file=sys.stderr)
            changed += 1
            continue

        try:
            service.posts().update(
                blogId=blog_id,
                postId=post["id"],
                body=update_body(post, new_content),
            ).execute()
            changed += 1
            print(f"🔗 링크 추가: {title}", file=sys.stderr)
        except Exception as e:
            failed.append((title, str(e)))
            print(f"❌ 실패: {title} — {e}", file=sys.stderr)

    verb = "수정 대상" if not args.apply else "수정 완료"
    print(
        f"\n{verb} {changed}편, 건너뜀 {skipped}편"
        + (f", 실패 {len(failed)}편" if failed else ""),
        file=sys.stderr,
    )
    if not args.apply and changed:
        print("ℹ️ 미리보기입니다. 실제로 넣으려면 --apply 를 붙이세요.", file=sys.stderr)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
