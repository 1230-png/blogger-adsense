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
| `BLOGGER_LABELS_EXTRA` | ⏳ 선택 | 모든 글에 공통으로 붙일 라벨(콤마 구분) |

Repository → Settings → Secrets and variables → Actions → New repository secret 에서 등록합니다.

---

## 3. 동작 방식

```
00:00 KST ──→ data/topics.csv 에서 아직 안 쓴 주제 1개 선정
            ├─ Groq로 서론+소제목4~6개+결론 구조의 글 생성 (최소 1,200자 강제)
            ├─ Blogger API로 발행 (즉시 공개)
            └─ data/used_topics.json 에 발행 기록 추가 후 커밋
```

- `workflow_dispatch`로 수동 실행도 가능하며, `category` 입력값으로
  `finance / health / tech / life / self_dev` 중 하나를 지정할 수 있습니다.
  비워두면 전체 카테고리 중 무작위로 선택합니다.
- 예약 실행 시각은 `.github/workflows/blogger_blog_daily.yml` 의
  `cron: '0 15 * * *'`(UTC) = **매일 00:00 KST** 입니다. GitHub 예약 실행은
  정상적으로 25~60분 늦게 시작될 수 있으며, 고장이 아닙니다.
- 초반에 애드센스 재심사에 필요한 게시글 수를 빨리 채우고 싶다면, Actions 탭에서
  **Run workflow**를 여러 번 수동 실행할 수 있습니다. 다만 스팸성 대량 발행으로
  보이지 않도록 며칠에 걸쳐 나눠 발행하는 것을 권장합니다.

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
`tech`(IT/생활꿀팁), `life`(생활정보), `self_dev`(자기계발) 다섯 가지입니다.
블로그의 실제 주제(예: 특정 지역 맛집, 특정 취미 등)에 더 맞게 이 파일을
직접 편집해서 채우면 SEO/애드센스 승인에 더 유리합니다.

---

## 6. 애드센스 신청/재심사 체크리스트

- [ ] 최소 20~30편 이상 발행 (업계 통용 안전 기준, 구글 공식 수치 아님)
- [ ] 각 글이 실질적인 정보를 담고 있는지 직접 몇 편 읽어보고 확인
- [ ] Blogger 관리 화면 → 레이아웃/라벨 등 사이트 구조 정리
- [ ] 개인정보처리방침, 블로그 소개 페이지 등록 (Blogger는 "페이지" 메뉴로 추가)
- [ ] Blogger 관리 화면의 **수익(AdSense)** 탭에서 애드센스 연동 신청

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

**"주제가 계속 겹치는 것 같다"**
→ `blogger_blog/data/used_topics.json`에 발행 기록이 잘 커밋되고 있는지
  Actions 로그에서 4️⃣ 단계를 확인하세요.
