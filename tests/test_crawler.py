from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup
from config import Credentials
from crawler import XKeywordCrawler
from twikit.errors import Unauthorized
from twikit.user import User
from twikit.x_client_transaction import ClientTransaction
from twikit_compat import apply_twikit_compatibility
from utils import redact_error, save_results


async def no_sleep(_: float) -> None:
    return None


class FakeResult:
    def __init__(self, items, next_result=None, cursor=None):
        self.items = items
        self.next_result = next_result
        self.next_cursor = cursor

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        return bool(self.items)

    async def next(self):
        return self.next_result or FakeResult([])


class FakeClient:
    def __init__(self, result):
        self.result = result

    async def search_tweet(self, keyword, product):
        return self.result


class ExpiredCookieClient:
    def __init__(self):
        self.login_count = 0
        self.search_count = 0
        self.saved_path = None

    def load_cookies(self, path):
        return None

    async def login(self, **kwargs):
        self.login_count += 1

    def save_cookies(self, path):
        self.saved_path = path

    async def search_tweet(self, keyword, product):
        self.search_count += 1
        if self.search_count == 1:
            raise Unauthorized("expired")
        return FakeResult([tweet("recovered")])


class BrowserCookieClient:
    def __init__(self):
        self.cookies = None
        self.saved_path = None

    def set_cookies(self, cookies):
        self.cookies = cookies

    def save_cookies(self, path):
        self.saved_path = path


class PartiallyBrokenTweet:
    id = "broken-1"
    user = SimpleNamespace(id="u1", name="tester", screen_name="tester")
    text = "fallback text"
    created_at = "now"

    @property
    def full_text(self):
        raise KeyError("note_tweet")

    @property
    def favorite_count(self):
        raise KeyError("favorite_count")


class FakeJsSession:
    def __init__(self):
        self.requested_url = None

    async def request(self, *, method, url, headers):
        self.requested_url = url
        return SimpleNamespace(text="value([7], 16); other([12],16)")


class FakeHomeFallbackSession:
    def __init__(self):
        self.requested_urls = []

    async def request(self, *, method, url, headers, **kwargs):
        self.requested_urls.append(url)
        if url == "https://x.com/home":
            return SimpleNamespace(
                content=(
                    b'<html><script>,59924:"ondemand.s";'
                    b'x,59924:"feed456"</script></html>'
                )
            )
        return SimpleNamespace(text="value([39],16);x([1], 16);y([40],16)")


def tweet(tweet_id: str, username: str | None = "tester"):
    user = (
        SimpleNamespace(id="u1", name="테스터", screen_name=username)
        if username
        else None
    )
    return SimpleNamespace(
        id=tweet_id,
        user=user,
        full_text=f"text-{tweet_id}",
        created_at="Tue Aug 18 00:00:00 +0000 2026",
        favorite_count=1,
        retweet_count=2,
        reply_count=3,
        view_count=4,
    )


