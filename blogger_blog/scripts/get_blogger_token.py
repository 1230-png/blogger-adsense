import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

# Blogger 글쓰기 권한 스코프
SCOPES = ["https://www.googleapis.com/auth/blogger"]


def generate_blogger_tokens():
    client_secret_file = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"

    if not os.path.exists(client_secret_file):
        print(f"❌ 에러: {client_secret_file} 파일이 현재 디렉토리에 없습니다.")
        print("구글 클라우드 콘솔에서 데스크톱 앱용 클라이언트 보안 비밀 JSON을 다운로드 받아 파일명을 변경해 주세요.")
        print("(기존 YouTube 업로드용 client_secret.json을 그대로 재사용해도 됩니다. 단, 같은")
        print(" 구글 클라우드 프로젝트에서 'Blogger API'가 사용 설정되어 있어야 합니다.)")
        return

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, scopes=SCOPES)

    print("\n" + "=" * 60)
    print("📢 아래 생성된 URL 링크를 전체 복사하여 모바일 브라우저(크롬 등)에 붙여넣으세요.")
    print("   블로그를 소유한 구글 계정으로 로그인/동의하세요.")
    print("=" * 60 + "\n")

    credentials = flow.run_local_server(
        host="localhost",
        port=8080,
        authorization_prompt_message="인증을 위해 다음 링크로 이동하세요: {url}",
        success_message="인증이 완료되었습니다. 터미널을 확인하세요.",
        open_browser=False,
    )

    print("\n" + "✅" * 15 + " 토큰 추출 성공 " + "✅" * 15)
    print(f"📌 BLOGGER_CLIENT_ID: {credentials.client_id}")
    print(f"📌 BLOGGER_CLIENT_SECRET: {credentials.client_secret}")
    print(f"🔥 BLOGGER_REFRESH_TOKEN (GitHub Secrets 등록용): {credentials.refresh_token}")
    print("=" * 60)
    print("ℹ️ 위 세 값을 각각 GitHub Secrets에 등록하세요.")
    print("ℹ️ BLOGGER_BLOG_ID는 Blogger 관리 화면(blogger.com/blog/posts/<숫자>) URL에서 확인하세요.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    generate_blogger_tokens()
