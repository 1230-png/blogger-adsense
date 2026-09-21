#!/usr/bin/env python3
"""애드센스 "가치가 별로 없는 콘텐츠" 판정을 코드로 옮긴 품질 게이트.

이 모듈이 이 저장소의 중심이다. `audit_blog.py`(이미 발행된 글 진단)와
`publish_post.py`(발행 직전 차단)가 **같은 함수**를 호출하기 때문에,
감사에서 통과한 기준과 발행에서 막히는 기준이 어긋날 수 없다.

## 임계값의 출처에 대한 정직한 설명

Google은 "본문 N자 이상", "글 M개 이상" 같은 **수치 기준을 공개하지 않는다.**
아래 상수는 공개된 숫자가 아니라, 애드센스 정책 문서가 서술적으로 요구하는 것
(고유하고 충분한 본문, 템플릿 복제 금지, 사이트 정보 페이지 존재)을 자동
검사 가능한 형태로 옮긴 **운영용 휴리스틱**이다. 통과했다고 승인이 보장되지
않고, 걸렸다고 반드시 위반인 것도 아니다. 사람이 확인할 곳을 좁혀 주는
용도로만 쓴다.

정책 원문:
- 최소 콘텐츠 요건:  https://support.google.com/adsense/answer/9856806
- 가치가 낮은 콘텐츠: https://support.google.com/adsense/answer/9976788
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# --- 글 1편에 적용하는 임계값 -------------------------------------------------

# 공백 제외 본문 길이. 기존 파이프라인은 1,200자였는데, 그 값은 소제목과
# 리스트 항목 글자까지 합산한 수치라 실제 산문은 1,000자 아래로 떨어질 수
# 있었다. 여기서는 태그를 걷어낸 실제 표시 텍스트로 다시 센다.
MIN_TEXT_CHARS = 1700
MIN_HEADINGS = 3          # h2/h3 소제목. 구조 없는 벽글은 얇게 읽힌다
MIN_PARAGRAPHS = 6        # <p> 개수
MIN_INTERNAL_LINKS = 1    # 같은 블로그의 다른 글로 가는 링크
MIN_LABELS = 1            # Blogger 라벨(카테고리)

# 다른 글에도 그대로 등장하는 문장의 비율. 인사말이나 고지 문구 몇 줄이
# 겹치는 것은 정상이지만, 본문 문장의 3할이 공용이면 템플릿을 돌린 것이다.
MAX_SHARED_SENTENCE_RATIO = 0.30

# 글 두 편의 5글자 shingle Jaccard 유사도. 이 이상이면 사실상 같은 글이다.
NEAR_DUPLICATE_JACCARD = 0.60

# --- 지어낸 수치 검사 ---------------------------------------------------------
#
# 왜 필요한가: 발행된 글을 직접 읽어 보니 분량·구조는 전부 통과인데 **내용이
# 틀려** 있었다. "신혼부부 30세 이하(남성 35세 이하)", "연소득 4,500만원 이하",
# "인사청" 처럼 실제 제도와 다른 수치와 기관명이 단정적으로 적혀 있었다.
#
# 원인은 분명하다. 생성기는 LLM 에 아무 자료도 주지 않으면서 "구체적인 수치를
# 담으라"고 시켰다. 자료가 없으면 그럴듯한 숫자를 지어내는 것 말고 방법이 없다.
#
# 글자 수 검사로는 이걸 절대 잡을 수 없다 — 지어낸 수치일수록 글은 더 구체적이고
# 길어 보인다. 그래서 별도 검사가 필요하다.
#
# 한계(중요): 이 검사는 **수치가 틀렸는지 판단하지 못한다.** 확인이 필요한
# 문장을 골라낼 뿐이다. 최종 판단은 사람이 원 출처를 보고 해야 한다.
RISKY_CLAIM_PATTERNS = [
    (r"\d[\d,]*\s*(?:만\s*원|억\s*원|만원|억원)", "금액 기준"),
    (r"만\s*\d+\s*세|\d+\s*세\s*(?:이하|이상|미만|초과)", "연령 요건"),
    (r"\d+(?:\.\d+)?\s*%", "비율·요율"),
    (r"\d+\s*(?:년|개월|주)\s*(?:이내|이상|이하|미만)", "기간 요건"),
    (r"제\s*\d+\s*조", "법령 조항"),
]

# 이 개수를 넘으면 차단한다. 1~2개는 상식 수준의 수치일 수 있으므로 봐준다.
MAX_RISKY_CLAIMS = 2

# 확인되지 않은 수치 중에서도 처리 방법이 갈리는 지점.
#
# 금액·연령·법령 조항은 글의 **주장 그 자체**다. "연소득 4,500만원 이하면
# 신청 가능"에서 금액을 빼면 남는 문장이 없고, 틀리면 독자가 실제로 신청을
# 잘못한다. 이런 글은 고쳐 쓰는 게 아니라 내리는 편이 맞다.
#
# 반면 비율(%)과 기간은 대개 설명을 꾸미는 값이다. "빠르게 걸으면 칼로리
# 소모가 60% 늘어난다"는 "느린 걸음보다 뚜렷하게 늘어난다"로 바꿔도 글이
# 성립한다. 이런 글은 본문만 다시 쓰면 살릴 수 있다.
HARD_CLAIM_KINDS = frozenset({"금액 기준", "연령 요건", "법령 조항"})

# --- 사이트 전체에 적용하는 임계값 --------------------------------------------

MIN_PUBLISHED_POSTS = 20   # 공식 숫자가 아니라 실무 하한선
MIN_PASS_RATIO = 0.90      # 발행된 글 중 게이트를 통과해야 하는 비율

# 애드센스 심사에서 사이트 신뢰도 근거로 확인되는 고정 페이지.
# 키는 blogger_blog/pages/<키>.md 파일명과 1:1로 맞춘다.
REQUIRED_PAGES = {
    "about": ("소개", ["소개", "about"]),
    "contact": ("문의", ["문의", "contact", "연락"]),
    "privacy": ("개인정보처리방침", ["개인정보", "privacy"]),
    "disclaimer": ("면책조항", ["면책", "disclaimer"]),
}

BLOCK = "block"
WARN = "warn"


@dataclass
class Finding:
    """검사 결과 1건. code는 리포트에서 묶는 키, severity는 발행 차단 여부."""

    code: str
    severity: str
    message: str


@dataclass
class PostReport:
    post_id: str
    title: str
    url: str
    metrics: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity == BLOCK for f in self.findings)

    @property
    def passed(self) -> bool:
        return not self.blocked


@dataclass
class SiteReport:
    post_reports: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    duplicate_pairs: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity == BLOCK for f in self.findings) or any(
            r.blocked for r in self.post_reports
        )


# --- HTML 파싱 ----------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "noscript", "iframe"}

# 블록 요소 경계에서는 줄바꿈을 넣는다. 그러지 않으면 </p><p> 를 사이에 두고
# 떨어져 있는 두 문장이 하나로 이어져 버린다. 예를 들어 링크 목록의 앵커
# 텍스트와 그 뒤 고지 문구가 한 문장이 되면, 글마다 링크가 다르다는 이유로
# 공용 문장 검사가 고지 문구를 놓친다.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "table", "tr", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section", "article",
}


class _Extract(HTMLParser):
    """본문 HTML에서 텍스트와 구조 지표를 한 번에 뽑는다.

    정규식으로 태그를 지우지 않는 이유: Blogger 본문에는 붙여넣기로 들어온
    깨진 태그와 속성값 안의 '>' 가 흔하고, 그걸 정규식으로 지우면 본문 길이가
    엉뚱하게 계산되어 멀쩡한 글이 '얇다'고 차단된다.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.headings = 0
        self.paragraphs = 0
        self.images = 0
        self.tables = 0
        self.links = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag in ("h2", "h3", "h4"):
            self.headings += 1
        elif tag == "p":
            self.paragraphs += 1
        elif tag == "img":
            self.images += 1
        elif tag == "table":
            self.tables += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_startendtag(self, tag, attrs):
        # <img />, <br/> 같은 self-closing 태그는 handle_starttag 로 오지 않는다.
        if tag not in _SKIP_TAGS:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        """블록 경계의 줄바꿈은 살리고, 그 밖의 연속 공백만 하나로 합친다."""
        joined = "".join(self.text_parts)
        joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
        return re.sub(r"\s*\n\s*", "\n", joined).strip()


