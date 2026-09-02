#!/usr/bin/env python3
"""품질 순으로 줄을 세워 상위 N편만 남기고 나머지를 초안으로 내린다.

얇은 글 24편보다 충실한 글 12편이 심사에 유리하다. 그런데 "어느 12편이
충실한가"를 사람이 24편을 다 읽어서 고르는 건 오래 걸리고, 기준도 그때그때
달라진다. 이 스크립트는 `quality.py` 가 재는 것과 **똑같은 지표**로 점수를
매겨 줄을 세운다.

    python blogger_blog/scripts/prune_posts.py --keep 12            # 미리보기
    python blogger_blog/scripts/prune_posts.py --keep 12 --apply    # 실제로 내림

기본은 미리보기다. `--apply` 를 명시해야 실제로 손댄다.

## 되돌릴 수 있다

내리는 방법은 삭제가 아니라 **초안으로 되돌리기**(Blogger API 의 revert)다.
글과 본문은 그대로 남아 있고, Blogger 관리 화면에서 다시 '게시'를 누르면
복구된다. 다만 **주소(URL)는 보장되지 않으므로**, 되살릴 생각이라면 아래
`--report` 로 남긴 목록을 보관하는 편이 낫다.

## 남는 글 수에 대한 주의

여기서 12편만 남기면 `quality.py` 의 사이트 검사는 `too_few_posts`(권장 최소
20편)로 계속 빨간불이다. 그게 맞는 동작이다. 순서는 이렇다.

    1. 이 스크립트로 얇은 글을 걷어낸다 (예: 24 → 12)
    2. 남은 글을 사람이 읽고 보강한다
    3. 새 파이프라인이 하루 1편씩 채운다 (약 8~12일)
    4. 감사가 초록불이 되면 재심사를 요청한다

"글 수를 채우려고 얇은 글을 남겨 두는 것"이 애초에 반려된 이유다.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import blogger_api
import quality

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USED_JSON = DATA_DIR / "used_topics.json"
ROOT = Path(__file__).resolve().parent.parent

# 점수 가중치. 근거가 없는 값이 아니라, 애드센스가 반려 사유로 든 항목
# (내용이 빈약함 / 고유하지 않음 / 사용자 환경)에 그대로 대응시킨 것이다.
# 그래도 임의의 값이므로, 결과가 납득되지 않으면 여기를 조정하면 된다.
W_TEXT_PER_100 = 1.0     # 분량이 주된 축. 4,000자에서 상한
W_HEADING = 3.0          # 구조
W_PARAGRAPH = 1.0        # 15문단에서 상한
W_IMAGE = 8.0            # 직접 만든 시각 자료는 대체하기 어려운 가치다
W_TABLE = 4.0
W_INTERNAL_LINK = 3.0
W_SHARED_PENALTY = 50.0  # 템플릿일수록 크게 감점
BLOCKED_PENALTY = 40.0   # 게이트 미달
DUPLICATE_PENALTY = 30.0 # 거의 같은 글 쌍에서 점수가 낮은 쪽

TEXT_CAP = 4000
PARAGRAPH_CAP = 15


def score(report: quality.PostReport) -> float:
    """PostReport 하나에 점수를 매긴다. 높을수록 남길 가치가 있다."""
    m = report.metrics
    value = (
        min(m["text_chars"], TEXT_CAP) / 100 * W_TEXT_PER_100
        + m["headings"] * W_HEADING
        + min(m["paragraphs"], PARAGRAPH_CAP) * W_PARAGRAPH
        + m["images"] * W_IMAGE
        + m["tables"] * W_TABLE
        + m["internal_links"] * W_INTERNAL_LINK
        - m["shared_sentence_ratio"] * W_SHARED_PENALTY
    )
    if report.blocked:
        value -= BLOCKED_PENALTY
    return round(value, 2)


def rank(posts: list, *, blog_host: str) -> list:
    """(PostReport, 점수) 목록을 점수 내림차순으로 돌려준다.

    거의 같은 글 쌍에서는 점수가 낮은 쪽을 더 깎는다. 둘 다 남겨 봐야
    중복 판정만 받으므로, 한쪽을 확실히 밀어내는 편이 낫다.
    """
    shared = quality.build_shared_sentences(posts)
    reports = {
        str(p.get("id")): quality.check_post(p, blog_host=blog_host, shared_sentences=shared)
        for p in posts
    }
    scores = {pid: score(r) for pid, r in reports.items()}

    for a, b, _ in quality.find_near_duplicates(posts):
        ida, idb = str(a.get("id")), str(b.get("id"))
        if ida not in scores or idb not in scores:
            continue
        loser = ida if scores[ida] <= scores[idb] else idb
        scores[loser] -= DUPLICATE_PENALTY

    ranked = [(reports[pid], scores[pid]) for pid in reports]
    # 동점일 때 순서가 실행마다 달라지면 곤란하므로 제목으로 한 번 더 정렬한다.
    return sorted(ranked, key=lambda t: (-t[1], t[0].title))


def build_report(kept: list, pruned: list, keep: int, applied: bool) -> str:
    lines = [
        f"# 글 선별 결과 — 상위 {keep}편 유지",
        "",
        f"- 검사한 글: {len(kept) + len(pruned)}편",
        f"- 유지: **{len(kept)}편** / 초안으로 내림: **{len(pruned)}편**",
        f"- 실행 모드: {'실제 적용됨' if applied else '미리보기 (--apply 없음)'}",
        "",
        "> 점수는 quality.py 가 재는 지표(본문 길이·소제목·문단·이미지·표·내부링크·",
        "> 공용 문장 비율)를 가중 합산한 값입니다. Google 의 기준이 아니라 이 저장소의",
        "> 운영용 점수이며, 순위가 납득되지 않으면 prune_posts.py 상단의 가중치를",
        "> 조정하면 됩니다.",
        "",
        f"## 유지하는 글 {len(kept)}편",
        "",
        "| 점수 | 제목 | 지표 |",
        "|---|---|---|",
    ]
    for report, value in kept:
        m = report.metrics
        lines.append(
            f"| {value} | [{report.title}]({report.url}) | "
            f"{m['text_chars']}자 · 소제목 {m['headings']} · 이미지 {m['images']} · "
            f"표 {m['tables']} · 내부링크 {m['internal_links']} |"
        )

    lines += ["", f"## 초안으로 내리는 글 {len(pruned)}편", "",
              "| 점수 | 제목 | 주된 이유 |", "|---|---|---|"]
    for report, value in pruned:
        blocking = [f.message for f in report.findings if f.severity == quality.BLOCK]
        reason = blocking[0] if blocking else "상대적으로 점수가 낮음"
        lines.append(f"| {value} | [{report.title}]({report.url}) | {reason} |")

    lines += [
        "",
        "## 되돌리려면",
        "",
        "삭제가 아니라 초안 전환입니다. Blogger 관리 화면 → 게시물 → 초안 탭에서",
        "다시 '게시'를 누르면 복구됩니다. 다만 주소(URL)는 보장되지 않습니다.",
        "",
    ]
    return "\n".join(lines)


def rewrite_used_topics(pruned_urls: set) -> int:
    """내려간 글을 발행 기록에서 뺀다.

    빼지 않으면 두 가지가 깨진다. (1) 다음 글이 '함께 읽으면 좋은 글'로 이제
    존재하지 않는 주소를 링크한다. (2) 그 주제가 계속 '사용됨'으로 남아
    다시 쓰이지 못한다 — 정작 다시 써야 할 주제인데도.
    """
    if not USED_JSON.exists():
        return 0
    try:
        entries = json.loads(USED_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0

    kept = [e for e in entries if e.get("url") not in pruned_urls]
    removed = len(entries) - len(kept)
    if removed:
        USED_JSON.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return removed


def main():
    parser = argparse.ArgumentParser(description="품질 상위 N편만 남기고 나머지를 초안으로 내림")
    parser.add_argument("--keep", type=int, default=12, help="유지할 글 수 (기본 12)")
    parser.add_argument("--apply", action="store_true", help="실제로 초안 전환한다 (없으면 미리보기)")
    parser.add_argument("--report", help="결과를 저장할 마크다운 경로")
    args = parser.parse_args()

    if args.keep < 1:
        print("❌ --keep 은 1 이상이어야 합니다.", file=sys.stderr)
        sys.exit(2)

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    blog = blogger_api.get_blog(service, blog_id)
    posts = blogger_api.list_posts(service, blog_id)

    print(f"📥 발행된 글 {len(posts)}편을 받았습니다.", file=sys.stderr)
    if len(posts) <= args.keep:
        print(f"ℹ️ 이미 {args.keep}편 이하입니다. 내릴 글이 없습니다.", file=sys.stderr)
        return

    ranked = rank(posts, blog_host=blogger_api.blog_host(blog))
    kept, pruned = ranked[: args.keep], ranked[args.keep :]

    report = build_report(kept, pruned, args.keep, args.apply)
    if args.report:
        path = Path(args.report)
        if not path.is_absolute():
            path = ROOT.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"📝 리포트 저장: {path}", file=sys.stderr)
    print(report)

    if not args.apply:
        print(
            f"\nℹ️ 미리보기입니다. 실제로 내리려면 --apply 를 붙이세요 "
            f"(내릴 글 {len(pruned)}편).",
            file=sys.stderr,
        )
        return

    failed = []
    for post_report, _ in pruned:
        try:
            service.posts().revert(blogId=blog_id, postId=post_report.post_id).execute()
            print(f"⬇️ 초안으로 전환: {post_report.title}", file=sys.stderr)
        except Exception as e:
            failed.append((post_report.title, str(e)))
            print(f"❌ 실패: {post_report.title} — {e}", file=sys.stderr)

    # 실제로 내려간 것만 기록에서 뺀다. 실패한 글은 아직 공개 상태이므로
    # 기록에 남겨 둬야 내부 링크와 주제 중복 판정이 맞다.
    failed_titles = {t for t, _ in failed}
    pruned_urls = {r.url for r, _ in pruned if r.title not in failed_titles}
    removed = rewrite_used_topics(pruned_urls)

    print(
        f"\n완료: {len(pruned) - len(failed)}편 초안 전환, "
        f"발행 기록에서 {removed}건 제거."
        + (f" 실패 {len(failed)}편." if failed else ""),
        file=sys.stderr,
    )
    if failed:
        sys.exit(1)

    print(
        f"\nℹ️ 남은 글은 {len(kept)}편입니다. quality.py 의 권장 최소치(20편)보다 적으므로\n"
        "   감사는 당분간 빨간불입니다. 남은 글을 보강하고 새 글이 쌓이기를 기다린 뒤\n"
        "   재심사를 요청하세요.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
