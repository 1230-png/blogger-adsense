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


# 이 파이프라인이 발행한 글의 꼬리표. 이게 있으면 생성글, 없으면 사람이
# 편집기에서 갈아 끼운 본문으로 본다 (quality.looks_hand_written).
RELATED_BLOCK = (
    f"<h2>{rw.quality.RELATED_BLOCK_HEADING}</h2>"
    f'<ul><li><a href="https://{HOST}/other.html">다른 글</a></li></ul>'
)
HAND_TAIL = f'<p><a href="https://{HOST}/other.html">본문 안에서 건 링크</a></p>'


def body(text, *, repeat=18, hand_written=False):
    """게이트의 다른 항목(구조·링크)은 통과하도록 살을 붙인다.

    그래야 이 테스트가 보려는 항목 하나만 보고 있다는 게 분명해진다.
    repeat 를 줄이면 구조는 멀쩡한 채로 분량만 모자란 글이 된다 — 실제로
    마지막까지 남았던 '운동 후 근육통' 글이 그 모양이었다.

    hand_written=True 면 관련 글 블록 없이 본문 안에만 링크를 둔다. 사람이
    Blogger 편집기에서 다시 쓴 글이 실제로 이 모양이다.
    """
    filler = "".join(
        f"<h2>소제목 {i}</h2><p>{text} 여기서는 {i}번째 관점으로 살펴봅니다. "
        + ("실제로 확인해야 할 지점을 순서대로 짚어 보겠습니다. " * repeat)
        + "</p>"
        for i in range(1, 6)
    )
    tail = HAND_TAIL if hand_written else RELATED_BLOCK
    return f"<p>서론입니다.</p>{filler}{tail}"


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


# --- 다시 써서 풀 수 있는 사유만 고른다 ---------------------------------------
#
# 감사가 마지막 1편을 분량 미달(thin_body)로 막고 있었는데, 선별이 수치 문제만
# 보고 있어서 그 글을 놓쳤다. 반대로 다시 써도 안 풀리는 사유까지 집어 오면
# LLM 호출만 버린다. 두 방향을 모두 고정해 둔다.


# 소제목도 링크도 있는데 분량만 모자란 글. 막는 사유가 thin_body 하나뿐이다.
SHORT = post("short", "운동 후 근육통 회복법",
             body("가볍게 움직이는 편이 낫습니다.", repeat=3))


def test_분량이_모자란_글도_다시_쓸_대상이다():
    report = rw.quality.check_post(SHORT, blog_host=HOST)
    codes = {f.code for f in report.findings if f.severity == rw.quality.BLOCK}
    assert codes == {"thin_body"}, codes   # 막는 사유가 분량 하나뿐인지 먼저 확인

    picked = rw.select([SHORT], blog_host=HOST, min_hard=MIN_HARD)
    assert [p["id"] for p, _ in picked] == ["short"]


def test_다시_써도_안_풀리는_사유가_섞이면_건너뛴다():
    """예: 다른 글과 문장이 겹치는 글. 다시 써도 같은 이유로 또 막힌다."""
    same = "<p>같은 문장입니다. 이 문장도 똑같습니다. 세 번째 문장도 같습니다.</p>" * 20
    # 생성글 꼬리표를 붙여 둔다. 그러지 않으면 '사람이 쓴 본문'으로 걸러져서,
    # 이 테스트가 보려는 templated 판정이 아니라 엉뚱한 이유로 통과한다.
    twins = [
        post("t1", "쌍둥이 글 하나", same + RELATED_BLOCK),
        post("t2", "쌍둥이 글 둘", same + RELATED_BLOCK),
    ]
    picked = rw.select(twins, blog_host=HOST, min_hard=MIN_HARD)
    codes = set()
    for p in twins:
        report = rw.quality.check_post(p, blog_host=HOST,
                                       shared_sentences=rw.quality.build_shared_sentences(twins))
        codes |= {f.code for f in report.findings if f.severity == rw.quality.BLOCK}
    assert "templated" in codes          # 실제로 겹침 판정이 났고
    assert picked == []                  # 그래서 대상에서 빠졌다


def test_지시문이_차단_사유에_맞춰_달라진다():
    """분량이 모자란 글에 '수치를 쓰지 말라'고만 하면 더 짧아진다."""
    thin = rw.instruction_for({"thin_body"})
    figures = rw.instruction_for({"unverified_figures"})
    assert "섹션을 7개까지" in thin
    assert "섹션을 7개까지" not in figures
    assert "수치를 쓰지 마십시오" in figures


def test_두_사유가_함께면_지시문도_둘_다_담는다():
    both = rw.instruction_for({"thin_body", "unverified_figures"})
    assert "섹션을 7개까지" in both
    assert "수치를 쓰지 마십시오" in both


def test_사유를_모르면_기본_지시문만_쓴다():
    assert rw.instruction_for(set()) == rw.BASE_INSTRUCTION


def test_분량_미달_글도_금액이_뼈대면_내리는_쪽이다():
    short_money = post(
        "sm", "특별공급 요약",
        "<p>연소득 4,500만원 이하, 자산 3억 원 미만, 만 39세 이하입니다.</p>"
        + RELATED_BLOCK,
        labels=("재테크",),
    )
    assert rw.select([short_money], blog_host=HOST, min_hard=MIN_HARD) == []
    assert [p["id"] for p, _, _ in up.select([short_money], min_hard=MIN_HARD, title_contains=[])] == ["sm"]


# --- 사람이 쓴 본문은 덮지 않는다 ---------------------------------------------
#
# 2026-09-21 감사에서 실제로 일어난 일: 자동 발행된 카페인 글을 사람이 Blogger
# 편집기에서 통째로 다시 썼는데, 1143자라 thin_body 로 잡혔다. 확인필요수치는
# 1건뿐이라 내리는 쪽으로도 빠지지 않았다. 그대로 돌렸으면 사람이 쓴 원문이
# LLM 출력으로 덮이고 복구할 방법이 없었다.

HAND = post("hand", "카페인이 수면에 미치는 영향",
            body("카페인은 간에서 CYP1A2 효소로 분해됩니다.", repeat=3, hand_written=True))


def test_사람이_쓴_본문은_다시_쓰지_않는다():
    report = rw.quality.check_post(HAND, blog_host=HOST)
    codes = {f.code for f in report.findings if f.severity == rw.quality.BLOCK}
    assert codes == {"thin_body"}, codes      # 재작성 사유에는 분명히 걸리는데
    assert rw.select([HAND], blog_host=HOST, min_hard=MIN_HARD) == []   # 대상은 아니다


def test_건너뛴_이유를_이름과_함께_알려준다():
    """조용히 빠지면 감사는 빨간불인데 재작성은 '대상 없음'이라고만 한다."""
    held = rw.skipped_hand_written([HAND], blog_host=HOST, min_hard=MIN_HARD)
    assert [p["id"] for p, _ in held] == ["hand"]


def test_명시적으로_켜면_덮어쓸_수_있다():
    picked = rw.select([HAND], blog_host=HOST, min_hard=MIN_HARD, include_hand_written=True)
    assert [p["id"] for p, _ in picked] == ["hand"]


def test_생성글은_건너뛰는_목록에_들어가지_않는다():
    """같은 분량 미달이라도 꼬리표가 있으면 평소대로 다시 쓴다."""
    held = rw.skipped_hand_written([SHORT], blog_host=HOST, min_hard=MIN_HARD)
    assert held == []
    assert [p["id"] for p, _ in rw.select([SHORT], blog_host=HOST, min_hard=MIN_HARD)] == ["short"]
