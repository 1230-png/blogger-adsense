"""기존 글 내부 링크 삽입 테스트.

여기서 막고 싶은 사고: 워크플로를 두 번 돌렸을 때 같은 블록이 두 번 들어가는 것.
발행된 글을 수정하는 스크립트라 되돌리기가 번거롭다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import add_internal_links as ail  # noqa: E402
import quality  # noqa: E402

HOST = "soo-c9.blogspot.com"


def post(pid, title, labels, published, content="<p>본문입니다.</p>"):
    return {
        "id": pid,
        "title": title,
        "url": f"https://{HOST}/{pid}.html",
        "content": content,
        "labels": labels,
        "published": published,
    }


POSTS = [
    post("1", "청약통장 활용법", ["재테크", "청약"], "2026-08-22T00:00:00Z"),
    post("2", "연말정산 절세 팁", ["재테크"], "2026-08-25T00:00:00Z"),
    post("3", "고혈압 예방 습관", ["건강"], "2026-08-23T00:00:00Z"),
    post("4", "무주택 기간 계산", ["재테크", "청약"], "2026-08-28T00:00:00Z"),
]


def test_블록을_만들면_내부_링크로_인식된다():
    block = ail.render_block(POSTS[:3])
    info = quality.extract(block)
    assert len([h for h in info.links if HOST in h]) == 3


def test_라벨이_겹치는_글을_먼저_고른다():
    related = ail.pick_related(POSTS[0], POSTS, limit=2)
    titles = [p["title"] for p in related]
    # '청약' 라벨을 공유하는 무주택 기간 글이 건강 글보다 앞이어야 한다.
    assert "무주택 기간 계산" in titles
    assert "고혈압 예방 습관" not in titles


def test_자기_자신은_링크하지_않는다():
    related = ail.pick_related(POSTS[0], POSTS, limit=3)
    assert all(p["id"] != "1" for p in related)


def test_요청한_개수만_고른다():
    assert len(ail.pick_related(POSTS[0], POSTS, limit=2)) == 2


def test_url이_없는_글은_고르지_않는다():
    broken = dict(post("9", "주소 없는 글", ["재테크"], "2026-08-29T00:00:00Z"), url="")
    related = ail.pick_related(POSTS[0], POSTS + [broken], limit=4)
    assert all(p["id"] != "9" for p in related)


def test_이미_블록이_있으면_다시_넣지_않는다():
    """워크플로를 두 번 돌려도 링크 목록이 두 번 붙으면 안 된다."""
    content = "<p>본문</p>" + ail.render_block(POSTS[:3])
    assert ail.has_block(content)


def test_블록이_없으면_삽입_대상이다():
    assert not ail.has_block("<p>본문만 있는 글</p>")


def test_제목의_특수문자를_이스케이프한다():
    tricky = [dict(POSTS[0], title='R&D 비용 < 5% 인 경우')]
    block = ail.render_block(tricky)
    assert "R&amp;D 비용 &lt; 5% 인 경우" in block


def test_url의_따옴표를_이스케이프한다():
    tricky = [dict(POSTS[0], url=f'https://{HOST}/a"onerror=x.html')]
    block = ail.render_block(tricky)
    assert '"onerror=x' not in block.replace("&quot;", "")


def test_블록을_붙이면_내부링크_차단이_해소된다():
    """이 스크립트의 존재 이유. 감사에서 24편 전부가 걸린 항목이다."""
    body = "".join(f"<h2>소제목 {i}</h2><p>{'글' * 400} {i}번 문장입니다.</p>" for i in range(5))
    before = {"id": "x", "title": "제목", "url": "", "content": body, "labels": ["재테크"]}
    assert "no_internal_link" in {f.code for f in quality.check_post(before, blog_host=HOST).findings}

    after = dict(before, content=body + ail.render_block(POSTS[:3]))
    report = quality.check_post(after, blog_host=HOST)
    assert "no_internal_link" not in {f.code for f in report.findings}
    assert report.passed, [f.message for f in report.findings]


def test_generate_post와_같은_블록_제목을_쓴다():
    """제목이 어긋나면 블로그 안에 블록 이름이 두 가지가 되고 중복 삽입도 생긴다."""
    import generate_post as gp

    html = gp.render_html(
        {"intro": "서론", "sections": [], "conclusion_heading": "정리", "conclusion": "결론"},
        [{"url": f"https://{HOST}/a.html", "title": "다른 글", "topic": "t"}],
    )
    assert ail.BLOCK_HEADING in html


# --- 회귀: 라벨 삭제 사고 --------------------------------------------------
#
# 이 스크립트의 첫 판이 posts().update() 에 title/content 만 보냈다.
# Blogger 의 update 는 PATCH 가 아니라 리소스 전체 교체라서, 발행 중이던
# 12편의 라벨이 전부 지워졌다. 다시는 일어나면 안 되는 일이다.


def test_수정_본문에_라벨을_반드시_실어_보낸다():
    original = post("1", "제목", ["재테크", "청약"], "2026-08-22T00:00:00Z")
    body = ail.update_body(original, "<p>새 본문</p>")
    assert body["labels"] == ["재테크", "청약"]
    assert body["content"] == "<p>새 본문</p>"
    assert body["title"] == "제목"


def test_라벨이_없는_글은_빈_목록으로_보낸다():
    original = dict(post("1", "제목", [], "2026-08-22T00:00:00Z"))
    del original["labels"]
    assert ail.update_body(original, "<p>x</p>")["labels"] == []


def test_custom_meta_data도_유지한다():
    original = dict(post("1", "제목", ["재테크"], "2026-08-22T00:00:00Z"))
    original["customMetaData"] = '{"description": "요약"}'
    assert ail.update_body(original, "<p>x</p>")["customMetaData"] == '{"description": "요약"}'


def test_원본_라벨_목록을_공유하지_않는다():
    """body 의 labels 를 나중에 건드려도 원본이 바뀌면 안 된다."""
    original = post("1", "제목", ["재테크"], "2026-08-22T00:00:00Z")
    body = ail.update_body(original, "<p>x</p>")
    body["labels"].append("오염")
    assert original["labels"] == ["재테크"]
