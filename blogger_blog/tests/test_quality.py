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


# --- 지어낸 수치 검사 ---------------------------------------------------------
#
# 발행된 글을 직접 읽어 보니 분량·구조는 전부 통과인데 수치가 틀려 있었다.
# 글자 수 검사로는 절대 잡히지 않는 결함이라 별도 검사를 붙였다.


def test_금액_연령_비율을_찾아낸다():
    html = (
        "<p>연소득 4,500만원 이하이고 만 39세 이하이면 신청할 수 있으며, "
        "중위소득 80% 기준을 적용합니다.</p>"
    )
    kinds = {kind for _, kind in quality.find_risky_claims(html)}
    assert kinds == {"금액 기준", "연령 요건", "비율·요율"}


def test_기간_요건과_법령_조항도_찾는다():
    html = "<p>결혼 후 7년 이내여야 하며, 주택법 제20조에 따릅니다.</p>"
    kinds = {kind for _, kind in quality.find_risky_claims(html)}
    assert kinds == {"기간 요건", "법령 조항"}


def test_같은_수치가_두_번_나와도_한_건으로_센다():
    """요약 표와 본문에 같은 금액이 나오는 건 흔하다. 두 건으로 세면 과장된다."""
    html = "<p>연소득 4,500만원 이하입니다.</p><p>다시 말해 4,500만원 이하입니다.</p>"
    assert len(quality.find_risky_claims(html)) == 1


def test_순서를_세는_숫자는_수치로_보지_않는다():
    """'7가지', '5단계' 같은 건 사실 주장이 아니다."""
    html = "<p>7가지 방법을 5단계로 정리했고 3개 항목을 확인합니다.</p>"
    assert quality.find_risky_claims(html) == []


def test_수치가_많으면_차단한다():
    body = "".join(f"<h2>소제목 {i}</h2><p>{'글' * 400} {i}번 문장입니다.</p>" for i in range(5))
    claims = (
        "<p>연소득 4,500만원 이하, 자산 1억원 이하, 만 39세 이하, "
        "중위소득 80%, 결혼 후 7년 이내가 기준입니다.</p>"
    )
    post = {
        "id": "x", "title": "제목", "url": "",
        "content": body + claims + f'<p><a href="https://{HOST}/a.html">다른 글</a></p>',
        "labels": ["재테크"],
    }
    report = quality.check_post(post, blog_host=HOST)
    assert "unverified_figures" in codes(report)
    assert report.blocked


def test_수치가_한두_개면_통과시킨다():
    """'하루 8잔' 수준의 상식적인 수치까지 막으면 게이트가 쓸모없어진다."""
    post = make_post()
    post["content"] += "<p>성인 기준 하루 7시간 수면이 권장되며 약 30% 정도가 해당합니다.</p>"
    report = quality.check_post(post, blog_host=HOST)
    assert "unverified_figures" not in codes(report)


def test_지표에_확인필요수치_건수가_들어간다():
    post = make_post()
    post["content"] += "<p>연소득 4,500만원 기준입니다.</p>"
    report = quality.check_post(post, blog_host=HOST)
    assert report.metrics["risky_claims"] == 1


def test_관련_글_링크_제목의_수치는_세지_않는다():
    """'청약통장 200% 활용법'을 링크한 글 여덟 편이 전부 오탐으로 잡혔었다."""
    body = "<p>본문에는 수치가 없습니다.</p>"
    related = (
        f"<h2>{quality.RELATED_BLOCK_HEADING}</h2>"
        "<ul><li><a href='/a.html'>청약통장 200% 활용법</a></li>"
        "<li><a href='/b.html'>연소득 4,500만원 가이드</a></li></ul>"
    )
    assert quality.find_risky_claims(body + related) == []


def test_관련_글_블록_앞의_수치는_그대로_센다():
    body = "<p>연소득 4,500만원 이하가 기준입니다.</p>"
    related = f"<h2>{quality.RELATED_BLOCK_HEADING}</h2><ul><li>청약통장 200% 활용법</li></ul>"
    claims = quality.find_risky_claims(body + related)
    assert [p for p, _ in claims] == ["4,500만원"]


# --- 주장 수치와 꾸밈 수치의 구분 ---------------------------------------------
#
# 이 구분이 "내릴 글"과 "다시 쓸 글"을 가른다. 여기가 틀리면 살릴 수 있는 글을
# 내리거나, 내려야 할 글을 다시 써서 또 지어낸 숫자를 올리게 된다.


def test_금액과_연령과_법령_조항은_주장_수치다():
    html = (
        "<p>연소득 4,500만원 이하이고 만 39세 이하이면 주택법 제5조에 따라 "
        "신청할 수 있습니다.</p>"
    )
    kinds = {k for _, k in quality.hard_claims(html)}
    assert kinds == {"금액 기준", "연령 요건", "법령 조항"}


def test_비율과_기간은_주장_수치가_아니다():
    html = "<p>소모량이 60% 늘어나며, 3개월 이상 유지하면 몸에 익습니다.</p>"
    assert quality.hard_claims(html) == []
    # 다만 확인이 필요한 수치이기는 하므로 전체 검사에서는 잡혀야 한다.
    assert len(quality.find_risky_claims(html)) == 2


def test_주장_수치는_전체_수치의_부분집합이다():
    html = "<p>보증금 5,000만원, 만 34세 이하, 공제율 15%, 제7조 기준입니다.</p>"
    assert set(quality.hard_claims(html)) <= set(quality.find_risky_claims(html))


def test_주장_수치도_관련_글_목록은_제외한다():
    html = (
        "<p>본문입니다.</p>"
        f"<h2>{quality.RELATED_BLOCK_HEADING}</h2>"
        '<ul><li><a href="/a.html">1,000만원 모으기</a></li></ul>'
    )
    assert quality.hard_claims(html) == []


def test_주장_수치_종류는_전체_종류에_정의되어_있다():
    """HARD_CLAIM_KINDS 에 오타가 나면 조용히 아무것도 안 걸린다."""
    defined = {kind for _, kind in quality.RISKY_CLAIM_PATTERNS}
    assert quality.HARD_CLAIM_KINDS <= defined
