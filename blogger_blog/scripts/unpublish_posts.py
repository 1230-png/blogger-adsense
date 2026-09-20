#!/usr/bin/env python3
"""수치가 글의 주장 자체인 글을 골라 초안으로 내린다.

prune_posts.py 와 목적이 다르다. 저쪽은 **얇은 글**을 걷어내려고 점수를 매겨
줄을 세운다. 이 스크립트는 분량·구조는 멀쩡한데 **내용이 틀렸을 수 있는 글**을
고른다. 지어낸 금액·연령·법령 조항이 들어간 글은 길수록, 구조가 좋을수록 더
위험하다. 점수로는 절대 걸러지지 않는다.

    python blogger_blog/scripts/unpublish_posts.py                  # 미리보기
    python blogger_blog/scripts/unpublish_posts.py --apply          # 실제로 내림

기본은 미리보기다. `--apply` 를 명시해야 실제로 손댄다.

## 왜 고쳐 쓰지 않고 내리는가

수치의 종류에 따라 처리가 갈린다 (quality.HARD_CLAIM_KINDS 주석 참고).

- 금액·연령·법령 조항: "연소득 4,500만원 이하면 신청 가능"에서 금액을 빼면
  남는 문장이 없다. 다시 써도 같은 자리에 또 지어낸 숫자가 들어간다. → 내린다
- 비율·기간: "칼로리 소모가 60% 늘어난다"는 수치를 빼도 문장이 성립한다.
  → rewrite_posts.py 로 본문만 다시 쓴다

즉 이 스크립트가 내리는 것은 "확인 없이는 살릴 방법이 없는 글"뿐이다.

## 되돌릴 수 있다

삭제가 아니라 Blogger API 의 revert(초안 전환)다. 본문은 그대로 남아 있고
관리 화면의 '초안' 탭에서 다시 게시할 수 있다. 다만 **주소(URL)는 보장되지
않으므로**, 되살릴 생각이라면 `--report` 로 남긴 목록을 보관하는 편이 낫다.
"""

import argparse
import json
import sys
from pathlib import Path

import blogger_api
import quality

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USED_JSON = DATA_DIR / "used_topics.json"
ROOT = Path(__file__).resolve().parent.parent

# 이 개수 이상의 '주장 수치'가 있으면 내린다. 3으로 잡은 근거: 금액이 한두 개
# 스치듯 언급된 글(예: 가계부 글의 "한 달 30만원")은 문장을 고쳐 살릴 수 있지만,
# 세 개를 넘으면 수치가 글의 뼈대라는 뜻이다.
DEFAULT_MIN_HARD_CLAIMS = 3


def select(posts: list, *, min_hard: int, title_contains: list) -> list:
    """(post, 사유, 수치목록) 목록. 결정론적이도록 제목순으로 정렬한다."""
    wanted = [t.strip() for t in title_contains if t.strip()]
    picked = []

    for post in posts:
        content = post.get("content") or ""
        title = post.get("title", "")
        hard = quality.hard_claims(content)

        if len(hard) >= min_hard:
            reason = f"주장 수치 {len(hard)}건 (기준 {min_hard}건 이상)"
        elif any(w in title for w in wanted):
            reason = "제목 지정(--title-contains)"
        else:
            continue

        picked.append((post, reason, hard))

    return sorted(picked, key=lambda t: t[0].get("title", ""))


def build_report(picked: list, kept: list, *, min_hard: int, applied: bool) -> str:
    lines = [
        "# 확인 불가 수치로 내리는 글",
        "",
        f"- 검사한 글: {len(picked) + len(kept)}편",
        f"- 내림: **{len(picked)}편** / 유지: **{len(kept)}편**",
        f"- 기준: 금액·연령·법령 조항 수치 {min_hard}건 이상",
        f"- 실행 모드: {'실제 적용됨' if applied else '미리보기 (--apply 없음)'}",
        "",
        "> 이 검사는 수치가 **틀렸는지** 판단하지 못합니다. 자료 없이 생성된",
        "> 수치라 확인이 필요하다는 것만 말합니다. 확인할 방법이 없으므로",
        "> 공개된 상태로 두지 않는 쪽을 택한 것입니다.",
        "",
        f"## 내리는 글 {len(picked)}편",
        "",
        "| 제목 | 사유 | 해당 수치 |",
        "|---|---|---|",
    ]
    for post, reason, hard in picked:
        sample = ", ".join(p for p, _ in hard[:6]) or "—"
        if len(hard) > 6:
            sample += " 외"
        lines.append(f"| [{post.get('title','')}]({post.get('url','')}) | {reason} | {sample} |")

    lines += [
        "",
        f"## 남는 글 {len(kept)}편",
        "",
        "| 제목 | 주장 수치 |",
        "|---|---|",
    ]
    for post in kept:
        n = len(quality.hard_claims(post.get("content") or ""))
        lines.append(f"| [{post.get('title','')}]({post.get('url','')}) | {n} |")

    lines += [
        "",
        "## 되돌리려면",
        "",
        "삭제가 아니라 초안 전환입니다. Blogger 관리 화면 → 게시물 → 초안 탭에서",
        "다시 '게시'를 누르면 복구됩니다. 다만 주소(URL)는 보장되지 않습니다.",
        "",
    ]
    return "\n".join(lines)


