"""본문 재작성 대상 선별 테스트.

여기서 막고 싶은 사고: rewrite_posts.py 와 unpublish_posts.py 가 같은 글을
두고 다투는 것. 한쪽이 다시 쓰는 동안 다른 쪽이 그 글을 내리면, LLM 호출을
쓰고도 결과가 사라진다. 두 선별이 서로소인지 고정해 둔다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pick_topic  # noqa: E402
import rewrite_posts as rw  # noqa: E402
import unpublish_posts as up  # noqa: E402

HOST = "soo-c9.blogspot.com"
MIN_HARD = up.DEFAULT_MIN_HARD_CLAIMS


def post(pid, title, content, labels=("건강",)):
    return {
        "id": pid,
        "title": title,
        "url": f"https://{HOST}/{pid}.html",
        "content": content,
        "labels": list(labels),
    }


def body(text):
    """게이트의 다른 항목(분량·구조·링크)은 통과하도록 살을 붙인다.

    그래야 이 테스트가 '수치' 하나만 보고 있다는 게 분명해진다.
    """
    filler = "".join(
        f"<h2>소제목 {i}</h2><p>{text} 여기서는 {i}번째 관점으로 살펴봅니다. "
        + ("실제로 확인해야 할 지점을 순서대로 짚어 보겠습니다. " * 12)
        + "</p>"
        for i in range(1, 6)
    )
    return f'<p>서론입니다.</p>{filler}<p><a href="https://{HOST}/other.html">다른 글</a></p>'


PERCENT = post("percent", "걷기 속도별 운동 효과",
               body("빠르게 걸으면 소모가 60% 늘고 심박수는 20% 오르며 지방은 30% 줄어듭니다."))
MONEY = post("money", "특별공급 자격 요건",
             body("연소득 4,500만원 이하이고 자산 3억 원 미만이며 보증금은 5,000만원입니다."),
             labels=("재테크",))
CLEAN = post("clean", "물 자주 마시는 습관", body("갈증을 느끼기 전에 마시는 편이 낫습니다."))


def test_비율_수치가_많은_글은_다시_쓸_대상이다():
    picked = rw.select([PERCENT], blog_host=HOST, min_hard=MIN_HARD)
    assert [p["id"] for p, _ in picked] == ["percent"]


def test_금액이_뼈대인_글은_다시_쓰지_않는다():
    """이쪽은 unpublish_posts.py 의 몫이다. 다시 써도 또 지어낸 숫자가 들어간다."""
    assert rw.select([MONEY], blog_host=HOST, min_hard=MIN_HARD) == []


def test_수치가_없는_글은_건드리지_않는다():
    assert rw.select([CLEAN], blog_host=HOST, min_hard=MIN_HARD) == []


def test_두_선별은_서로_겹치지_않는다():
    posts = [PERCENT, MONEY, CLEAN]
    rewrite_ids = {p["id"] for p, _ in rw.select(posts, blog_host=HOST, min_hard=MIN_HARD)}
    unpublish_ids = {p["id"] for p, _, _ in up.select(posts, min_hard=MIN_HARD, title_contains=[])}
    assert rewrite_ids & unpublish_ids == set()


def test_라벨에서_카테고리를_되찾는다():
    assert rw.slug_for(post("x", "제목", "<p>본문</p>", labels=("재테크",))) == "finance"
    assert rw.slug_for(post("x", "제목", "<p>본문</p>", labels=("건강", "수면"))) == "health"


def test_모르는_라벨이면_기본_카테고리로_떨어진다():
    assert rw.slug_for(post("x", "제목", "<p>본문</p>", labels=("아무말",))) == rw.FALLBACK_SLUG
    assert rw.FALLBACK_SLUG in pick_topic.CATEGORY_LABELS


def test_역방향_표가_카테고리_정의와_어긋나지_않는다():
    """pick_topic 에 카테고리를 추가하고 여기를 안 고치면 조용히 틀린다."""
    assert set(rw.LABEL_TO_SLUG.values()) == set(pick_topic.CATEGORY_LABELS)


def test_내부_링크는_렌더가_받는_모양으로_나온다():
    related = rw.related_for(PERCENT, [PERCENT, MONEY, CLEAN], 2)
    assert len(related) == 2
    assert all(set(r) == {"url", "title"} for r in related)
    assert all(r["url"] != PERCENT["url"] for r in related)
