"""Temporary compatibility fixes for known Twikit 2.3.3/X changes.

These patches mirror upstream d60/twikit PRs #411 and #412. They live in the
project instead of site-packages so recreating the virtual environment does not
silently remove them. The patches are skipped for any other Twikit version.
"""

from __future__ import annotations

import re
from typing import Any

import twikit
from bs4 import BeautifulSoup
from twikit.client.gql import Endpoint, GQLClient
from twikit.constants import FEATURES
from twikit.user import User
from twikit.x_client_transaction import transaction as transaction_module


PATCHED_VERSION = "2.3.3"
ON_DEMAND_CHUNK_REGEX = re.compile(r",(\d+)\s*:\s*['\"]ondemand\.s['\"]")
INDICES_REGEX = re.compile(r"\[(\d+)\]\s*,\s*16")


async def _get_indices_webpack_compat(
    self: Any, home_page_response: Any, session: Any, headers: dict[str, str]
) -> tuple[int, list[int]]:
    """Resolve X's newer two-stage webpack mapping for ondemand.s."""
    response = self.validate_response(home_page_response) or self.home_page_response
    response_text = str(response)
    chunk_match = ON_DEMAND_CHUNK_REGEX.search(response_text)
    key_byte_indices: list[int] = []

    # As of August 2026, x.com serves a minimal logged-out shell without the
    # webpack map, while x.com/home still includes the required ondemand entry.
    if not chunk_match:
        home_response = await session.request(
            method="GET",
            url="https://x.com/home",
            headers=headers,
            follow_redirects=True,
        )
        response = BeautifulSoup(home_response.content, "lxml")
        self.home_page_response = self.validate_response(response)
        response_text = str(response)
        chunk_match = ON_DEMAND_CHUNK_REGEX.search(response_text)

    if chunk_match:
        chunk_index = re.escape(chunk_match.group(1))
        hash_regex = re.compile(
            rf",{chunk_index}\s*:\s*['\"]([0-9a-f]+)['\"]",
            flags=re.IGNORECASE,
        )
        hash_match = hash_regex.search(response_text)
        if hash_match:
            file_hash = hash_match.group(1)
            url = (
                "https://abs.twimg.com/responsive-web/client-web/"
                f"ondemand.s.{file_hash}a.js"
            )
            js_response = await session.request(method="GET", url=url, headers=headers)
            key_byte_indices = [
                int(match.group(1)) for match in INDICES_REGEX.finditer(js_response.text)
            ]

    if not key_byte_indices:
        raise RuntimeError(
            "X 페이지에서 KEY_BYTE 인덱스를 찾지 못했습니다. "
            "X 구조가 다시 변경되었을 수 있습니다."
        )
    return key_byte_indices[0], key_byte_indices[1:]


async def _search_timeline_post(
    self: Any,
    query: str,
    product: str,
    count: int,
    cursor: str | None,
) -> Any:
    """Use POST for SearchTimeline, matching upstream PR #412."""
    variables = {
        "rawQuery": query,
        "count": count,
        "querySource": "typed_query",
        "product": product,
    }
    if cursor is not None:
        variables["cursor"] = cursor
    return await self.gql_post(Endpoint.SEARCH_TIMELINE, variables, FEATURES)


def _user_init_optional_fields(self: Any, client: Any, data: dict[str, Any]) -> None:
    """Treat current X user legacy fields as optional (upstream PR #418)."""
    self._client = client
    legacy = data.get("legacy", {})

    self.id = data.get("rest_id", "")
    self.created_at = legacy.get("created_at", "")
    self.name = legacy.get("name", "")
    self.screen_name = legacy.get("screen_name", "")
    self.profile_image_url = legacy.get("profile_image_url_https", "")
    self.profile_banner_url = legacy.get("profile_banner_url")
    self.url = legacy.get("url")
    self.location = legacy.get("location", "")
    self.description = legacy.get("description", "")
    entities = legacy.get("entities", {})
    self.description_urls = entities.get("description", {}).get("urls", [])
    self.urls = entities.get("url", {}).get("urls")
    self.pinned_tweet_ids = legacy.get("pinned_tweet_ids_str", [])
    self.is_blue_verified = data.get("is_blue_verified", False)
    self.verified = legacy.get("verified", False)
    self.possibly_sensitive = legacy.get("possibly_sensitive", False)
    self.can_dm = legacy.get("can_dm", False)
    self.can_media_tag = legacy.get("can_media_tag", False)
    self.want_retweets = legacy.get("want_retweets", False)
    self.default_profile = legacy.get("default_profile", False)
    self.default_profile_image = legacy.get("default_profile_image", False)
    self.has_custom_timelines = legacy.get("has_custom_timelines", False)
    self.followers_count = legacy.get("followers_count", 0)
    self.fast_followers_count = legacy.get("fast_followers_count", 0)
    self.normal_followers_count = legacy.get("normal_followers_count", 0)
    self.following_count = legacy.get("friends_count", 0)
    self.favourites_count = legacy.get("favourites_count", 0)
    self.listed_count = legacy.get("listed_count", 0)
    self.media_count = legacy.get("media_count", 0)
    self.statuses_count = legacy.get("statuses_count", 0)
    self.is_translator = legacy.get("is_translator", False)
    self.translator_type = legacy.get("translator_type", "")
    self.withheld_in_countries = legacy.get("withheld_in_countries", [])
    self.protected = legacy.get("protected", False)


def apply_twikit_compatibility() -> bool:
    """Apply known 2.3.3 fixes once; return whether this version needs them."""
    if getattr(twikit, "__version__", None) != PATCHED_VERSION:
        return False
    transaction_module.ClientTransaction.get_indices = _get_indices_webpack_compat
    GQLClient.search_timeline = _search_timeline_post
    User.__init__ = _user_init_optional_fields
    return True
