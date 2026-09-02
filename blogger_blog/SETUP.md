# Blogger Blog 자동 발행 설정 가이드

## 개요

Groq API로 매일 실질적인 정보성 블로그 글을 생성해 **Google Blogger**에 자동
발행하는 파이프라인입니다. 구조는 **주제 선정 → 글 생성 → 발행 → 기록** 네
단계이며, 이 저장소는 YouTube 자동화 저장소(`1230-png/Soop1230`)와 완전히
분리된 독립 저장소입니다. 공유하는 코드도, 시크릿도 없습니다.

> ℹ️ 원래 티스토리 기준으로 만들었으나, 티스토리 Open API는 2024년 2월
> 완전히 종료되어(공식 공지: notice.tistory.com/2664) 더 이상 자동 발행이
> 불가능합니다. 반면 Blogger는 구글이 직접 운영·유지보수하는 서비스라
> Blogger API v3가 살아있고, 관리 화면에 애드센스 연동 탭이 기본 내장돼
> 있어 지금 상황(구글 계정으로 애드센스 신청)에 더 잘 맞습니다.

이 파이프라인은 애드센스 재심사 사유였던 **"가치가 별로 없는 콘텐츠"** 문제를
겨냥해서 만들어졌습니다. `generate_post.py`는 서론 - 소제목 4~6개 - 결론
구조를 강제하고, 본문이 최소 1,200자를 넘지 못하면 발행하지 않고 실패
처리합니다(얇은 글을 계속 쌓으면 재심사도 또 떨어지기 때문).

⚠️ 참고로 구글은 최근 "대량 자동 생성 콘텐츠(scaled content abuse)" 자체를
스팸 정책으로 별도 규정하고 있습니다. 완전 자동화라도 발행 빈도를 하루 1~2편
수준으로 유지하고, 가끔 실제로 글을 열어서 품질을 직접 확인하는 것을
권장합니다.

---

## 1. 사전 준비

### 1-1. Blogger 블로그 만들기

1. https://www.blogger.com 에서 애드센스를 신청할 구글 계정으로 새 블로그 생성
2. 관리 화면 URL이 `blogger.com/blog/posts/1234567890123456789` 형태인데,
   여기서 숫자 부분이 **BLOGGER_BLOG_ID** 입니다. 메모해 두세요.

### 1-2. Google Cloud Console에서 API 사용 설정

1. https://console.cloud.google.com 접속 (블로그와 같은 구글 계정)
2. 새 프로젝트 생성 (또는 기존 YouTube 자동화용 프로젝트 재사용 가능)
3. **API 및 서비스 → 라이브러리** 에서 `Blogger API v3` 검색 후 **사용 설정**
4. **API 및 서비스 → OAuth 동의화면**: 외부/테스트 사용자로 본인 계정 등록
5. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth
   클라이언트 ID → 데스크톱 앱** 생성 후 JSON 다운로드 → `client_secret.json`
   으로 이름 변경

> 이미 YouTube 자동화용으로 만들어둔 `client_secret.json`이 있다면, 같은
> 구글 클라우드 프로젝트에서 `Blogger API v3`만 추가로 사용 설정하면 그 파일을
> 그대로 재사용할 수 있습니다.

### 1-3. 리프레시 토큰 발급

```bash
pip install google-auth-oauthlib
python blogger_blog/scripts/get_blogger_token.py client_secret.json
```

1. 출력된 URL을 브라우저(모바일 가능)에서 열고 블로그 소유 계정으로
   로그인/동의합니다.
2. 터미널에 `BLOGGER_CLIENT_ID`, `BLOGGER_CLIENT_SECRET`,
   `BLOGGER_REFRESH_TOKEN` 세 값이 출력됩니다.

---

## 2. GitHub Secrets 등록

| Secret Name | 필수 | 설명 |
|---|---|---|
| `GROQ_API_KEY` | ✅ | 기존에 이미 등록된 값 재사용 |
| `BLOGGER_REFRESH_TOKEN` | ✅ | 1-3 단계에서 발급 |
| `BLOGGER_CLIENT_ID` | ✅ | 1-3 단계에서 발급 |
| `BLOGGER_CLIENT_SECRET` | ✅ | 1-3 단계에서 발급 |
| `BLOGGER_BLOG_ID` | ✅ | 1-1 단계에서 메모한 숫자 ID |
| `BLOGGER_CONTACT_EMAIL` | ✅ | 소개·문의·개인정보처리방침 페이지에 표시할 이메일 |
| `BLOGGER_BLOG_NAME` | ⏳ 선택 | 페이지에 표시할 블로그 이름 (비우면 Blogger 설정값) |
| `BLOGGER_LABELS_EXTRA` | ⏳ 선택 | 모든 글에 공통으로 붙일 라벨(콤마 구분) |

