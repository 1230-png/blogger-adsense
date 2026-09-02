#!/usr/bin/env python3
"""이미 발행된 블로그를 애드센스 기준으로 진단해 리포트를 만든다.

애드센스가 "가치가 별로 없는 콘텐츠"로 반려했을 때, 정작 **어느 글이
문제인지**는 알려주지 않는다. 이 스크립트가 그 자리를 메운다: 발행된 글을
전부 받아 `quality.py` 의 게이트에 걸고, 손봐야 할 글과 이유를 목록으로 낸다.

    python blogger_blog/scripts/audit_blog.py                    # 요약만
    python blogger_blog/scripts/audit_blog.py --report audit.md  # 파일로 저장

기준 미달이 하나라도 있으면 종료 코드 1 로 끝난다. 워크플로에서 재심사
요청 전에 이걸 돌려 빨간불이면 요청하지 않게 하려는 것이다.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import blogger_api
import quality

ROOT = Path(__file__).resolve().parent.parent


def _fmt_metrics(m: dict) -> str:
    return (
        f"{m['text_chars']}자 · 소제목 {m['headings']} · 문단 {m['paragraphs']} · "
        f"이미지 {m['images']} · 표 {m['tables']} · 내부링크 {m['internal_links']} · "
        f"라벨 {m['labels']} · 공용문장 {m['shared_sentence_ratio']:.0%}"
    )


def build_report(site: quality.SiteReport, blog: dict) -> str:
    posts = site.post_reports
    failing = [r for r in posts if r.blocked]
    passing = [r for r in posts if r.passed]

    lines = [
        f"# 애드센스 콘텐츠 감사 — {blog.get('name', '(제목 없음)')}",
        "",
        f"- 대상: {blog.get('url', '')}",
        f"- 발행 글: **{len(posts)}편** (통과 {len(passing)} / 미달 {len(failing)})",
        f"- 종합 판정: **{'미달 — 재심사 요청 전에 아래를 먼저 해결하세요' if site.blocked else '통과'}**",
        "",
        "> 이 기준은 Google이 공개한 수치가 아니라, 정책 문서가 서술적으로",
        "> 요구하는 바를 자동 검사로 옮긴 휴리스틱입니다. 통과가 승인을",
        "> 보장하지 않고, 미달이 곧 위반인 것도 아닙니다.",
        "",
    ]

    if site.findings:
        lines += ["## 사이트 전체 문제", ""]
        for f in site.findings:
            mark = "🔴" if f.severity == quality.BLOCK else "🟡"
            lines.append(f"- {mark} {f.message}")
        lines.append("")

    # 어떤 문제가 몇 편에 걸쳐 나오는지 먼저 보여준다. 24편을 하나씩 읽는
    # 것보다, "24편 전부 내부 링크 0" 같은 패턴을 보는 쪽이 고치기 빠르다.
    counter = Counter(f.code for r in posts for f in r.findings)
    if counter:
        lines += ["## 문제 유형별 빈도", "", "| 문제 | 해당 글 수 |", "|---|---|"]
        for code, n in counter.most_common():
            lines.append(f"| `{code}` | {n} |")
        lines.append("")

    if failing:
        lines += [f"## 기준 미달 글 {len(failing)}편", ""]
        for r in failing:
            lines.append(f"### {r.title}")
            lines.append(f"{r.url}")
            lines.append("")
            lines.append(f"`{_fmt_metrics(r.metrics)}`")
            lines.append("")
            for f in r.findings:
                mark = "🔴" if f.severity == quality.BLOCK else "🟡"
                lines.append(f"- {mark} {f.message}")
            lines.append("")

    if passing:
        lines += [f"## 통과한 글 {len(passing)}편", "", "| 제목 | 지표 |", "|---|---|"]
        for r in passing:
            warns = [f for f in r.findings if f.severity == quality.WARN]
            suffix = f" (경고 {len(warns)})" if warns else ""
            lines.append(f"| [{r.title}]({r.url}) | {_fmt_metrics(r.metrics)}{suffix} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="발행된 Blogger 글을 애드센스 기준으로 진단")
    parser.add_argument("--report", help="리포트를 저장할 마크다운 경로")
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="미달이 있어도 종료 코드 0 으로 끝낸다 (리포트만 보고 싶을 때)",
    )
    args = parser.parse_args()

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()

    blog = blogger_api.get_blog(service, blog_id)
    posts = blogger_api.list_posts(service, blog_id)
    pages = blogger_api.live_pages(service, blog_id)

    print(f"📥 글 {len(posts)}편, 페이지 {len(pages)}개를 받았습니다.", file=sys.stderr)

    site = quality.check_site(posts, pages, blog_host=blogger_api.blog_host(blog))
    report = build_report(site, blog)

    if args.report:
        path = Path(args.report)
        if not path.is_absolute():
            path = ROOT.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"📝 리포트 저장: {path}", file=sys.stderr)

    print(report)

    failing = sum(1 for r in site.post_reports if r.blocked)
    if site.blocked:
        print(
            f"\n❌ 기준 미달입니다 (미달 글 {failing}편, 사이트 문제 {len(site.findings)}건).",
            file=sys.stderr,
        )
        sys.exit(0 if args.exit_zero else 1)

    print("\n✅ 자동 검사 기준은 모두 통과했습니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