def rewrite_used_topics(removed_urls: set) -> int:
    """내려간 글을 발행 기록에서 뺀다.

    빼지 않으면 (1) 다음 글이 이제 없는 주소를 '함께 읽으면 좋은 글'로 링크하고,
    (2) 그 주제가 계속 '사용됨'으로 남아 제대로 다시 쓰이지 못한다.
    """
    if not USED_JSON.exists():
        return 0
    try:
        entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0

    kept = [e for e in entries if e.get("url") not in removed_urls]
    removed = len(entries) - len(kept)
    if removed:
        USED_JSON.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return removed


def main():
    parser = argparse.ArgumentParser(description="확인 불가 수치가 뼈대인 글을 초안으로 내림")
    parser.add_argument(
        "--min-hard-claims",
        type=int,
        default=DEFAULT_MIN_HARD_CLAIMS,
        help=f"금액·연령·법령 조항 수치가 몇 건 이상이면 내릴지 (기본 {DEFAULT_MIN_HARD_CLAIMS})",
    )
    parser.add_argument(
        "--title-contains",
        action="append",
        default=[],
        help="제목에 이 문구가 들어간 글도 함께 내린다 (여러 번 지정 가능)",
    )
    parser.add_argument("--apply", action="store_true", help="실제로 초안 전환한다")
    parser.add_argument("--report", help="결과를 저장할 마크다운 경로")
    args = parser.parse_args()

    if args.min_hard_claims < 1:
        print("❌ --min-hard-claims 는 1 이상이어야 합니다.", file=sys.stderr)
        sys.exit(2)

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    posts = blogger_api.list_posts(service, blog_id)
    print(f"📥 발행된 글 {len(posts)}편을 받았습니다.", file=sys.stderr)

    picked = select(posts, min_hard=args.min_hard_claims, title_contains=args.title_contains)
    picked_ids = {p.get("id") for p, _, _ in picked}
    kept = [p for p in posts if p.get("id") not in picked_ids]

    report = build_report(picked, kept, min_hard=args.min_hard_claims, applied=args.apply)
    if args.report:
        path = Path(args.report)
        if not path.is_absolute():
            path = ROOT.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"📝 리포트 저장: {path}", file=sys.stderr)
    print(report)

    if not picked:
        print("\n✅ 기준에 걸리는 글이 없습니다.", file=sys.stderr)
        return

    if len(kept) < quality.MIN_PUBLISHED_POSTS:
        print(
            f"\n⚠️ 내리고 나면 {len(kept)}편만 남습니다 "
            f"(권장 최소 {quality.MIN_PUBLISHED_POSTS}편). 감사는 당분간 빨간불입니다.",
            file=sys.stderr,
        )

    if not args.apply:
        print(
            f"\nℹ️ 미리보기입니다. 실제로 내리려면 --apply 를 붙이세요 (대상 {len(picked)}편).",
            file=sys.stderr,
        )
        return

    failed = []
    done_urls = set()
    for post, _, _ in picked:
        title = post.get("title", "")
        try:
            service.posts().revert(blogId=blog_id, postId=post["id"]).execute()
            done_urls.add(post.get("url"))
            print(f"⬇️ 초안으로 전환: {title}", file=sys.stderr)
        except Exception as e:
            failed.append((title, str(e)))
            print(f"❌ 실패: {title} — {e}", file=sys.stderr)

    removed = rewrite_used_topics(done_urls)
    print(
        f"\n완료: {len(done_urls)}편 초안 전환, 발행 기록에서 {removed}건 제거."
        + (f" 실패 {len(failed)}편." if failed else ""),
        file=sys.stderr,
    )
    if done_urls:
        print(
            "\nℹ️ 남은 글 중 내려간 글을 링크하던 것이 있으면 죽은 링크가 됩니다.\n"
            "   add_internal_links.py --refresh --apply 를 이어서 돌리세요.",
            file=sys.stderr,
        )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
