"""글 선별(초안 전환) 테스트.

여기서 막고 싶은 사고는 두 가지다.

1. 충실한 글이 얇은 글보다 낮은 점수를 받아 내려가는 것. 되돌릴 수는 있지만
   주소가 보장되지 않으므로, 잘못 내리면 실질적으로 되돌리기 어렵다.
2. 내려간 글이 발행 기록에 남는 것. 그러면 다음 글이 이제 존재하지 않는
   주소를 '함께 읽으면 좋은 글'로 링크한다.

Blogger API 는 호출하지 않는다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import prune_posts  # noqa: E402
import quality  # noqa: E402

from test_quality import make_post  # noqa: E402

HOST = "soo-c9.blogspot.com"


def thin_post(post_id):
    """옛 파이프라인이 만들던 모양: 얇고, 표도 이미지도 내부 링크도 없다."""
    body = "".join(
        f"<h2>소제목 {j}</h2><p>{'글' * 60} {post_id}-{j} 고유한 문장입니다.</p>" for j in range(4)
    )
    return {
        "id": f"thin{post_id}",
        "title": f"얇은 글 {post_id}",
        "url": f"https://{HOST}/thin/{post_id}.html",
        "content": f"<p>{'서' * 40} {post_id} 서론입니다.</p>{body}<h2>마무리</h2><p>결론입니다.</p>",
        "labels": ["재테크"],
    }


def rich_post(post_id):
    """새 파이프라인이 만드는 모양: 길고, 표와 내부 링크가 있다."""
    post = make_post(post_id=f"rich{post_id}", title=f"충실한 글 {post_id}", filler=chr(0xAC00 + post_id))
    post["content"] = (
        '<h2>핵심 요약</h2><table><tbody><tr><th>항목</th><td>설명입니다.</td></tr></tbody></table>'
        + post["content"]
    )
    post["url"] = f"https://{HOST}/rich/{post_id}.html"
    return post


def ranked_titles(posts):
    return [r.title for r, _ in prune_posts.rank(posts, blog_host=HOST)]


# --- 순위 --------------------------------------------------------------------


def test_충실한_글이_얇은_글보다_위에_온다():
    posts = [thin_post(1), rich_post(1), thin_post(2), rich_post(2)]
    titles = ranked_titles(posts)
    assert titles[0].startswith("충실한") and titles[1].startswith("충실한")
    assert titles[2].startswith("얇은") and titles[3].startswith("얇은")


def test_표와_내부링크가_점수를_올린다():
    full = rich_post(1)
    plain = dict(full, id="plain", url=f"https://{HOST}/plain.html")
    # 표를 없애고, 내부 링크를 외부 링크로 바꾼다. 본문 글자 수는 그대로다.
    plain["content"] = (
        full["content"]
        .replace("<table>", "<div>")
        .replace("</table>", "</div>")
        .replace(f'href="https://{HOST}', 'href="https://example.com')
    )

    full_score = prune_posts.score(quality.check_post(full, blog_host=HOST))
    plain_score = prune_posts.score(quality.check_post(plain, blog_host=HOST))
    assert full_score > plain_score


def test_거의_같은_글_쌍에서_한쪽만_밀려난다():
    a = rich_post(1)
    b = dict(a, id="copy", title="같은 내용 복사본", url=f"https://{HOST}/copy.html")
    others = [thin_post(i) for i in range(3)]

    ranked = prune_posts.rank([a, b] + others, blog_host=HOST)
    scores = {r.title: s for r, s in ranked}

    # 내용이 같으므로 감점 전 점수는 동일하다. 둘 중 한쪽만 중복 감점을
    # 받아야 한다 — 둘 다 깎으면 살릴 만한 원본까지 함께 밀려난다.
    gap = abs(scores["충실한 글 1"] - scores["같은 내용 복사본"])
    assert gap == prune_posts.DUPLICATE_PENALTY


def test_동점이어도_순서가_실행마다_바뀌지_않는다():
    posts = [thin_post(1), thin_post(2), thin_post(3)]
    assert ranked_titles(posts) == ranked_titles(list(reversed(posts)))


def test_점수는_지표에서만_나온다():
    """제목이나 발행일 같은 것이 점수에 섞이지 않는지."""
    a = rich_post(1)
    b = dict(a, id="b", title="ZZZ 완전히 다른 제목", published="2020-01-01")
    ra = quality.check_post(a, blog_host=HOST)
    rb = quality.check_post(b, blog_host=HOST)
    assert prune_posts.score(ra) == prune_posts.score(rb)


# --- 유지/제거 분할 -----------------------------------------------------------


def test_상위_N편만_남긴다():
    posts = [rich_post(i) for i in range(3)] + [thin_post(i) for i in range(5)]
    ranked = prune_posts.rank(posts, blog_host=HOST)
    kept, pruned = ranked[:3], ranked[3:]
    assert len(kept) == 3 and len(pruned) == 5
    assert all(r.title.startswith("충실한") for r, _ in kept)


# --- 발행 기록 정리 -----------------------------------------------------------


def test_내려간_글을_발행_기록에서_뺀다(tmp_path, monkeypatch):
    used = tmp_path / "used_topics.json"
    used.write_text(
        json.dumps([
            {"topic": "a", "category": "finance", "date": "2026-08-01", "url": f"https://{HOST}/a.html"},
            {"topic": "b", "category": "finance", "date": "2026-08-02", "url": f"https://{HOST}/b.html"},
            {"topic": "c", "category": "health", "date": "2026-08-03", "url": f"https://{HOST}/c.html"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(prune_posts, "USED_JSON", used)

    removed = prune_posts.rewrite_used_topics({f"https://{HOST}/b.html"})
    assert removed == 1

    left = json.loads(used.read_text(encoding="utf-8"))
    assert [e["topic"] for e in left] == ["a", "c"]


def test_기록_파일이_없어도_터지지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(prune_posts, "USED_JSON", tmp_path / "없음.json")
    assert prune_posts.rewrite_used_topics({"https://x"}) == 0


def test_깨진_기록_파일에도_터지지_않는다(tmp_path, monkeypatch):
    broken = tmp_path / "used_topics.json"
    broken.write_text("{{{ 깨진 JSON", encoding="utf-8")
    monkeypatch.setattr(prune_posts, "USED_JSON", broken)
    assert prune_posts.rewrite_used_topics({"https://x"}) == 0


def test_지울_것이_없으면_파일을_건드리지_않는다(tmp_path, monkeypatch):
    used = tmp_path / "used_topics.json"
    original = json.dumps([{"topic": "a", "url": f"https://{HOST}/a.html"}], ensure_ascii=False)
    used.write_text(original, encoding="utf-8")
    monkeypatch.setattr(prune_posts, "USED_JSON", used)

    assert prune_posts.rewrite_used_topics({f"https://{HOST}/없는글.html"}) == 0
    assert used.read_text(encoding="utf-8") == original


# --- 리포트 -------------------------------------------------------------------


def test_리포트에_유지와_제거가_모두_나온다():
    posts = [rich_post(1), thin_post(1)]
    ranked = prune_posts.rank(posts, blog_host=HOST)
    report = prune_posts.build_report(ranked[:1], ranked[1:], keep=1, applied=False)
    assert "충실한 글 1" in report
    assert "얇은 글 1" in report
    assert "미리보기" in report
