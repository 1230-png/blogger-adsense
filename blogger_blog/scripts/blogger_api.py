#!/usr/bin/env python3
"""Blogger API v3 클라이언트 공용 모듈.

원래 이 인증 코드는 publish_post.py 안에만 있어서, 발행 말고 다른 일
(발행된 글 감사, 필수 페이지 게시)을 하려면 복사할 수밖에 없었다.
자격증명 처리가 두 벌이 되면 한쪽만 고쳐지므로 여기로 뺐다.

필요 환경변수:
- BLOGGER_REFRESH_TOKEN / BLOGGER_CLIENT_ID / BLOGGER_CLIENT_SECRET
  : get_blogger_token.py 로 발급
- BLOGGER_BLOG_ID
  : Blogger 관리 화면 URL(blogger.com/blog/posts/<이 숫자>)의 숫자 부분
"""

import os
import sys
from urllib.parse import urlparse

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# 글과 페이지를 모두 쓰려면 읽기 전용이 아닌 전체 스코프가 필요하다.
SCOPES = ["https://www.googleapis.com/auth/blogger"]

# Blogger API 는 페이지네이션 상한이 있어서, 한 번에 전부 달라고 해도
# 나눠서 준다. maxResults 를 넉넉히 주고 nextPageToken 을 따라간다.
PAGE_SIZE = 50


def get_blogger_client():
    refresh_token = os.environ.get("BLOGGER_REFRESH_TOKEN")
    client_id = os.environ.get("BLOGGER_CLIENT_ID")
    client_secret = os.environ.get("BLOGGER_CLIENT_SECRET")

    if not refresh_token or not client_id or not client_secret:
        print(
            "❌ BLOGGER_REFRESH_TOKEN / BLOGGER_CLIENT_ID / BLOGGER_CLIENT_SECRET "
            "환경변수가 필요합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    credentials.refresh(google.auth.transport.requests.Request())

    return build("blogger", "v3", credentials=credentials)


def require_blog_id() -> str:
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        print("❌ BLOGGER_BLOG_ID 환경변수가 필요합니다.", file=sys.stderr)
        sys.exit(1)
    return blog_id


def get_blog(service, blog_id: str) -> dict:
    return service.blogs().get(blogId=blog_id).execute()


def blog_host(blog: dict) -> str:
    """내부 링크 판정에 쓸 호스트명. 'soo-c9.blogspot.com' 형태."""
    return urlparse(blog.get("url", "")).netloc


def list_posts(service, blog_id: str, *, status: str = "LIVE") -> list:
    """발행된 글 전체를 본문까지 포함해 가져온다.

    fetchBodies=True 가 없으면 content 가 비어서 오고, 그러면 품질 검사가
    모든 글을 '본문 0자'로 판정해 버린다.
    """
    posts, token = [], None
    while True:
        response = (
            service.posts()
            .list(
                blogId=blog_id,
                status=status,
                fetchBodies=True,
                fetchImages=True,
                maxResults=PAGE_SIZE,
                pageToken=token,
            )
            .execute()
        )
        posts.extend(response.get("items", []))
        token = response.get("nextPageToken")
        if not token:
            return posts


def list_pages(service, blog_id: str) -> list:
    """고정 페이지(소개·문의 등) 목록.

    초안 상태의 페이지는 방문자에게 보이지 않으므로 심사에서도 없는 것과
    같다. 그래서 status 를 함께 받아 두고, 호출자가 LIVE 만 거를 수 있게 한다.
    """
    pages, token = [], None
    while True:
        response = (
            service.pages()
            .list(blogId=blog_id, fetchBodies=True, maxResults=PAGE_SIZE, pageToken=token)
            .execute()
        )
        pages.extend(response.get("items", []))
        token = response.get("nextPageToken")
        if not token:
            return pages


def live_pages(service, blog_id: str) -> list:
    return [p for p in list_pages(service, blog_id) if p.get("status", "LIVE") == "LIVE"]


def insert_page(service, blog_id: str, title: str, content: str) -> dict:
    body = {"kind": "blogger#page", "title": title, "content": content}
    return service.pages().insert(blogId=blog_id, body=body, isDraft=False).execute()


def update_page(service, blog_id: str, page_id: str, title: str, content: str) -> dict:
    body = {"kind": "blogger#page", "title": title, "content": content}
    return service.pages().update(blogId=blog_id, pageId=page_id, body=body).execute()
