# blogger-adsense

Groq + Google Blogger API v3 로 매일 정보성 블로그 글을 자동 발행하는 파이프라인.
**전부 무료 티어**로 동작합니다.

## 왜 별도 저장소인가

YouTube 자동화 저장소(`1230-png/Soop1230` — `@200-y3b`, `@reality_bizarre`)와
분리했습니다.

- 제품·OAuth 스코프·시크릿·의존성이 전부 다르고, 공유되는 코드가 0줄입니다.
- 같은 저장소에 두면 `run_shorts.yml`(00:00 UTC)과 예약 시각이 겹치는데,
  둘 다 같은 브랜치에 auto-commit/push 를 하므로 push 경합이 발생합니다.
- 유튜브 자동화는 이미 동작 검증이 끝난 상태라, 블로그 파이프라인 때문에
  건드리지 않습니다.

## 동작

```
매일 09:00 / 21:00 KST (cron '0 0,12 * * *' UTC) — 하루 2편
  1️⃣ blogger_blog/data/topics.csv 에서 아직 안 쓴 주제 1개 선정
  2️⃣ Groq(openai/gpt-oss-120b)로 서론 + 소제목 4~6개 + 결론 구조 생성
     └ 본문 1,200자 미만이면 발행하지 않고 실패 처리 (얇은 콘텐츠 방지)
  3️⃣ Blogger API v3 로 발행
  4️⃣ blogger_blog/data/used_topics.json 에 기록 후 커밋
```

수동 실행은 Actions 탭 → **Run workflow**. `category` 입력으로
`finance / health / tech / life / self_dev` 중 하나를 지정할 수 있습니다.

## 필요한 GitHub Secrets

| Secret | 필수 | 발급처 |
|---|---|---|
| `GROQ_API_KEY` | ✅ | https://console.groq.com (무료) |
| `BLOGGER_CLIENT_ID` | ✅ | Google Cloud Console |
| `BLOGGER_CLIENT_SECRET` | ✅ | Google Cloud Console |
| `BLOGGER_REFRESH_TOKEN` | ✅ | `blogger_blog/scripts/get_blogger_token.py` |
| `BLOGGER_BLOG_ID` | ✅ | Blogger 관리 URL 의 숫자 부분 |
| `BLOGGER_LABELS_EXTRA` | ⏳ | 모든 글 공통 라벨 (콤마 구분) |

> ⚠️ 이 저장소는 **public** 입니다 (Actions 분 수 무제한). API 키는 반드시
> Secrets 에만 넣고, 문서·코드에 평문으로 적지 마세요.

## 비용

| 항목 | 무료 여부 |
|---|---|
| GitHub Actions | ✅ public 저장소는 분 수 무제한 |
| Groq API | ✅ 무료 티어 |
| Blogger API v3 | ✅ 무료 |
| Google Cloud 프로젝트 | ✅ 무료 (Blogger API v3 "사용 설정"만 하면 됨) |

TTS·영상 생성이 없어 ElevenLabs 무료 할당량(10k자/월)을 전혀 쓰지 않습니다.

## 자세한 설정

**→ [`blogger_blog/SETUP.md`](blogger_blog/SETUP.md)**
