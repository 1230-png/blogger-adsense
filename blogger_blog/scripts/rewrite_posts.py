#!/usr/bin/env python3
"""게이트에 걸린 기존 글의 본문을, 고친 프롬프트로 다시 쓴다.

두 가지 차단 사유를 다룬다 (REWRITABLE_CODES).

- `unverified_figures` — 자료 없이 지어낸 수치. 단, 금액·연령·법령 조항이
  뼈대인 글은 unpublish_posts.py 로 내린다 (quality.HARD_CLAIM_KINDS 주석 참고).
  여기서 다루는 것은 비율(%)·기간처럼 **수치를 빼도 글이 성립하는** 경우다.
- `thin_body` — 분량 미달. 더 길게 쓰면 풀린다.

    python blogger_blog/scripts/rewrite_posts.py                 # 미리보기
    python blogger_blog/scripts/rewrite_posts.py --apply         # 실제로 교체

## 왜 내리지 않고 다시 쓰는가

"빠르게 걸으면 칼로리 소모가 60% 늘어난다"에서 60%만 빼면 문장이 남지 않지만,
"느린 걸음보다 뚜렷하게 늘어난다"로 고쳐 쓰면 글의 값어치는 그대로다. 게다가
이런 글까지 전부 내리면 발행 글이 권장 최소치 아래로 떨어져, 이번에는 "콘텐츠가
부족한 사이트"로 반려될 차례가 된다.

## 무엇을 보존하는가

제목과 글 주소(URL), 라벨, customMetaData 를 그대로 둔다. 제목을 LLM 이 새로
지으면 주소와 제목이 어긋나고, 다른 글이 걸어 둔 내부 링크의 앵커 텍스트도
틀리게 된다. 그래서 **본문만** 바꾼다.

## 안전장치

새 본문이 품질 게이트를 통과하지 못하면 **원본을 그대로 둔다.** 즉 이 스크립트가
글을 더 나쁘게 만드는 경우는 없다. 통과한 글만 교체한다.
"""

import argparse
import sys
import time

import add_internal_links
import blogger_api
import generate_post
import pick_topic
import quality
import unpublish_posts

# 라벨에서 카테고리 슬러그를 되찾기 위한 역방향 표. generate_post 의 카테고리
# 고지(CATEGORY_NOTICE)와 내부 링크 선택이 슬러그 기준이라 필요하다.
LABEL_TO_SLUG = {label: slug for slug, label in pick_topic.CATEGORY_LABELS.items()}
FALLBACK_SLUG = "life"

# LLM 호출 사이 간격(초). Groq 무료 티어의 분당 요청 제한에 걸리지 않게 한다.
CALL_INTERVAL = 3.0

# 한 글에 허용하는 생성 시도 횟수. 첫 응답이 게이트에 걸리면 한 번 더 부탁한다.
MAX_ATTEMPTS = 2

# 본문을 다시 써서 풀 수 있는 차단 사유.
#
# - unverified_figures: 수치를 빼고 쓰면 된다 (금액이 뼈대인 글은 아래 min_hard
#   로 걸러져 unpublish_posts.py 쪽으로 간다)
# - thin_body: 더 길게 쓰면 된다
#
# 여기 없는 사유(예: templated — 다른 글과 문장이 겹침)가 섞여 있으면 다시
# 써도 같은 이유로 또 막히므로 건너뛴다. 그런 글은 사람이 봐야 한다.
REWRITABLE_CODES = frozenset({"unverified_figures", "thin_body"})

BASE_INSTRUCTION = "이 주제로 이미 발행된 글이 있는데, 아래 이유로 다시 씁니다."

