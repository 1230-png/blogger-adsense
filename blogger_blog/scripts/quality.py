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