Repository → Settings → Secrets and variables → Actions → New repository secret 에서 등록합니다.

> ⚠️ 이 저장소는 **public** 입니다. `BLOGGER_CONTACT_EMAIL` 을 파일에 직접
> 적지 마세요. 고정 페이지 템플릿(`blogger_blog/pages/*.html`)은
> `{{CONTACT_EMAIL}}` 토큰만 갖고 있고, 값은 발행 시점에 주입됩니다.

---

## 3. 동작 방식

```
09:00 KST ──→ pytest 로 품질 게이트 자체를 먼저 검사
         ├─ data/topics.csv 에서 아직 안 쓴 주제 1개 선정
         ├─ Groq로 글 생성 → 요약 표 + 소제목 5~7개 + 내부 링크 3개로 조립
         │   └ 산문 1,600자 미만이면 한 번 재생성, 그래도 미달이면 중단
         ├─ quality.py 게이트 통과 시에만 Blogger 발행
         │   └ 미달이면 발행하지 않고 그날을 건너뛴다 (워크플로 실패는 정상)
         └─ data/used_topics.json 에 발행 기록 추가 후 커밋
```

- `workflow_dispatch`로 수동 실행도 가능하며, `category` 입력값으로
  `finance / health / tech / life / self_dev` 중 하나를 지정할 수 있습니다.
  비워두면 전체 카테고리 중 무작위로 선택합니다.
- 예약 실행 시각은 `.github/workflows/blogger_blog_daily.yml` 의
  `cron: '0 0 * * *'`(UTC) = **매일 09:00 KST**, 하루 1편입니다.
  GitHub 예약 실행은 정상적으로 25~60분 늦게 시작될 수 있으며, 고장이 아닙니다.
- **글 수를 빨리 채우려고 수동 실행을 반복하지 마세요.** 사람 검토 없이
  LLM으로 만든 글을 몰아서 올리는 것은 Google이 *scaled content abuse*로
  설명하는 패턴이고, 애드센스 반려 사유였던 "가치가 별로 없는 콘텐츠"와 같은
  뿌리입니다. 하루 2편에서 1편으로 줄인 것도 같은 이유입니다.
  자세한 내용은 [`ADSENSE_FIX.md`](ADSENSE_FIX.md) 를 참고하세요.

### 다른 워크플로

| 워크플로 | 실행 | 하는 일 |
|---|---|---|
| **Blogger AdSense Audit** | 매주 월 10:00 KST + 수동 | 발행된 글 전체를 진단해 리포트 생성. 미달이 있으면 실패(빨간 X)로 끝난다 — **재심사 요청 전에 초록불인지 확인하는 용도** |
| **Blogger Required Pages** | 수동 | 소개·문의·개인정보처리방침·면책조항 페이지 게시. 여러 번 돌려도 안전 |

---

## 4. 로컬 테스트

```bash
export GROQ_API_KEY=your_key
export BLOGGER_REFRESH_TOKEN=your_refresh_token
export BLOGGER_CLIENT_ID=your_client_id
export BLOGGER_CLIENT_SECRET=your_client_secret
export BLOGGER_BLOG_ID=your_blog_id

python blogger_blog/scripts/pick_topic.py | tee topic.json
cat topic.json | python blogger_blog/scripts/generate_post.py | tee post.json
cat post.json | python blogger_blog/scripts/publish_post.py
```

발행까지 하고 싶지 않다면 마지막 줄(publish_post.py)은 생략하고
`post.json` 내용만 확인하면 됩니다.

---

## 5. 주제 추가/커스터마이징

`blogger_blog/data/topics.csv` 에 `category,topic` 형식으로 줄을 추가하면
됩니다. 지금 등록된 카테고리는 `finance`(재테크), `health`(건강),
`tech`(IT/생활꿀팁), `life`(생활정보), `self_dev`(자기계발) 다섯 가지이며,
카테고리당 50개씩 **총 250개**가 들어 있습니다(하루 2편 기준 약 4개월치).

