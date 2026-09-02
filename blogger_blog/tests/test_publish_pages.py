"""고정 페이지 렌더링 테스트.

여기서 막고 싶은 사고: 문의 페이지에 '{{CONTACT_EMAIL}}' 이라고 그대로 적힌
채 발행되는 것. 그건 페이지가 없는 것보다 나쁘다 — 심사자에게 관리되지 않는
사이트로 보인다.
"""

import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
PAGES = Path(__file__).resolve().parent.parent / "pages"
sys.path.insert(0, str(SCRIPTS))

import publish_pages  # noqa: E402
import quality  # noqa: E402

CONTEXT = {
    "BLOG_NAME": "테스트 블로그",
    "BLOG_URL": "https://soo-c9.blogspot.com",
    "CONTACT_EMAIL": "someone@example.com",
    "UPDATED": "2026-09-02",
}


def test_토큰을_치환한다():
    html = publish_pages.render_page("<p>{{BLOG_NAME}} / {{CONTACT_EMAIL}}</p>", CONTEXT)
    assert html == "<p>테스트 블로그 / someone@example.com</p>"


def test_유지보수용_주석을_제거한다():
    html = publish_pages.render_page("<!-- 내부 메모 -->\n<p>본문</p>", CONTEXT)
    assert "내부 메모" not in html
    assert "<p>본문</p>" in html


def test_치환되지_않은_토큰이_남으면_실패시킨다():
    with pytest.raises(ValueError, match="UNKNOWN_TOKEN"):
        publish_pages.render_page("<p>{{UNKNOWN_TOKEN}}</p>", CONTEXT)


@pytest.mark.parametrize("key", sorted(quality.REQUIRED_PAGES))
def test_필수_페이지_템플릿이_존재한다(key):
    assert (PAGES / f"{key}.html").exists()


@pytest.mark.parametrize("key", sorted(quality.REQUIRED_PAGES))
def test_필수_페이지가_토큰_없이_렌더된다(key):
    html = publish_pages.render_page((PAGES / f"{key}.html").read_text(encoding="utf-8"), CONTEXT)
    assert not re.search(r"\{\{|\}\}", html)
    assert CONTEXT["CONTACT_EMAIL"] in html or key == "about" or "@" not in html


@pytest.mark.parametrize("key", sorted(quality.REQUIRED_PAGES))
def test_필수_페이지가_빈약하지_않다(key):
    """세 줄짜리 소개 페이지는 그 자체가 '내용이 빈약한 화면'이다."""
    html = publish_pages.render_page((PAGES / f"{key}.html").read_text(encoding="utf-8"), CONTEXT)
    info = quality.extract(html)
    assert quality.text_length(html) >= 400, f"{key}: {quality.text_length(html)}자"
    assert info.headings >= 2, f"{key}: 소제목 {info.headings}개"


def test_개인정보처리방침에_애드센스_고지가_있다():
    """애드센스를 붙이면서 광고 쿠키 고지가 없는 처리방침은 심사에서 문제가 된다."""
    html = publish_pages.render_page((PAGES / "privacy.html").read_text(encoding="utf-8"), CONTEXT)
    text = quality.visible_text(html)
    assert "AdSense" in text
    assert "쿠키" in text
    links = quality.extract(html).links
    assert any("google.com/settings/ads" in link for link in links)
    assert any("aboutads.info" in link for link in links)


def test_기존_페이지를_제목으로_찾아낸다():
    """같은 페이지를 두 번 만들지 않는지. 중복 페이지는 그 자체로 감점이다."""
    existing = [{"id": "9", "title": "개인정보처리방침", "url": "https://x/p/privacy.html"}]
    _, keywords = quality.REQUIRED_PAGES["privacy"]
    assert publish_pages.find_existing(existing, keywords)["id"] == "9"


def test_영문_url만_있어도_찾아낸다():
    existing = [{"id": "9", "title": "Privacy Policy", "url": "https://x/p/privacy.html"}]
    _, keywords = quality.REQUIRED_PAGES["privacy"]
    assert publish_pages.find_existing(existing, keywords)["id"] == "9"


def test_없는_페이지는_None():
    _, keywords = quality.REQUIRED_PAGES["privacy"]
    assert publish_pages.find_existing([{"id": "1", "title": "소개", "url": "/p/about.html"}], keywords) is None
