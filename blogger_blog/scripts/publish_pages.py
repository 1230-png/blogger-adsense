#!/usr/bin/env python3
"""소개·문의·개인정보처리방침·면책조항 고정 페이지를 Blogger에 게시한다.

애드센스 심사에서 사이트의 신뢰성을 확인할 때 보는 페이지들이다. 기존
파이프라인에는 이 페이지를 만드는 코드가 아예 없었고, 그게 "가치가 별로 없는
콘텐츠" 판정의 확실한 구멍 중 하나였다.

    python blogger_blog/scripts/publish_pages.py --dry-run   # 결과만 확인
    python blogger_blog/scripts/publish_pages.py             # 없으면 생성, 있으면 갱신

여러 번 돌려도 안전하다. 같은 페이지를 또 만들지 않고 내용만 갱신한다.

필요 환경변수는 blogger_api.py 의 것에 더해:
- BLOGGER_CONTACT_EMAIL : 페이지에 표시할 문의용 이메일 주소.
  이 저장소는 public 이므로 이메일을 파일에 적지 않고 시크릿으로 주입한다.
- BLOGGER_BLOG_NAME (선택) : 지정하지 않으면 Blogger 에 설정된 블로그 이름을 쓴다.
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

import blogger_api
import quality

PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"

# 파일 안의 <!-- ... --> 는 유지보수용 메모다. 방문자에게 보일 이유가 없고,
# 처리방침의 전제 조건 같은 내부 메모가 그대로 공개되면 곤란하다.
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def render_page(template: str, context: dict) -> str:
    """{{TOKEN}} 치환 + 주석 제거.

    치환되지 않은 토큰이 남으면 예외를 던진다. '{{CONTACT_EMAIL}}' 이라고
    그대로 적힌 문의 페이지를 발행하는 것은 페이지가 없는 것보다 나쁘다.
    """
    html = _COMMENT.sub("", template).strip()
    for key, value in context.items():
        html = html.replace("{{" + key + "}}", value)

    leftover = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", html)))
    if leftover:
        raise ValueError(f"치환되지 않은 토큰이 남았습니다: {', '.join(leftover)}")
    return html


def build_context(blog: dict, *, contact_email: str = "", blog_name: str = "") -> dict:
    """페이지 템플릿에 채워 넣을 값.

    이메일은 인자 → 환경변수 순으로 찾는다. 인자를 받는 이유: 시크릿을
    미리 등록해 두지 않아도 워크플로 실행 화면에서 바로 입력할 수 있게
    하기 위해서다. 어느 쪽이든 파일에는 적지 않는다 (저장소가 public).
    """
    email = (contact_email or os.environ.get("BLOGGER_CONTACT_EMAIL", "")).strip()
    if not email:
        print(
            "❌ 문의용 이메일이 없습니다.\n"
            "   --contact-email 로 넘기거나 BLOGGER_CONTACT_EMAIL 환경변수를 설정하세요.\n"
            "   개인정보처리방침과 문의 페이지에는 실제로 연락 가능한 주소가 있어야 합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    blog_url = (blog.get("url") or "").rstrip("/")
    name = (blog_name or os.environ.get("BLOGGER_BLOG_NAME", "")).strip() or blog.get("name", "")
    if not name:
        print("❌ 블로그 이름을 확인할 수 없습니다. BLOGGER_BLOG_NAME 을 지정하세요.", file=sys.stderr)
        sys.exit(1)

    return {
        "BLOG_NAME": name,
        "BLOG_URL": blog_url,
        "CONTACT_EMAIL": email,
        "UPDATED": date.today().isoformat(),
    }


def find_existing(pages: list, keywords: list) -> dict | None:
    for page in pages:
        haystack = f"{page.get('title', '')} {page.get('url', '')}".lower()
        if any(k.lower() in haystack for k in keywords):
            return page
    return None


def main():
    parser = argparse.ArgumentParser(description="애드센스 필수 고정 페이지 게시")
    parser.add_argument("--dry-run", action="store_true", help="발행하지 않고 결과만 출력")
    parser.add_argument(
        "--only",
        choices=sorted(quality.REQUIRED_PAGES),
        help="이 페이지 하나만 처리",
    )
    parser.add_argument(
        "--contact-email",
        default="",
        help="페이지에 표시할 문의용 이메일 (없으면 BLOGGER_CONTACT_EMAIL 환경변수)",
    )
    parser.add_argument(
        "--blog-name",
        default="",
        help="페이지에 표시할 블로그 이름 (없으면 Blogger 설정값)",
    )
    args = parser.parse_args()

    service = blogger_api.get_blogger_client()
    blog_id = blogger_api.require_blog_id()
    blog = blogger_api.get_blog(service, blog_id)
    context = build_context(blog, contact_email=args.contact_email, blog_name=args.blog_name)

    # 초안 페이지는 방문자에게 보이지 않아 심사에서도 없는 것과 같지만,
    # 여기서는 전체 목록을 봐야 한다. 초안이 이미 있는데 못 찾고 새로 만들면
    # 같은 제목의 페이지가 두 개가 된다.
    existing = blogger_api.list_pages(service, blog_id)

    targets = [args.only] if args.only else list(quality.REQUIRED_PAGES)
    created, updated = 0, 0

    for key in targets:
        title, keywords = quality.REQUIRED_PAGES[key]
        source = PAGES_DIR / f"{key}.html"
        if not source.exists():
            print(f"⚠️ 템플릿 없음, 건너뜁니다: {source}", file=sys.stderr)
            continue

        try:
            content = render_page(source.read_text(encoding="utf-8"), context)
        except ValueError as e:
            print(f"❌ {key}.html: {e}", file=sys.stderr)
            sys.exit(1)

        page = find_existing(existing, keywords)

        if args.dry_run:
            action = "갱신" if page else "생성"
            print(f"[dry-run] {action}: {title} ({quality.text_length(content)}자)", file=sys.stderr)
            continue

        if page:
            result = blogger_api.update_page(service, blog_id, page["id"], title, content)
            updated += 1
            print(f"♻️ 갱신: {title} → {result.get('url')}", file=sys.stderr)
        else:
            result = blogger_api.insert_page(service, blog_id, title, content)
            created += 1
            print(f"✅ 생성: {title} → {result.get('url')}", file=sys.stderr)

    if not args.dry_run:
        print(f"\n완료: 생성 {created}개, 갱신 {updated}개", file=sys.stderr)
        print(
            "ℹ️ 페이지를 만들어도 블로그 메뉴에 자동으로 걸리지는 않습니다.\n"
            "   Blogger 관리 화면 → 레이아웃 → '페이지' 가젯을 추가해 네 페이지를\n"
            "   모두 노출시켜야 심사에서 확인됩니다.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