class CrawlerTests(unittest.IsolatedAsyncioTestCase):
    def test_user_optional_fields_compatibility(self):
        apply_twikit_compatibility()

        user = User(None, {"rest_id": "u1", "legacy": {"screen_name": "tester"}})

        self.assertEqual(user.screen_name, "tester")
        self.assertEqual(user.withheld_in_countries, [])
        self.assertEqual(user.followers_count, 0)

    async def test_browser_cookies_bypass_password_login(self):
        with tempfile.TemporaryDirectory() as directory:
            cookie_path = Path(directory) / "cookies.json"
            client = BrowserCookieClient()
            crawler = XKeywordCrawler(
                Credentials("user", None, "secret", "token-value", "ct0-value"),
                client=client,
                sleep=no_sleep,
            )

            with patch("crawler.COOKIE_PATH", cookie_path):
                await crawler.authenticate()

            self.assertEqual(
                client.cookies,
                {"auth_token": "token-value", "ct0": "ct0-value"},
            )
            self.assertEqual(client.saved_path, str(cookie_path))

    def test_html_error_body_and_ip_are_not_logged(self):
        error = RuntimeError(
            'status: 403, message: "<!DOCTYPE html><html>Your IP: 192.0.2.1</html>"'
        )

        message = redact_error(error, [])

        self.assertIn("HTTP 403", message)
        self.assertNotIn("192.0.2.1", message)
        self.assertNotIn("DOCTYPE", message)

    async def test_key_byte_compatibility_parser(self):
        apply_twikit_compatibility()
        html = BeautifulSoup(
            '<html><script>,3141:"ondemand.s";x,3141:"abc123"</script></html>',
            "html.parser",
        )
        session = FakeJsSession()

        row_index, remaining = await ClientTransaction().get_indices(
            html, session, {}
        )

        self.assertEqual((row_index, remaining), (7, [12]))
        self.assertTrue(session.requested_url.endswith("ondemand.s.abc123a.js"))

    async def test_key_byte_parser_falls_back_to_home_route(self):
        apply_twikit_compatibility()
        minimal_shell = BeautifulSoup("<html></html>", "html.parser")
        session = FakeHomeFallbackSession()

        row_index, remaining = await ClientTransaction().get_indices(
            minimal_shell, session, {}
        )

        self.assertEqual((row_index, remaining), (39, [1, 40]))
        self.assertEqual(session.requested_urls[0], "https://x.com/home")
        self.assertTrue(session.requested_urls[1].endswith("ondemand.s.feed456a.js"))

    def test_email_is_optional_for_credentials(self):
        credentials = Credentials("user", None, "secret")

        self.assertTrue(credentials.complete)
        self.assertEqual(credentials.missing_names(), [])

    async def test_expired_cookie_falls_back_to_credentials_once(self):
        with tempfile.TemporaryDirectory() as directory:
            cookie_path = Path(directory) / "cookies.json"
            cookie_path.write_text("{}", encoding="utf-8")
            client = ExpiredCookieClient()
            crawler = XKeywordCrawler(
                Credentials("user", "user@example.com", "secret"),
                client=client,
                sleep=no_sleep,
            )

            with patch("crawler.COOKIE_PATH", cookie_path):
                await crawler.authenticate()
                results = await crawler.run("query", "Latest", 1)

            self.assertEqual(client.login_count, 1)
            self.assertEqual(client.search_count, 2)
            self.assertEqual(client.saved_path, str(cookie_path))
            self.assertEqual(results[0]["tweet_id"], "recovered")

    async def test_paginates_deduplicates_and_honors_limit(self):
        page2 = FakeResult([tweet("2"), tweet("3")], cursor=None)
        page1 = FakeResult([tweet("1"), tweet("2")], page2, cursor="next-1")
        crawler = XKeywordCrawler(
            Credentials(None, None, None),
            client=FakeClient(page1),
            sleep=no_sleep,
        )

        results = await crawler.run("검색어", "Latest", 3)

        self.assertEqual([row["tweet_id"] for row in results], ["1", "2", "3"])
        self.assertEqual(results[0]["url"], "https://x.com/tester/status/1")

    async def test_missing_user_fields_do_not_abort_collection(self):
        crawler = XKeywordCrawler(
            Credentials(None, None, None),
            client=FakeClient(FakeResult([tweet("1", None)])),
            sleep=no_sleep,
        )

        results = await crawler.run("query", "Top", 1)

        self.assertIsNone(results[0]["username"])
        self.assertIsNone(results[0]["url"])

    async def test_broken_optional_property_uses_safe_default(self):
        crawler = XKeywordCrawler(
            Credentials(None, None, None),
            client=FakeClient(FakeResult([PartiallyBrokenTweet()])),
            sleep=no_sleep,
        )

        results = await crawler.run("query", "Latest", 1)

        self.assertEqual(results[0]["text"], "fallback text")
        self.assertIsNone(results[0]["favorite_count"])

    def test_csv_and_json_are_written_with_expected_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "tweets.csv"
            json_path = Path(directory) / "tweets.json"
            row = {
                "keyword": "개인정보",
                "tweet_id": "1",
                "text": "한글 본문",
            }

            save_results([row], csv_path, json_path)

            self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8"))[0]["text"],
                "한글 본문",
            )


if __name__ == "__main__":
    unittest.main()