> ⚠️ 주제에 **쉼표를 넣지 마세요.** 따옴표 없는 CSV라 열이 밀립니다.

블로그의 실제 주제(예: 특정 지역 맛집, 특정 취미 등)에 더 맞게 이 파일을
직접 편집해서 채우면 SEO/애드센스 승인에 더 유리합니다.

### 주제가 소진되면

250개를 모두 발행하면 `pick_topic.py` 가 해당 카테고리의 범위 설명을
Groq 에 넘겨 **새 세부 주제를 만들어냅니다.** 생성된 후보는
`used_topics.json` 과 대조해 이미 쓴 주제와 겹치면 버리고 다시 만듭니다
(띄어쓰기·문장부호만 다른 것도 같은 주제로 봅니다).

생성까지 실패하면 그때만 기존 주제를 재사용하며, 로그에 경고를 남깁니다.
그 경고가 보이면 `topics.csv` 에 주제를 더 채워 넣으세요.

---

## 6. 애드센스 신청/재심사 체크리스트

> 반려된 상태에서 무엇을 어떤 순서로 해야 하는지는
> **[`ADSENSE_FIX.md`](ADSENSE_FIX.md)** 에 자세히 정리돼 있습니다.

- [ ] `BLOGGER_CONTACT_EMAIL` 시크릿 등록
- [ ] **Blogger Required Pages** 워크플로 실행 → 필수 페이지 4종 게시
- [ ] Blogger 관리 화면 → 레이아웃 → **페이지 가젯 추가**로 네 페이지 모두 노출
      (페이지를 만들어도 메뉴에 걸지 않으면 심사자가 찾지 못합니다)
- [ ] `blogger_blog/pages/about.html` 을 본인 이야기로 수정 후 재실행
- [ ] **Blogger AdSense Audit** 워크플로 실행 → 미달 글 목록 확인
- [ ] 미달 글을 보강 / 통합 / 비공개 처리 (자동화 불가, 직접 읽고 판단)
- [ ] 감사 워크플로가 **초록불**이 된 것을 확인
- [ ] Blogger 관리 화면의 **수익(AdSense)** 탭에서 재심사 요청

> ⚠️ 빨간불 상태로 재심사를 요청하지 마세요. 반복 반려는 불리하게 작용합니다.

---

## 7. 트러블슈팅

**"BLOGGER_REFRESH_TOKEN / BLOGGER_CLIENT_ID / BLOGGER_CLIENT_SECRET 환경변수가 필요합니다"**
→ GitHub Secrets 등록 여부 확인

**"Blogger 발행 실패"**
→ `BLOGGER_BLOG_ID`가 맞는지, Google Cloud Console에서 Blogger API가
  사용 설정되어 있는지, 리프레시 토큰이 해당 블로그 소유 계정으로
  발급되었는지 확인. 필요하면 `get_blogger_token.py`로 재발급.

**"본문이 짧아서 중단됩니다"**
→ Groq 응답이 짧게 나온 경우로, 자동으로 1회 재시도합니다. 계속 실패하면
  `GROQ_MODEL` 환경변수로 다른 모델을 지정해 보세요.

**"사용 가능한 Groq 모델이 없습니다" / Groq 404 에러**
→ Groq 가 해당 모델을 퇴역시킨 경우입니다(무료 티어는 주기적으로 바뀝니다).
  기본값은 `openai/gpt-oss-120b` → `openai/gpt-oss-20b` 순으로 자동
  폴백하지만 둘 다 사라졌다면, https://console.groq.com/docs/models 에서
  현재 모델 ID를 확인해 `GROQ_MODEL` 시크릿으로 지정하세요.

**"주제가 계속 겹치는 것 같다"**
→ `blogger_blog/data/used_topics.json`에 발행 기록이 잘 커밋되고 있는지
  Actions 로그에서 4️⃣ 단계를 확인하세요. 기록이 커밋되지 않으면 다음 실행이
  같은 주제를 다시 고릅니다.

**"기존 주제를 재사용합니다" 경고가 뜬다**
→ 250개를 전부 발행했고 새 주제 생성도 실패한 상태입니다. `GROQ_API_KEY`
  시크릿이 살아 있는지 확인하고, `topics.csv` 에 주제를 추가하세요.