# 차단 사유별로 덧붙이는 지시. 분량이 모자란 글에 "수치를 쓰지 말라"고만 하면
# 모델은 더 짧게 쓰는 쪽으로 움직인다.
CODE_INSTRUCTIONS = {
    "unverified_figures": (
        "자료 없이 지어낸 비율·기간 수치가 섞여 있습니다. 같은 주제를 다루되 "
        "**구체적인 비율·기간·금액 수치를 쓰지 마십시오.** '약 몇 퍼센트'처럼 "
        "얼버무리는 것도 안 됩니다. 수치 대신 방향(늘어난다/줄어든다), 판단 "
        "기준, 확인 방법, 흔한 실수를 구체적으로 쓰십시오."
    ),
    "thin_body": (
        "본문이 짧습니다. 섹션을 7개까지 늘리고 각 섹션의 설명을 더 풀어 "
        "쓰십시오. **다만 분량을 채우려고 수치를 지어내는 것은 최악입니다.** "
        "절차, 준비물, 판단 기준, 흔한 실수를 더 자세히 쓰는 쪽으로 채우십시오."
    ),
}


def instruction_for(codes) -> str:
    """차단 사유에 맞는 재작성 지시문."""
    parts = [CODE_INSTRUCTIONS[c] for c in sorted(codes) if c in CODE_INSTRUCTIONS]
    return "\n".join([BASE_INSTRUCTION, *parts]) if parts else BASE_INSTRUCTION


def slug_for(post: dict) -> str:
    for label in post.get("labels") or []:
        if label in LABEL_TO_SLUG:
            return LABEL_TO_SLUG[label]
    return FALLBACK_SLUG


def select(posts: list, *, blog_host: str, min_hard: int) -> list:
    """다시 쓸 글 목록.

    조건은 두 가지다. (1) 게이트가 아래 사유로 막고 있다, (2) 그 글이 내릴
    대상이 아니다. 둘째 조건이 없으면 unpublish_posts.py 와 같은 글을 두고
    다투게 된다.
    """
    shared = quality.build_shared_sentences(posts)
    picked = []
    for post in posts:
        report = quality.check_post(post, blog_host=blog_host, shared_sentences=shared)
        codes = {f.code for f in report.findings if f.severity == quality.BLOCK}
        if not (codes & REWRITABLE_CODES):
            continue
        # 고칠 수 없는 사유가 하나라도 섞여 있으면 다시 써도 소용없다.
        if codes - REWRITABLE_CODES:
            continue
        if len(quality.hard_claims(post.get("content") or "")) >= min_hard:
            continue
        picked.append((post, report))
    return sorted(picked, key=lambda t: t[0].get("title", ""))


def related_for(post: dict, posts: list, limit: int) -> list:
    """generate_post.render_html 이 받는 모양({url, title})으로 맞춘다."""
    return [
        {"url": p["url"], "title": p.get("title", "")}
        for p in add_internal_links.pick_related(post, posts, limit)
    ]


def rewrite_one(post: dict, posts: list, *, blog_host: str, limit: int, before=None):
    """새 본문을 만들어 (본문, 리포트)로 돌려준다. 실패하면 (None, 마지막리포트)."""
    title = post.get("title", "")
    slug = slug_for(post)
    label = pick_topic.CATEGORY_LABELS.get(slug, slug)
    related = related_for(post, posts, limit)
    notice = generate_post.CATEGORY_NOTICE.get(slug, "")

    codes = set()
    if before is not None:
        codes = {f.code for f in before.findings if f.severity == quality.BLOCK}
    base = instruction_for(codes)

    last_report = None
    instruction = base

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            draft = generate_post._call_groq(title, label, instruction)
        except Exception as e:
            print(f"   ❌ 생성 실패({attempt}회차): {e}", file=sys.stderr)
            return None, last_report

        content = generate_post.render_html(draft, related, notice)
        report = quality.check_post(
            {
                "id": post.get("id", ""),
                "title": title,
                "url": post.get("url", ""),
                "content": content,
                "labels": list(post.get("labels") or []),
            },
            blog_host=blog_host,
        )
        last_report = report

        if not report.blocked:
            return content, report

        reasons = "; ".join(f.message[:60] for f in report.findings if f.severity == quality.BLOCK)
        print(f"   ⚠️ {attempt}회차 게이트 미달 — {reasons}", file=sys.stderr)
        instruction = (
            base
            + f"\n\n이전 답변이 다음 이유로 반려됐습니다: {reasons}\n"
            "특히 숫자는 하나도 쓰지 말고, 섹션을 7개까지 늘려 분량을 채우십시오."
        )
        time.sleep(CALL_INTERVAL)

    return None, last_report


