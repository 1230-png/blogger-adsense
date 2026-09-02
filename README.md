# blogger-adsense

Groq + Google Blogger API v3 로 정보성 블로그 글을 자동 발행하는 파이프라인.
**전부 무료 티어**로 동작합니다.

> ⚠️ **애드센스가 "가치가 별로 없는 콘텐츠"로 반려한 상태라면
> → [`blogger_blog/ADSENSE_FIX.md`](blogger_blog/ADSENSE_FIX.md) 를 먼저 읽으세요.**
> 원인 분석과, 코드로 고친 것 / 사람이 해야 하는 것이 순서대로 정리돼 있습니다.

## 왜 별도 저장소인가

YouTube 자동화 저장소(`1230-png/Soop1230` — `@200-y3b`, `@reality_bizarre`)와
분리했습니다.

- 제품·OAuth 스코프·시크릿·의존성이 전부 다르고, 공유되는 코드가 0줄입니다.
- 같은 저장소에 두면 `run_shorts.yml`(00:00 UTC)과 예약 시각이 겹치는데,
  둘 다 같은 브랜치에 auto-commit/push 를 하므로 push 경합이 발생합니다.
- 유튜브 자동화는 이미 동작 검증이 끝난 상태라, 블로그 파이프라인 때문에
  건드리지 않습니다.

## 구조

```
blogger_blog/
├── scripts/
│   ├── quality.py          품질 게이트 ★ 발행과 감사가 같이 쓰는 단일 기준
│   ├── blogger_api.py      Blogger API v3 클라이언트 (글·페이지 공용)
│   ├── pick_topic.py       주제 선정 (소진되면 Groq 로 새 주제 생성)
│   ├── generate_post.py    글 생성 + HTML 조립
│   ├── publish_post.py     발행 (게이트 미달이면 발행 중단)
│   ├── publish_pages.py    필수 고정 페이지 게시
│   ├── audit_blog.py       발행된 글 전체 진단 → 리포트
│   └── get_blogger_token.py  OAuth refresh token 발급 (로컬 1회)
├── pages/                  소개·문의·개인정보처리방침·면책조항 템플릿
├── data/
│   ├── topics.csv          주제 후보 250개
│   └── used_topics.json    발행 기록 (내부 링크 생성에도 쓰임)
├── tests/                  pytest — 네트워크·자격증명 불필요
├── ADSENSE_FIX.md          반려 대응 문서 ★
└── SETUP.md                최초 설정
```

## 동작

```
매일 09:00 KST (cron '0 0 * * *' UTC) — 하루 1편
  0️⃣ pytest 로 품질 게이트 자체를 먼저 검사
  1️⃣ topics.csv 에서 아직 안 쓴 주제 1개 선정
     └ 전부 소진되면 Groq 로 새 주제 생성 (기발행 주제와 대조해 중복 차단)
  2️⃣ Groq 로 본문 생성 → 요약 표 + 소제목 5~7개 + 내부 링크 3개로 조립
     └ 산문 1,600자 미만이면 한 번 재생성, 그래도 미달이면 중단
  3️⃣ quality.py 게이트 통과 시에만 Blogger 발행
     └ 미달이면 발행하지 않고 그날을 건너뛴다 (워크플로 실패는 정상 동작)
  4️⃣ used_topics.json 에 기록 후 커밋
```

### 워크플로

| 워크플로 | 실행 | 하는 일 |
|---|---|---|
| **Blogger Blog Daily** | 매일 09:00 KST | 글 1편 생성·발행 |
| **Blogger AdSense Audit** | 매주 월 10:00 KST + 수동 | 발행된 글 전체 진단 → 리포트 |
| **Blogger Required Pages** | 수동 | 필수 고정 페이지 4종 게시 |

수동 실행은 Actions 탭 → **Run workflow**.

## 품질 게이트

`quality.py` 하나가 **발행 전 검사와 발행 후 감사에 모두** 쓰입니다. 기준이
두 벌이 되지 않으므로, "발행은 됐는데 감사에서 떨어지는" 글이 생기지 않습니다.

차단(🔴) 항목: 본문 1,700자 미만 · 소제목 3개 미만 · 내부 링크 없음 ·
다른 글과 겹치는 문장 30% 초과 · 거의 같은 글 존재 · 필수 페이지 누락 ·
발행 글 20편 미만 · 통과율 90% 미만

**이 숫자들은 Google이 공개한 기준이 아닙니다.** 정책 문서가 서술적으로
요구하는 바를 자동 검사로 옮긴 운영용 휴리스틱입니다. 통과가 승인을
보장하지 않습니다. 자세한 설명은 `quality.py` 상단 주석에 있습니다.

## 테스트

```bash
pip install -r blogger_blog/scripts/requirements.txt
python -m pytest blogger_blog/tests -q
```

네트워크도 자격증명도 필요 없습니다. 매일 발행 워크플로가 발행 전에 먼저
돌립니다.

## 필요한 GitHub Secrets

| Secret | 필수 | 발급처 |
|---|---|---|
| `GROQ_API_KEY` | ✅ | https://console.groq.com (무료) |
| `BLOGGER_CLIENT_ID` | ✅ | Google Cloud Console |
| `BLOGGER_CLIENT_SECRET` | ✅ | Google Cloud Console |
| `BLOGGER_REFRESH_TOKEN` | ✅ | `blogger_blog/scripts/get_blogger_token.py` |
| `BLOGGER_BLOG_ID` | ✅ | Blogger 관리 URL 의 숫자 부분 |
| `BLOGGER_CONTACT_EMAIL` | ✅ | 고정 페이지에 표시할 문의용 이메일 |
| `BLOGGER_BLOG_NAME` | ⏳ | 블로그 이름 (비우면 Blogger 설정값) |
| `BLOGGER_LABELS_EXTRA` | ⏳ | 모든 글 공통 라벨 (콤마 구분) |

> ⚠️ 이 저장소는 **public** 입니다. API 키와 이메일 주소는 반드시 Secrets 에만
> 넣고, 문서·코드에 평문으로 적지 마세요. 그래서 고정 페이지 템플릿도
> `{{CONTACT_EMAIL}}` 토큰만 갖고 있습니다.

## 비용

| 항목 | 무료 여부 |
|---|---|
| GitHub Actions | ✅ public 저장소는 분 수 무제한 |
| Groq API | ✅ 무료 티어 |
| Blogger API v3 | ✅ 무료 |
| Google Cloud 프로젝트 | ✅ 무료 (Blogger API v3 "사용 설정"만 하면 됨) |

## 자세한 설정

- 최초 설정: [`blogger_blog/SETUP.md`](blogger_blog/SETUP.md)
- 애드센스 반려 대응: [`blogger_blog/ADSENSE_FIX.md`](blogger_blog/ADSENSE_FIX.md)
