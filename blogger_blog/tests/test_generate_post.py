"""글 조립(렌더링) 테스트.

Groq API 는 호출하지 않는다. 검증 대상은 "LLM 응답 dict 를 받아 어떤 HTML 을
만드는가"이고, 애드센스 반려의 원인이 바로 그 HTML 의 모양이었다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_post as gp  # noqa: E402
import quality  # noqa: E402

HOST = "soo-c9.blogspot.com"


def llm_response(sections=6, body_chars=300):
    """Groq 가 돌려주는 모양의 응답."""
    return {
        "title": "신용카드 소득공제를 최대로 받는 사용 비율",
        "meta_description": "총급여의 25%를 넘긴 뒤부터 공제가 시작되는 구조를 정리했습니다.",
        "intro": "연말정산 " * 60 + "때마다 헷갈리는 지점을 정리합니다.",
        "sections": [
            {
                "heading": f"{i}단계로 확인하는 기준",
                "body": f"{i}번 섹션 " * body_chars + "구체적인 설명입니다.",
                "list": [f"{i}번 실천 항목 하나", f"{i}번 실천 항목 둘"],
            }
            for i in range(sections)
        ],
        "conclusion_heading": "올해 남은 기간에 조정할 것",
        "conclusion": "정리하자면 " * 40 + "이렇게 접근하시면 됩니다.",
        "tags": ["연말정산", "소득공제"],
    }


PUBLISHED = [
    {"topic": "연말정산 미리 준비하는 절세 팁", "title": "연말정산 절세 팁",
     "category": "finance", "date": "2026-08-30", "url": f"https://{HOST}/2026/08/a.html"},
    {"topic": "파킹통장과 CMA 차이", "title": "파킹통장과 CMA",
     "category": "finance", "date": "2026-08-28", "url": f"https://{HOST}/2026/08/b.html"},
    {"topic": "고혈압 예방 생활 습관", "title": "고혈압 예방",
     "category": "health", "date": "2026-08-29", "url": f"https://{HOST}/2026/08/c.html"},
]


# --- 이전 버전이 만들던 문제들 -------------------------------------------------


def test_결론_소제목이_고정_리터럴이_아니다():
    """24편 전부의 마지막 h2 가 '마무리'로 같았던 것이 템플릿 판정의 근거였다."""
    html = gp.render_html(llm_response(), PUBLISHED)
    assert "<h2>올해 남은 기간에 조정할 것</h2>" in html
    assert "<h2>마무리</h2>" not in html


def test_결론_소제목이_비면_기본값을_쓴다():
    response = llm_response()
    response["conclusion_heading"] = ""
    assert "<h2>정리하며</h2>" in gp.render_html(response, PUBLISHED)


def test_핵심_요약_표를_강제하지_않는다():
    """24편 전부가 <h2>핵심 요약</h2><table>로 시작한 것 자체가 템플릿 신호였다.

    표를 다시 강제로 붙이면 같은 문제를 재발시키므로, 렌더 결과에 표가
    전혀 없어야 한다 (quality.py의 no_visual은 경고일 뿐 차단이 아니다).
    """
    html = gp.render_html(llm_response(), PUBLISHED)
    assert "<table" not in html
    assert "핵심 요약" not in html
    assert quality.extract(html).tables == 0


def test_내부_링크가_들어간다():
    html = gp.render_html(llm_response(), PUBLISHED)
    info = quality.extract(html)
    assert len([h for h in info.links if HOST in h]) == 3


def test_링크할_글이_없으면_블록을_통째로_생략한다():
    html = gp.render_html(llm_response(), [])
    assert "함께 읽으면 좋은 글" not in html


def test_html_특수문자를_이스케이프한다():
    """이전 버전은 이스케이프가 없어서 '<' 하나에 뒤쪽 마크업이 통째로 깨졌다."""
    response = llm_response()
    response["sections"][0]["heading"] = "R&D 비용 < 5% 인 경우"
    response["sections"][0]["body"] = "조건은 <b>이렇게</b> & 저렇게 판단합니다. " * 40

    html = gp.render_html(response, PUBLISHED)
    assert "R&amp;D 비용 &lt; 5% 인 경우" in html
    assert "<b>" not in html
    # 이스케이프했으므로 파서가 끝까지 정상적으로 읽어야 한다.
    assert "올해 남은 기간에 조정할 것" in quality.visible_text(html)


def test_링크_url의_따옴표도_이스케이프한다():
    published = [{"topic": "t", "title": '따옴표 " 포함', "category": "finance",
                  "date": "2026-08-30", "url": f'https://{HOST}/a"onerror=x.html'}]
    html = gp.render_html(llm_response(), published)
    assert '"onerror=x' not in html.replace("&quot;", "")


# --- 분량 계산 ----------------------------------------------------------------


def test_산문_길이는_소제목과_링크를_빼고_센다():
    response = llm_response(sections=2, body_chars=10)
    prose = gp.prose_length(response)
    rendered = quality.text_length(gp.render_html(response, PUBLISHED))
    # 요약 표·소제목·링크·고지가 더해지므로 렌더 결과가 더 길다.
    assert prose < rendered


def test_빈_섹션은_렌더에서_빠진다():
    response = llm_response()
    response["sections"].append({"heading": "", "body": "", "list": []})
    before = quality.extract(gp.render_html(llm_response(), PUBLISHED)).headings
    after = quality.extract(gp.render_html(response, PUBLISHED)).headings
    assert before == after


# --- 내부 링크 선정 -----------------------------------------------------------


def test_같은_카테고리를_먼저_고른다():
    picked = gp.pick_related(PUBLISHED, "finance", "지금 쓰는 주제", limit=2)
    assert [e["category"] for e in picked] == ["finance", "finance"]


def test_최신_글을_먼저_고른다():
    picked = gp.pick_related(PUBLISHED, "finance", "지금 쓰는 주제", limit=1)
    assert picked[0]["date"] == "2026-08-30"


def test_카테고리가_모자라면_다른_카테고리로_채운다():
    picked = gp.pick_related(PUBLISHED, "tech", "지금 쓰는 주제", limit=3)
    assert len(picked) == 3


def test_지금_쓰는_주제_자신은_제외한다():
    picked = gp.pick_related(PUBLISHED, "finance", "연말정산 미리 준비하는 절세 팁", limit=3)
    assert all(e["topic"] != "연말정산 미리 준비하는 절세 팁" for e in picked)


def test_같은_url이_두_번_들어가지_않는다():
    duplicated = PUBLISHED + PUBLISHED
    picked = gp.pick_related(duplicated, "finance", "지금 쓰는 주제", limit=5)
    assert len({e["url"] for e in picked}) == len(picked)


def test_발행_기록이_비어도_터지지_않는다():
    assert gp.pick_related([], "finance", "주제") == []


# --- 최종 확인 ----------------------------------------------------------------


def test_렌더_결과가_품질_게이트를_통과한다():
    """생성기와 게이트가 따로 놀지 않는지 확인하는, 이 파일에서 가장 중요한 테스트."""
    html = gp.render_html(llm_response(), PUBLISHED, gp.CATEGORY_NOTICE["finance"])
    report = quality.check_post(
        {"id": "", "title": "제목", "url": "", "content": html, "labels": ["재테크"]},
        blog_host=HOST,
    )
    assert report.passed, [f.message for f in report.findings]
    assert report.metrics["text_chars"] >= quality.MIN_TEXT_CHARS


def test_산문_기준을_넘기면_렌더_기준도_넘는다():
    """MIN_PROSE_CHARS 가 MIN_TEXT_CHARS 보다 낮게 잡힌 것이 안전한지 확인한다."""
    response = llm_response(sections=5, body_chars=1)
    # 산문 길이를 기준선에 딱 맞춘다.
    filler = "가" * (gp.MIN_PROSE_CHARS - gp.prose_length(response) + 5)
    response["sections"][0]["body"] += filler
    assert gp.prose_length(response) >= gp.MIN_PROSE_CHARS

    html = gp.render_html(response, PUBLISHED, gp.CATEGORY_NOTICE["finance"])
    assert quality.text_length(html) >= quality.MIN_TEXT_CHARS


# --- 요청 한도(429) 처리 ------------------------------------------------------
#
# 실제로 겪은 일: 기존 글 9편을 한 번에 다시 쓰다가 네 번째에서 429 가 났고,
# 재시도가 없어 남은 6편이 그대로 건너뛰어졌다. 429 는 분당 한도(몇 초면 풀림)
# 와 하루 한도(몇 시간)가 섞여 오므로, 기다릴 값인지 판단해야 한다.


class _FakeResponse:
    def __init__(self, status_code=429, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("본문이 JSON 이 아닙니다")
        return self._payload


def test_retry_after_헤더를_초로_읽는다():
    assert gp._retry_after(_FakeResponse(headers={"retry-after": "12.5"})) == 12.5


def test_retry_after가_없으면_기본값을_쓴다():
    assert gp._retry_after(_FakeResponse()) == gp.DEFAULT_RETRY_WAIT


def test_retry_after가_숫자가_아니면_기본값을_쓴다():
    """Groq 가 HTTP-date 형식으로 줄 수도 있다. 그때 죽으면 안 된다."""
    resp = _FakeResponse(headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert gp._retry_after(resp) == gp.DEFAULT_RETRY_WAIT


def test_음수_retry_after는_0으로_본다():
    assert gp._retry_after(_FakeResponse(headers={"retry-after": "-5"})) == 0.0


def test_한도_설명을_본문에서_꺼낸다():
    """분당 한도인지 하루 한도인지가 여기 적혀 있어 사람이 판단할 근거가 된다."""
    resp = _FakeResponse(payload={"error": {"message": "Rate limit reached for model"}})
    assert "Rate limit reached" in gp._error_detail(resp)


def test_본문이_JSON이_아니어도_설명을_만든다():
    assert gp._error_detail(_FakeResponse(text="<html>429</html>")) == "<html>429</html>"


def test_기다릴_수_있는_한도만_기다린다():
    """하루 한도까지 기다리면 워크플로가 타임아웃까지 매달린다."""
    assert gp.MAX_RETRY_WAIT < 24 * 60 * 60
    assert gp.DEFAULT_RETRY_WAIT <= gp.MAX_RETRY_WAIT
