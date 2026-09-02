"""품질 게이트 테스트.

여기서 막고 싶은 사고는 두 가지다.

1. 얇거나 템플릿으로 찍어낸 글이 게이트를 빠져나가는 것 — 그게 애드센스
   반려의 원인이었으므로, 통과시켜서는 안 되는 것이 통과하면 안 된다.
2. 반대로 멀쩡한 글이 파싱 실수로 '본문 0자' 판정을 받아 발행이 멈추는 것.
   Blogger 본문에는 깨진 태그가 흔해서, 태그 처리를 정규식으로 대충 하면
   실제로 이런 일이 난다.

네트워크도 자격증명도 필요 없다.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import quality  # noqa: E402

HOST = "soo-c9.blogspot.com"


def make_post(
    *, post_id="1", title="제목", sections=5, body_chars=380, links=1, labels=("재테크",), filler="본"
):
    """게이트를 통과하도록 설계된 정상 글. 테스트마다 한 축씩 무너뜨려서 쓴다.

    filler 를 바꾸면 본문이 완전히 다른 글이 된다. 서로 다른 두 글을 만들 때
    id 만 바꾸면 내용이 같아서 중복·템플릿 검사에 걸린다.
    """
    parts = ["<h2>핵심 요약</h2><table><tbody><tr><th>항목</th><td>설명입니다.</td></tr></tbody></table>"]
    parts.append("<p>" + filler * 200 + " 서론 문장입니다.</p>")
    for i in range(sections):
        parts.append(f"<h2>소제목 {i}</h2>")
        parts.append(f"<p>{filler * body_chars} 이것은 {filler}{i}번 섹션의 고유한 문장입니다.</p>")
    parts.append(f"<h2>지금 확인할 것</h2><p>{filler * 150} 결론 문장입니다.</p>")
    for i in range(links):
        parts.append(f'<p><a href="https://{HOST}/2026/08/other-{i}.html">다른 글 {i}</a></p>')
    return {
        "id": post_id,
        "title": title,
        "url": f"https://{HOST}/p/{post_id}.html",
        "content": "\n".join(parts),
        "labels": list(labels),
    }


def codes(report):
    return {f.code for f in report.findings}


# --- 통과해야 하는 것 ---------------------------------------------------------


def test_정상적인_글은_통과한다():
    report = quality.check_post(make_post(), blog_host=HOST)
    assert report.passed, [f.message for f in report.findings]


def test_상대경로_링크도_내부_링크로_센다():
    post = make_post(links=0)
    post["content"] += '<p><a href="/2026/08/other.html">다른 글</a></p>'
    report = quality.check_post(post, blog_host=HOST)
    assert "no_internal_link" not in codes(report)


# --- 막아야 하는 것 -----------------------------------------------------------


def test_본문이_얇으면_차단한다():
    report = quality.check_post(make_post(sections=1, body_chars=50), blog_host=HOST)
    assert "thin_body" in codes(report)
    assert report.blocked


def test_소제목이_없으면_차단한다():
    post = {"id": "1", "title": "제목", "url": "", "content": "<p>" + "가" * 3000 + "</p>", "labels": ["x"]}
    report = quality.check_post(post, blog_host=HOST)
    assert "no_structure" in codes(report)


def test_내부_링크가_없으면_차단한다():
    report = quality.check_post(make_post(links=0), blog_host=HOST)
    assert "no_internal_link" in codes(report)
    assert report.blocked


def test_외부_링크는_내부_링크로_치지_않는다():
    post = make_post(links=0)
    post["content"] += '<p><a href="https://example.com/a.html">외부</a></p>'
    report = quality.check_post(post, blog_host=HOST)
    assert "no_internal_link" in codes(report)


def test_첫_글이면_내부_링크를_요구하지_않는다():
    """링크할 대상이 없는 새 블로그에서 첫 글이 영원히 막히면 안 된다."""
    report = quality.check_post(make_post(links=0), blog_host=HOST, require_internal_link=False)
    assert report.passed
    assert "no_internal_link" in codes(report)  # 경고로는 남는다


def test_공용_문장이_많으면_템플릿으로_차단한다():
    """본문이 서로 달라도, 공용 문장을 잔뜩 끼워 넣으면 걸려야 한다."""
    boiler = "".join(
        f"<p>모든 글에 똑같이 들어가는 상투적인 문장 {i}번입니다.</p>" for i in range(20)
    )
    a = make_post(post_id="a", filler="본")
    b = make_post(post_id="b", filler="달")
    a["content"] += boiler
    b["content"] += boiler

    shared = quality.build_shared_sentences([a, b])
    report = quality.check_post(a, blog_host=HOST, shared_sentences=shared)
    assert "templated" in codes(report)


def test_짧은_공통_고지_한줄은_템플릿으로_치지_않는다():
    """카테고리 고지처럼 한 문장만 겹치는 것까지 막으면 게이트가 쓸모없어진다."""
    notice = "<p><em>이 글은 일반적인 정보 제공을 위한 것이며 전문가 상담을 대신하지 않습니다.</em></p>"
    a = make_post(post_id="a", filler="본")
    b = make_post(post_id="b", filler="달")
    a["content"] += notice
    b["content"] += notice

    shared = quality.build_shared_sentences([a, b])
    assert notice.count("이 글은") == 1  # 고지는 실제로 공유된다
    report = quality.check_post(a, blog_host=HOST, shared_sentences=shared)
    assert report.passed, [f.message for f in report.findings]


def test_거의_같은_글을_찾아낸다():
    a = make_post(post_id="a")
    b = dict(a, id="b", title="제목만 바꾼 글")
    pairs = quality.find_near_duplicates([a, b])
    assert len(pairs) == 1
    assert pairs[0][2] >= quality.NEAR_DUPLICATE_JACCARD


def test_서로_다른_글은_중복으로_잡지_않는다():
    a = make_post(post_id="a", filler="본")
    b = make_post(post_id="b", filler="달")
    assert quality.find_near_duplicates([a, b]) == []


# --- HTML 파싱 견고성 ---------------------------------------------------------


def test_스크립트와_스타일은_본문_길이에서_뺀다():
    html = "<style>.a{color:red}</style><script>var x=1;</script><p>실제 본문입니다.</p>"
    assert quality.visible_text(html) == "실제 본문입니다."


def test_속성값_안의_꺾쇠가_본문을_먹지_않는다():
    """정규식으로 태그를 지우면 여기서 본문이 통째로 사라진다."""
    html = '<a title="a > b" href="/x">링크</a><p>남아야 하는 본문</p>'
    text = quality.visible_text(html)
    assert "링크" in text and "남아야 하는 본문" in text


def test_self_closing_이미지도_센다():
    info = quality.extract('<p>글</p><img src="/a.png" />')
    assert info.images == 1


def test_html_엔티티는_한_글자로_센다():
    assert quality.text_length("<p>A&amp;B</p>") == 3


# --- 사이트 단위 --------------------------------------------------------------


def test_필수_페이지가_없으면_차단한다():
    posts = [make_post(post_id=str(i)) for i in range(quality.MIN_PUBLISHED_POSTS)]
    site = quality.check_site(posts, pages=[], blog_host=HOST)
    assert {f.code for f in site.findings} >= {
        "missing_page_about",
        "missing_page_contact",
        "missing_page_privacy",
        "missing_page_disclaimer",
    }
    assert site.blocked


def test_필수_페이지가_다_있으면_해당_지적이_사라진다():
    posts = [make_post(post_id=str(i)) for i in range(quality.MIN_PUBLISHED_POSTS)]
    pages = [
        {"title": "소개", "url": f"https://{HOST}/p/about.html"},
        {"title": "문의", "url": f"https://{HOST}/p/contact.html"},
        {"title": "개인정보처리방침", "url": f"https://{HOST}/p/privacy.html"},
        {"title": "면책조항", "url": f"https://{HOST}/p/disclaimer.html"},
    ]
    site = quality.check_site(posts, pages, blog_host=HOST)
    assert not any(f.code.startswith("missing_page_") for f in site.findings)
    assert quality.missing_pages(pages) == []


def test_글이_적으면_차단한다():
    site = quality.check_site([make_post()], pages=[], blog_host=HOST)
    assert "too_few_posts" in {f.code for f in site.findings}


@pytest.mark.parametrize("title", ["", "   "])
def test_제목이_비면_차단한다(title):
    report = quality.check_post(make_post(title=title), blog_host=HOST)
    assert "no_title" in codes(report)
