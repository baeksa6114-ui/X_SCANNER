"""Asynchronous Twikit login and keyword pagination logic."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from httpx import RequestError
from twikit import Client
from twikit.errors import (
    AccountLocked,
    AccountSuspended,
    Forbidden,
    RequestTimeout,
    ServerError,
    TooManyRequests,
    Unauthorized,
)

from config import (
    COOKIE_PATH,
    MAX_PAGES,
    MAX_RETRIES,
    MAX_STALLED_PAGES,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    RETRY_BASE_DELAY,
    Credentials,
)
from twikit_compat import apply_twikit_compatibility
from utils import normalize_tweet, redact_error, safe_getattr


apply_twikit_compatibility()

T = TypeVar("T")
AUTH_ERRORS = (Unauthorized, Forbidden, AccountLocked, AccountSuspended)
RETRYABLE_ERRORS = (
    TooManyRequests,
    RequestTimeout,
    ServerError,
    RequestError,
    ConnectionError,
    TimeoutError,
    OSError,
)


class AuthenticationError(RuntimeError):
    """Raised when neither saved cookies nor credentials can authenticate."""


class XKeywordCrawler:
    def __init__(
        self,
        credentials: Credentials,
        *,
        client: Client | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.credentials = credentials
        self.client = client or Client("ko-KR")
        self.sleep = sleep
        self.results: list[dict[str, Any]] = []
        self.seen_ids: set[str] = set()
        self._using_cookies = False
        self._credential_login_attempted = False

    @property
    def _secrets(self) -> tuple[str | None, ...]:
        return (
            self.credentials.username,
            self.credentials.email,
            self.credentials.password,
            self.credentials.auth_token,
            self.credentials.ct0,
        )

    def _error_text(self, error: BaseException) -> str:
        return redact_error(error, self._secrets)

    async def authenticate(self, *, force_credentials: bool = False) -> None:
        """Prefer saved cookies; use credentials for first login or cookie recovery."""
        if self.credentials.browser_cookies_complete and not force_credentials:
            self.client.set_cookies(
                {
                    "auth_token": self.credentials.auth_token,
                    "ct0": self.credentials.ct0,
                }
            )
            self.client.save_cookies(str(COOKIE_PATH))
            self._using_cookies = True
            print("[LOGIN] 브라우저 쿠키를 적용했습니다")
            return

        if COOKIE_PATH.exists() and not force_credentials:
            try:
                self.client.load_cookies(str(COOKIE_PATH))
                self._using_cookies = True
                print("[LOGIN] 저장된 쿠키를 불러왔습니다")
                return
            except Exception as error:
                print(f"[WARN] 쿠키 로드 실패, 일반 로그인을 시도합니다: {self._error_text(error)}")

        if not self.credentials.complete:
            missing = ", ".join(self.credentials.missing_names())
            raise AuthenticationError(f".env에 필수 계정 정보가 없습니다: {missing}")

        self._credential_login_attempted = True
        try:
            await self.client.login(
                auth_info_1=self.credentials.username,
                auth_info_2=self.credentials.email,
                password=self.credentials.password,
                cookies_file=None if force_credentials else str(COOKIE_PATH),
            )
            # force_credentials bypasses the stale cookie, so persist fresh cookies.
            if force_credentials:
                self.client.save_cookies(str(COOKIE_PATH))
            self._using_cookies = False
            print("[LOGIN] 로그인 성공")
        except Exception as error:
            raise AuthenticationError(f"로그인 실패: {self._error_text(error)}") from error

    async def _retry(
        self,
        operation: Callable[[], Awaitable[T]],
        label: str,
    ) -> T:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await operation()
            except AUTH_ERRORS:
                raise
            except RETRYABLE_ERRORS as error:
                if attempt == MAX_RETRIES:
                    raise
                delay = RETRY_BASE_DELAY * attempt
                print(
                    f"[WARN] {label} 일시 오류 ({attempt}/{MAX_RETRIES}): "
                    f"{self._error_text(error)} - {delay:.0f}초 후 재시도"
                )
                await self.sleep(delay)
        raise RuntimeError("재시도 로직이 예기치 않게 종료되었습니다")

    async def _first_page(self, keyword: str, product: str) -> Any:
        try:
            return await self._retry(
                lambda: self.client.search_tweet(keyword, product), "검색 요청"
            )
        except AUTH_ERRORS as error:
            if not self._using_cookies or self._credential_login_attempted:
                raise AuthenticationError(
                    f"인증이 거부되었습니다: {self._error_text(error)}"
                ) from error
            print("[WARN] 저장된 쿠키가 만료된 것으로 보여 일반 로그인을 시도합니다")
            await self.authenticate(force_credentials=True)
            try:
                return await self._retry(
                    lambda: self.client.search_tweet(keyword, product), "검색 요청"
                )
            except AUTH_ERRORS as retry_error:
                raise AuthenticationError(
                    f"재로그인 후에도 인증이 거부되었습니다: {self._error_text(retry_error)}"
                ) from retry_error
        except Exception as error:
            raise RuntimeError(f"검색 요청 실패: {self._error_text(error)}") from error

    async def run(self, keyword: str, product: str, max_count: int) -> list[dict[str, Any]]:
        tweets = await self._first_page(keyword, product)
        page_number = 1
        previous_cursors: set[str] = set()
        stalled_pages = 0

        while tweets and page_number <= MAX_PAGES and len(self.results) < max_count:
            page_items = list(tweets)
            print(f"[PAGE {page_number}] 게시글 {len(page_items)}개 발견")
            before_count = len(self.results)

            for tweet in page_items:
                if len(self.results) >= max_count:
                    break
                try:
                    tweet_id = safe_getattr(tweet, "id")
                    if tweet_id is None or str(tweet_id) in self.seen_ids:
                        continue
                    record = normalize_tweet(tweet, keyword)
                    self.seen_ids.add(str(tweet_id))
                    self.results.append(record)
                    username = record.get("username") or "unknown"
                    print(f"[COLLECT] {len(self.results)}/{max_count} @{username}")
                except Exception as error:
                    print(f"[ERROR] 게시글 데이터 파싱 실패: {self._error_text(error)}")

            print(f"현재 수집: {len(self.results)} / {max_count}")
            if len(self.results) >= max_count:
                break

            stalled_pages = stalled_pages + 1 if len(self.results) == before_count else 0
            if stalled_pages >= MAX_STALLED_PAGES:
                print("[WARN] 새 게시글이 없는 페이지가 반복되어 종료합니다")
                break

            cursor = getattr(tweets, "next_cursor", None)
            if cursor is None:
                print("[INFO] 다음 검색 결과가 없습니다")
                break
            if str(cursor) in previous_cursors:
                print("[WARN] 동일한 페이지 커서가 반복되어 종료합니다")
                break
            previous_cursors.add(str(cursor))

            delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            print(f"[PAGE {page_number + 1}] 다음 검색 결과 요청 ({delay:.1f}초 대기)")
            await self.sleep(delay)
            try:
                tweets = await self._retry(tweets.next, "다음 페이지 요청")
            except AUTH_ERRORS as error:
                raise AuthenticationError(
                    f"페이지 요청 중 인증이 만료되었습니다: {self._error_text(error)}"
                ) from error
            except Exception as error:
                print(f"[ERROR] 다음 페이지 요청 실패: {self._error_text(error)}")
                break
            page_number += 1

        if page_number > MAX_PAGES:
            print(f"[WARN] 안전 한도({MAX_PAGES}페이지)에 도달하여 종료합니다")
        if not self.results:
            print("[INFO] 검색 결과가 없습니다")
        return self.results
