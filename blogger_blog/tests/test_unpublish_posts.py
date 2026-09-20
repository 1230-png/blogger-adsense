"""확인 불가 수치로 글을 내리는 선별 로직 테스트.

여기서 막고 싶은 사고: 되돌리기 어려운 작업(공개된 글을 내리는 것)을 잘못된
기준으로 실행하는 것. 특히 두 가지다.

1. 비율(%)만 있는 건강 글까지 내려서 발행 글 수가 무너지는 것
   — 그건 rewrite_posts.py 가 본문만 고쳐 살릴 수 있는 글이다
2. 관련 글 목록의 링크 제목에 든 숫자를 본문 주장으로 세는 것
   — 이미 한 번 낸 오탐이라 회귀 테스트로 고정해 둔다
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import quality  # noqa: E402
import unpublish_posts as up  # noqa: E402

HOST = "soo-c9.blogspot.com"


def post(pid, title, content):
    return {
        "id": pid,
        "title": title,
        "url": f"https://{HOST}/{pid}.html",
        "content": content,
        "labels": ["재테크"],
    }


MONEY = post(
    "money",
    "특별공급 자격 요건",
    "<p>연소득 4,500만원 이하이고 자산 3억 원 미만이어야 하며, "
    "만 39세 이하여야 합니다. 보증금은 5,000만원까지 지원됩니다.</p>",
)
PERCENT = post(
    "percent",
    "걷기 속도별 운동 효과",
    "<p>빠르게 걸으면 칼로리 소모가 60% 늘고, 심박수는 20% 오르며, "
    "지방 연소는 30% 증가하고 혈압은 15% 낮아집니다.</p>",
)
CLEAN = post("clean", "가계부 쓰는 법", "<p>영수증을 모으는 습관부터 시작하세요.</p>")
ONE_MONEY = post(
    "one",
    "가계부 정리 요령",
    "<p>한 달 30만원 정도를 따로 떼어 두면 관리가 쉬워집니다. 나머지는 흐름만 봅니다.</p>",
)


def test_금액과_연령이_많은_글은_내릴_대상이다():
    picked = up.select([MONEY], min_hard=3, title_contains=[])
    assert [p["id"] for p, _, _ in picked] == ["money"]


def test_비율만_있는_글은_내리지_않는다():
    """이런 글은 수치를 빼도 문장이 남으므로 다시 쓰는 쪽이 맞다."""
    assert up.select([PERCENT], min_hard=3, title_contains=[]) == []


def test_금액이_한두_개_스친_글은_내리지_않는다():
    assert up.select([ONE_MONEY], min_hard=3, title_contains=[]) == []


def test_수치가_없는_글은_내리지_않는다():
    assert up.select([CLEAN], min_hard=3, title_contains=[]) == []


def test_제목으로_직접_지정할_수_있다():
    picked = up.select([CLEAN], min_hard=3, title_contains=["가계부"])
    assert [p["id"] for p, _, _ in picked] == ["clean"]
    assert picked[0][1] == "제목 지정(--title-contains)"


def test_관련_글_링크의_숫자는_주장으로_세지_않는다():
    """'청약통장 200% 활용법' 같은 링크 제목 때문에 멀쩡한 글이 내려가면 안 된다."""
    linked = post(
        "linked",
        "청약 기초",
        "<p>공고문을 먼저 읽으세요.</p>"
        f"<h2>{quality.RELATED_BLOCK_HEADING}</h2>"
        '<ul><li><a href="/a.html">1,000만원 모으기</a></li>'
        '<li><a href="/b.html">3,000만원 굴리기</a></li>'
        '<li><a href="/c.html">5,000만원 만들기</a></li></ul>',
    )
    assert up.select([linked], min_hard=3, title_contains=[]) == []


def test_선별_결과는_제목순으로_고정된다():
    """실행할 때마다 순서가 바뀌면 미리보기와 실제 적용이 어긋난다."""
    picked = up.select([MONEY, PERCENT, CLEAN], min_hard=3, title_contains=["가계부", "걷기"])
    assert [p["title"] for p, _, _ in picked] == sorted(p["title"] for p, _, _ in picked)


def test_리포트에_내리는_글과_남는_글이_모두_나온다():
    picked = up.select([MONEY, CLEAN], min_hard=3, title_contains=[])
    report = up.build_report(picked, [CLEAN], min_hard=3, applied=False)
    assert "특별공급 자격 요건" in report
    assert "가계부 쓰는 법" in report
    assert "미리보기" in report


def test_발행_기록에서_내려간_글만_빠진다(tmp_path, monkeypatch):
    import json

    used = tmp_path / "used_topics.json"
    used.write_text(
        json.dumps(
            [
                {"topic": "a", "url": f"https://{HOST}/money.html"},
                {"topic": "b", "url": f"https://{HOST}/clean.html"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(up, "USED_JSON", used)

    removed = up.rewrite_used_topics({f"https://{HOST}/money.html"})

    assert removed == 1
    left = json.loads(used.read_text(encoding="utf-8"))
    assert [e["topic"] for e in left] == ["b"]