def extract(html: str) -> _Extract:
    parser = _Extract()
    parser.feed(html or "")
    parser.close()
    return parser


def block_text(html: str) -> str:
    """블록 경계의 줄바꿈을 살린 본문 텍스트. 문장 분리에 쓴다."""
    return extract(html).text


def visible_text(html: str) -> str:
    """태그를 걷어낸 본문 텍스트. 줄바꿈까지 포함해 공백을 하나로 합친다."""
    return re.sub(r"\s+", " ", extract(html).text).strip()


def text_length(html: str) -> int:
    """공백을 제외한 본문 글자 수. 한국어는 단어 수보다 글자 수가 안정적이다."""
    return len(re.sub(r"\s+", "", visible_text(html)))


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。？！])\s+|\n+")


def sentences(html: str, min_chars: int = 10) -> list:
    """중복 판정용 문장 목록. 너무 짧은 조각은 우연히 겹치므로 버린다."""
    out = []
    for raw in _SENTENCE_SPLIT.split(block_text(html)):
        s = raw.strip()
        if len(re.sub(r"\s+", "", s)) >= min_chars:
            out.append(s)
    return out


def shingles(html: str, size: int = 5) -> set:
    """공백 제거 후 size 글자 단위 슬라이딩 윈도우 집합."""
    packed = re.sub(r"\s+", "", visible_text(html))
    if len(packed) < size:
        return set()
    return {packed[i : i + size] for i in range(len(packed) - size + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# 글 끝의 관련 글 목록. 이 블록은 자동 생성된 **링크 제목**이지 본문 주장이
# 아니므로 수치 검사에서 제외한다. 실제로 이걸 넣지 않았더니, "청약통장 200%
# 활용법" 을 링크한 글 여덟 편이 전부 '비율·요율 200%' 로 잡혔다.
RELATED_BLOCK_HEADING = "함께 읽으면 좋은 글"


def find_risky_claims(html: str) -> list:
    """확인이 필요한 수치 주장을 (문구, 종류) 목록으로 돌려준다.

    표 안의 요약 문구까지 포함해 본문을 보되, 끝의 관련 글 목록은 뺀다.
    중복은 한 번만 센다 — 같은 금액이 요약 표와 본문에 두 번 나온 것을
    두 건으로 세면 실제보다 위험해 보인다.
    """
    text = visible_text(html)
    cut = text.find(RELATED_BLOCK_HEADING)
    if cut != -1:
        text = text[:cut]
    found, seen = [], set()
    for pattern, kind in RISKY_CLAIM_PATTERNS:
        for match in re.finditer(pattern, text):
            phrase = match.group(0).strip()
            key = (phrase, kind)
            if key in seen:
                continue
            seen.add(key)
            found.append((phrase, kind))
    return found


def hard_claims(html: str) -> list:
    """수치 중에서도 '글의 주장 자체'인 것만 (문구, 종류)로 돌려준다.

    이 개수가 많은 글은 수치를 빼면 글이 남지 않으므로 다시 쓸 수 없다.
    내릴 글과 다시 쓸 글을 가르는 기준이 이것이다. HARD_CLAIM_KINDS 주석 참고.
    """
    return [(p, k) for p, k in find_risky_claims(html) if k in HARD_CLAIM_KINDS]


def looks_hand_written(html: str) -> bool:
    """본문이 이 파이프라인의 출력이 아닌 것으로 보이면 True.

    이 저장소가 발행·재작성하는 글은 예외 없이 관련 글 블록을 달고 나간다
    (generate_post.render_html → add_internal_links.render_block). 그 블록이
    통째로 없다는 것은 Blogger 편집기에서 사람이 본문을 갈아 끼웠다는 뜻이다.

    이 구분이 필요한 이유는 처리 결과가 되돌아오지 않기 때문이다. 내리는
    것(unpublish)은 초안 전환이라 되살릴 수 있지만, 다시 쓰는 것은 본문을
    교체해 버려서 사람이 쓴 원문이 어디에도 남지 않는다. 실제로 2026-09-21
    감사에서, 손으로 다시 쓴 글 한 편이 1143자라는 이유만으로 재작성 대상에
    들어왔다 — 그대로 돌렸으면 생성글로 덮였다.

    완벽한 판별이 아니다. 사람이 고친 뒤 add_internal_links 를 돌리면 블록이
    다시 붙어 생성글처럼 보인다. 그래서 이건 '건드리지 않을 이유'로만 쓰고,
    '건드려도 된다는 근거'로는 쓰지 않는다.
    """
    return RELATED_BLOCK_HEADING not in (html or "")


# --- 글 단위 검사 -------------------------------------------------------------


def _is_internal(href: str, blog_host: str) -> bool:
    if href.startswith("/"):
        return True
    if not blog_host:
        return False
    return blog_host.lower() in href.lower()


def check_post(
    post: dict,
    *,
    blog_host: str = "",
    shared_sentences=frozenset(),
    require_internal_link: bool = True,
) -> PostReport:
    """글 1편을 검사한다.

    post 는 Blogger API 의 post 리소스와 같은 모양의 dict:
    ``{"id", "title", "url", "content", "labels"}``. 발행 전 초안도 같은 모양을
    맞춰서 넘기면 발행된 글과 완전히 동일한 검사를 받는다.

    shared_sentences 는 "다른 글에도 등장하는 문장" 집합으로, 호출자가
    build_shared_sentences() 로 미리 만들어 넘긴다. 비어 있으면 템플릿 검사는
    건너뛴다 (비교 대상이 없을 때 무조건 통과시키는 쪽이 안전하다).

    require_internal_link 를 False 로 주면 내부 링크 없음이 차단이 아니라
    경고가 된다. 글이 이 한 편뿐인 새 블로그에서는 링크할 대상 자체가 없어서,
    이걸 차단으로 두면 첫 글을 영원히 발행할 수 없기 때문이다.
    """
    html = post.get("content") or ""
    info = extract(html)
    labels = post.get("labels") or []

    packed_len = len(re.sub(r"\s+", "", info.text))
    internal = [h for h in info.links if _is_internal(h, blog_host)]
    post_sentences = sentences(html)
    shared_hits = [s for s in post_sentences if s in shared_sentences]
    shared_ratio = len(shared_hits) / len(post_sentences) if post_sentences else 0.0

    report = PostReport(
        post_id=str(post.get("id", "")),
        title=(post.get("title") or "").strip(),
        url=post.get("url", ""),
        metrics={
            "text_chars": packed_len,
            "headings": info.headings,
            "paragraphs": info.paragraphs,
            "images": info.images,
            "tables": info.tables,
            "internal_links": len(internal),
            "labels": len(labels),
            "shared_sentence_ratio": round(shared_ratio, 3),
        },
    )

    add = report.findings.append
    if not report.title:
        add(Finding("no_title", BLOCK, "제목이 비어 있습니다."))
    if packed_len < MIN_TEXT_CHARS:
        add(
            Finding(
                "thin_body",
                BLOCK,
                f"본문 {packed_len}자 (최소 {MIN_TEXT_CHARS}자). "
                "'내용이 빈약한 콘텐츠'로 가장 많이 걸리는 항목입니다.",
            )
        )
    if info.headings < MIN_HEADINGS:
        add(
            Finding(
                "no_structure",
                BLOCK,
                f"소제목 {info.headings}개 (최소 {MIN_HEADINGS}개). h2/h3로 단락을 나누세요.",
            )
        )
    if info.paragraphs < MIN_PARAGRAPHS:
        add(Finding("few_paragraphs", WARN, f"문단 {info.paragraphs}개 (권장 {MIN_PARAGRAPHS}개 이상)."))
    if info.images == 0 and info.tables == 0:
        add(
            Finding(
                "no_visual",
                WARN,
                "이미지도 표도 없습니다. 직접 만든 도표·스크린샷이 가장 좋고, "
                "최소한 요약 표라도 있어야 벽글로 읽히지 않습니다.",
            )
        )
    if len(internal) < MIN_INTERNAL_LINKS:
        add(
            Finding(
                "no_internal_link",
                BLOCK if require_internal_link else WARN,
                "블로그 내 다른 글로 가는 링크가 없습니다.",
            )
        )
    if len(labels) < MIN_LABELS:
        add(Finding("no_label", WARN, "라벨(카테고리)이 없습니다."))
    risky = find_risky_claims(html)
    report.metrics["risky_claims"] = len(risky)
    if len(risky) > MAX_RISKY_CLAIMS:
        sample = ", ".join(f"{p}({k})" for p, k in risky[:5])
        add(
            Finding(
                "unverified_figures",
                BLOCK,
                f"확인되지 않은 수치 {len(risky)}건 (허용 {MAX_RISKY_CLAIMS}건): {sample}"
                + (" 외" if len(risky) > 5 else "")
                + ". 자료 없이 생성된 수치는 사실과 다를 수 있습니다. "
                "원 출처로 확인하거나, 수치를 빼고 '어디서 확인하는지'로 바꾸세요.",
            )
        )

    if shared_ratio > MAX_SHARED_SENTENCE_RATIO:
        add(
            Finding(
                "templated",
                BLOCK,
                f"본문 문장의 {shared_ratio:.0%}가 다른 글에도 그대로 있습니다 "
                f"(허용 {MAX_SHARED_SENTENCE_RATIO:.0%}). 템플릿을 돌린 것으로 판정됩니다.",
            )
        )

    return report


def build_shared_sentences(posts: list, *, min_posts: int = 2) -> frozenset:
    """min_posts 편 이상에 공통으로 등장하는 문장 집합."""
    counts = {}
    for post in posts:
        for s in set(sentences(post.get("content") or "")):
            counts[s] = counts.get(s, 0) + 1
    return frozenset(s for s, n in counts.items() if n >= min_posts)


def find_near_duplicates(posts: list, threshold: float = NEAR_DUPLICATE_JACCARD) -> list:
    """(글A, 글B, 유사도) 목록. 사실상 같은 글이 두 번 올라간 경우를 잡는다."""
    prepared = [(p, shingles(p.get("content") or "")) for p in posts]
    pairs = []
    for i in range(len(prepared)):
        for j in range(i + 1, len(prepared)):
            score = jaccard(prepared[i][1], prepared[j][1])
            if score >= threshold:
                pairs.append((prepared[i][0], prepared[j][0], round(score, 3)))
    return sorted(pairs, key=lambda t: -t[2])


# --- 사이트 단위 검사 ---------------------------------------------------------


def _page_present(pages: list, keywords: list) -> bool:
    for page in pages:
        haystack = f"{page.get('title', '')} {page.get('url', '')}".lower()
        if any(k.lower() in haystack for k in keywords):
            return True
    return False


def missing_pages(pages: list) -> list:
    """아직 없는 필수 페이지의 키 목록. publish_pages.py 가 이 목록만 게시한다."""
    return [k for k, (_, kws) in REQUIRED_PAGES.items() if not _page_present(pages, kws)]


def check_site(posts: list, pages: list, *, blog_host: str = "") -> SiteReport:
    """블로그 전체를 검사한다. posts/pages 는 Blogger API 리소스 모양의 dict 목록."""
    shared = build_shared_sentences(posts)
    reports = [check_post(p, blog_host=blog_host, shared_sentences=shared) for p in posts]
    site = SiteReport(post_reports=reports, duplicate_pairs=find_near_duplicates(posts))
    add = site.findings.append

    if len(posts) < MIN_PUBLISHED_POSTS:
        add(
            Finding(
                "too_few_posts",
                BLOCK,
                f"발행 글 {len(posts)}편 (권장 최소 {MIN_PUBLISHED_POSTS}편). "
                "공식 기준은 아니지만, 글이 적으면 '아직 준비 중인 화면'으로 반려됩니다.",
            )
        )

    if reports:
        pass_ratio = sum(1 for r in reports if r.passed) / len(reports)
        if pass_ratio < MIN_PASS_RATIO:
            failing = sum(1 for r in reports if r.blocked)
            add(
                Finding(
                    "low_pass_ratio",
                    BLOCK,
                    f"{len(reports)}편 중 {failing}편이 기준 미달 "
                    f"(통과율 {pass_ratio:.0%}, 목표 {MIN_PASS_RATIO:.0%}). "
                    "미달 글은 보강하거나 비공개로 내려야 합니다.",
                )
            )

    for key in missing_pages(pages):
        label = REQUIRED_PAGES[key][0]
        add(
            Finding(
                f"missing_page_{key}",
                BLOCK,
                f"필수 페이지 없음: {label}. `publish_pages.py` 로 게시할 수 있습니다.",
            )
        )

    for a, b, score in site.duplicate_pairs:
        add(
            Finding(
                "near_duplicate",
                BLOCK,
                f"거의 같은 글 (유사도 {score:.0%}): "
                f"'{a.get('title')}' ↔ '{b.get('title')}'",
            )
        )

    return site