def main():
    parser = argparse.ArgumentParser(description="수치를 지어낸 글의 본문을 다시 쓴다")
    parser.add_argument("--apply", action="store_true", help="실제로 본문을 교체한다")
    parser.add_argument("--limit", type=int, default=0, help="처리할 글 수 상한 (0=제한 없음)")
    parser.add_argument(
        "--links",
        type=int,
        default=add_internal_links.LINK_COUNT,
        help="새 본문에 붙일 내부 링크 수",
    )
    parser.add_argument(
        "--min-hard-claims",
        type=int,
        default=unpublish_posts.DEFAULT_MIN_HARD_CLAIMS,
        help="이 개수 이상의 주장 수치가 있는 글은 다시 쓰지 않고 넘긴다 "
             "(unpublish_posts.py 가 내릴 대상)",
    )
    args = parser.parse_args()

    if args.apply and not generate_post.GROQ_API_KEY:
        print("❌ GROQ_API_KEY 가 없습니다.", file=sys.stderr)
        sys.exit(1)

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    blog = blogger_api.get_blog(service, blog_id)
    host = blogger_api.blog_host(blog)

    posts = blogger_api.list_posts(service, blog_id)
    targets = select(posts, blog_host=host, min_hard=args.min_hard_claims)
    if args.limit:
        targets = targets[: args.limit]

    print(
        f"📥 발행된 글 {len(posts)}편 중 다시 쓸 글 {len(targets)}편.",
        file=sys.stderr,
    )
    for post, report in targets:
        n = report.metrics.get("risky_claims", 0)
        print(f"  - {post.get('title','')} (확인필요수치 {n})", file=sys.stderr)

    if not targets:
        print("✅ 다시 쓸 글이 없습니다.", file=sys.stderr)
        return

    if not args.apply:
        print(
            f"\nℹ️ 미리보기입니다. 실제로 다시 쓰려면 --apply 를 붙이세요 "
            f"(LLM 호출 {len(targets)}회 이상 발생).",
            file=sys.stderr,
        )
        return

    done, skipped, failed = 0, 0, []
    for index, (post, before) in enumerate(targets, 1):
        title = post.get("title", "")
        print(f"\n[{index}/{len(targets)}] ✍️ {title}", file=sys.stderr)

        content, after = rewrite_one(
            post, posts, blog_host=host, limit=args.links, before=before
        )
        if content is None:
            skipped += 1
            print("   ⏭️ 게이트를 통과하는 본문을 못 만들어 원본을 그대로 둡니다.", file=sys.stderr)
            time.sleep(CALL_INTERVAL)
            continue

        try:
            service.posts().update(
                blogId=blog_id,
                postId=post["id"],
                body=add_internal_links.update_body(post, content),
            ).execute()
        except Exception as e:
            failed.append((title, str(e)))
            print(f"   ❌ 교체 실패: {e}", file=sys.stderr)
            time.sleep(CALL_INTERVAL)
            continue

        done += 1
        print(
            f"   ✅ 교체 완료 — 확인필요수치 "
            f"{before.metrics.get('risky_claims', 0)} → {after.metrics.get('risky_claims', 0)}, "
            f"{after.metrics['text_chars']}자",
            file=sys.stderr,
        )
        time.sleep(CALL_INTERVAL)

    print(
        f"\n완료: 교체 {done}편, 건너뜀 {skipped}편"
        + (f", 실패 {len(failed)}편" if failed else ""),
        file=sys.stderr,
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
